import os
import uuid
import json
import tempfile
import urllib.request
from urllib.parse import urlparse
from datetime import datetime

from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session

from api.database import get_db, engine, Base
from api.models import DFDSession, DataMappingRow, KnowledgeGraphNode, KnowledgeGraphEdge
from agent.schema_generator import SchemaGenerator
from utils.logger import setup_logger

logger = setup_logger("FastAPI")

Base.metadata.create_all(bind=engine)

app = FastAPI(title="PIA - Privacy Impact Assessment API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request / Response Models ────────────────────────

class InitiateRequest(BaseModel):
    session_id: str
    department: str
    files: List[str]
    use_rlm: bool = False
    aggressive_processing: bool = False

class InitiateResponse(BaseModel):
    session_id: str
    message: str

class StatusResponse(BaseModel):
    session_id: str
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

# ── Helpers ──────────────────────────────────────────

def _download_files(files: List[str], temp_dir: str) -> List[str]:
    """Download remote URLs or validate local paths. Returns list of local file paths."""
    local_files = []
    for file_ref in files:
        if file_ref.startswith("http://") or file_ref.startswith("https://"):
            logger.info(f"Downloading: {file_ref[:80]}...")
            parsed_url = urlparse(file_ref)
            filename = os.path.basename(parsed_url.path) or f"file_{len(local_files)}.txt"
            dest_path = os.path.join(temp_dir, filename)
            req = urllib.request.Request(file_ref, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response, open(dest_path, 'wb') as out_file:
                out_file.write(response.read())
            local_files.append(dest_path)
        else:
            if not os.path.exists(file_ref):
                raise FileNotFoundError(f"Local file not found: {file_ref}")
            local_files.append(file_ref)
    return local_files


def _combine_transcripts(local_files: List[str]) -> str:
    """Read and combine all transcript files into a single string."""
    combined = ""
    for lf in local_files:
        with open(lf, 'r', encoding='utf-8') as f:
            combined += f"\n--- File: {os.path.basename(lf)} ---\n"
            combined += f.read() + "\n"
    return combined


# ── Unified Background Pipeline ─────────────────────

def process_aggressive_pipeline(session_id: str, department: str, files: List[str], db: Session):
    try:
        logger.info(f"[{session_id}] Aggressive Pipeline starting for department: {department}")

        from test.orchestrator.pipeline_runner import PipelineRunner
        from test.agents.knowledge_graph_agent import KnowledgeGraphAgent
        from test.graph.html_generator import HTMLGeneratorAgent

        with tempfile.TemporaryDirectory() as temp_dir:
            # 1. Download and combine
            local_files = _download_files(files, temp_dir)
            combined_transcript = _combine_transcripts(local_files)
            combined_path = os.path.join(temp_dir, "combined_source.txt")
            with open(combined_path, "w") as f:
                f.write(combined_transcript)
            
            # 2. Run Pipeline (Phases 1-9)
            runner = PipelineRunner()
            result = runner.process_file(combined_path)

            # 3. Save to temp for Graph Builder
            pipeline_dir = os.path.join(temp_dir, "pipeline")
            os.makedirs(pipeline_dir)
            with open(os.path.join(pipeline_dir, "combined_intelligence.json"), "w") as f:
                json.dump(result, f, indent=2)

            # 4. Build Knowledge Graph
            graph_dir = os.path.join(temp_dir, "graph")
            os.makedirs(graph_dir)
            kg_agent = KnowledgeGraphAgent()
            kg_result = kg_agent.build_graph(pipeline_dir, graph_dir)

            # 5. Generate HTML DFD
            html_gen = HTMLGeneratorAgent()
            html_path = os.path.join(temp_dir, "privacy_dfd.html")
            html_gen.generate(graph_dir, pipeline_dir, html_path)
            
            interactive_html = ""
            if os.path.exists(html_path):
                with open(html_path, "r") as f:
                    interactive_html = f.read()

        # Parse graph JSON
        graph_json_path = os.path.join(graph_dir, "knowledge_graph.json")
        graph_data = {"nodes": [], "edges": []}
        if os.path.exists(graph_json_path):
            with open(graph_json_path, "r") as f:
                graph_data = json.load(f)

        # 6. Save everything to DB
        db_session = db.query(DFDSession).filter(DFDSession.session_id == session_id).first()
        if db_session:
            db_session.status = "completed"
            db_session.actors_json = result.get("actors")
            db_session.systems_json = result.get("systems")
            db_session.data_elements_json = result.get("data_elements")
            db_session.flows_json = result.get("flows")
            db_session.risks_json = result.get("risks")
            db_session.compliance_schema_json = result.get("compliance_schema")
            db_session.verification_report_json = result.get("verification_report")
            db_session.interactive_html = interactive_html
            db_session.dfd_json = kg_result
            db_session.updated_at = datetime.utcnow()
            db.commit()

        # Save KG Nodes
        for n in graph_data.get("nodes", []):
            db_node = KnowledgeGraphNode(
                id=str(uuid.uuid4()),
                session_id=session_id,
                node_id=n.get("id", ""),
                name=n.get("name", ""),
                type=n.get("type", ""),
                aliases=n.get("aliases", []),
                data_elements=n.get("data_elements", []),
                risks=n.get("risks", []),
                sources=n.get("sources", [])
            )
            db.add(db_node)
        
        # Save KG Edges
        for e in graph_data.get("edges", []):
            db_edge = KnowledgeGraphEdge(
                id=str(uuid.uuid4()),
                session_id=session_id,
                source_node=e.get("source", ""),
                target_node=e.get("target", ""),
                data_elements=e.get("data_elements", []),
                flow_type=e.get("flow_type", ""),
                channel=e.get("channel", ""),
                inferred=1 if e.get("inferred") else 0,
                sources=e.get("sources", [])
            )
            db.add(db_edge)

        # Save data mapping rows
        inventory_rows = result.get("data_inventory", [])
        s_no = 1
        for row in inventory_rows:
            db_row = DataMappingRow(
                id=str(uuid.uuid4()),
                session_id=session_id,
                s_no=s_no,
                data_category=row.get("data_category", "Unknown"),
                description=row.get("description", ""),
                purpose=row.get("purpose", ""),
                data_owner=row.get("data_owner", ""),
                storage_location=row.get("storage_location", ""),
                data_classification=row.get("data_classification", ""),
                retention_period=row.get("retention_period", ""),
                legal_basis=row.get("legal_basis", "")
            )
            db.add(db_row)
            s_no += 1
        db.commit()

        logger.info(f"[{session_id}] Aggressive Pipeline completed successfully")

    except Exception as e:
        logger.error(f"[{session_id}] Aggressive Pipeline failed: {str(e)}", exc_info=True)
        db_session = db.query(DFDSession).filter(DFDSession.session_id == session_id).first()
        if db_session:
            db_session.status = "failed"
            db_session.error_message = str(e)
            db_session.updated_at = datetime.utcnow()
            db.commit()


def process_unified_pipeline(session_id: str, department: str, files: List[str], db: Session):
    try:
        logger.info(f"[{session_id}] Pipeline starting for department: {department}")

        from config import Config
        from agent.ingestion import IngestionAgent
        from agent.kb_builder import KBBuilder
        from agent.retrieval import RetrievalAgent
        from agent.dfd_extractor import DFDExtractor
        from agent.dfd_validator import validate_dfd, format_validation_report
        from agent.privacy_dfd import PrivacyDFDAgent
        from agent.learning import LearningLoop

        Config.validate()

        with tempfile.TemporaryDirectory() as temp_dir:
            # ── 1. Download files ────────────────────
            local_files = _download_files(files, temp_dir)
            combined_transcript = _combine_transcripts(local_files)
            logger.info(f"[{session_id}] Downloaded and combined {len(local_files)} files")

            # ── 2. Ingest into KB (always use references) ──
            ingestion_agent = IngestionAgent()
            kb_builder = KBBuilder()
            retrieval_agent = RetrievalAgent()
            learning_loop = LearningLoop(kb_builder)

            extracted_data_list = []
            for idx, file_path in enumerate(local_files):
                data = ingestion_agent.ingest_transcript(file_path)
                extracted_data_list.append(data)
                with open(file_path, "r") as f:
                    content = f.read()
                metadata = {
                    "session": idx + 1,
                    "department": department,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "source": os.path.basename(file_path),
                }
                kb_builder.add_transcript(f"{department}_session_{idx+1}", content, metadata)

            # ── 3. Retrieve context from vector DB ───
            query = (
                f"Privacy compliance assessment for {department} department. "
                f"Personal data types, legal basis, consent management, data sharing."
            )
            context = retrieval_agent.retrieve_context(query)
            logger.info(f"[{session_id}] Context retrieved from vector DB")

            # ── 4. Schema Generation (Step 1 + 2) ────
            generator = SchemaGenerator()
            schema_one_json = generator.generate_schema_one(combined_transcript)
            logger.info(f"[{session_id}] Schema-1 generated")

            inventory_rows = generator.generate_data_inventory(schema_one_json)
            logger.info(f"[{session_id}] Data inventory generated ({len(inventory_rows)} rows)")

            # ── 5. DFD Extraction (with validation) ──
            dfd_extractor = DFDExtractor()
            dfd_json = dfd_extractor.extract(department, extracted_data_list, context)

            final_validation = validate_dfd(dfd_json)
            logger.info(f"[{session_id}] DFD validation: {final_validation['score']}/100")

            # ── 6. Mermaid Privacy DFD ────────────────
            privacy_dfd_agent = PrivacyDFDAgent()
            privacy_dfd_md = privacy_dfd_agent.generate_department_dfd(
                department, extracted_data_list, context
            )
            logger.info(f"[{session_id}] Mermaid Privacy DFD generated")

            # ── 7. Learning loop ─────────────────────
            learning_loop.process_feedback(
                f"report_{department}",
                json.dumps(dfd_json, indent=2),
                {"department": department, "date": datetime.now().strftime("%Y-%m-%d")}
            )

        # ── 8. Save everything to DB ─────────────────
        db_session = db.query(DFDSession).filter(DFDSession.session_id == session_id).first()
        if db_session:
            db_session.schema_one_json = schema_one_json
            db_session.dfd_json = dfd_json
            db_session.privacy_dfd_md = privacy_dfd_md
            db_session.status = "completed"
            db_session.updated_at = datetime.utcnow()
            db.commit()

        # Save data mapping rows
        s_no = 1
        for row in inventory_rows:
            db_row = DataMappingRow(
                id=str(uuid.uuid4()),
                session_id=session_id,
                s_no=s_no,
                data_category=row.get("data_category", "Unknown"),
                description=row.get("description", ""),
                purpose=row.get("purpose", ""),
                data_owner=row.get("data_owner", ""),
                storage_location=row.get("storage_location", ""),
                data_classification=row.get("data_classification", ""),
                retention_period=row.get("retention_period", ""),
                legal_basis=row.get("legal_basis", "")
            )
            db.add(db_row)
            s_no += 1
        db.commit()

        logger.info(f"[{session_id}] Pipeline completed successfully")

    except Exception as e:
        logger.error(f"[{session_id}] Pipeline failed: {str(e)}", exc_info=True)
        db_session = db.query(DFDSession).filter(DFDSession.session_id == session_id).first()
        if db_session:
            db_session.status = "failed"
            db_session.error_message = str(e)
            db_session.updated_at = datetime.utcnow()
            db.commit()


# ── API Endpoints ────────────────────────────────────

@app.post("/api/initiate", response_model=InitiateResponse)
def initiate(request: InitiateRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    existing = db.query(DFDSession).filter(DFDSession.session_id == request.session_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Session ID already exists")

    processing_mode = "normal"
    if request.aggressive_processing:
        processing_mode = "aggressive_processing"
    elif request.use_rlm:
        processing_mode = "rlm"

    new_session = DFDSession(
        session_id=request.session_id,
        department=request.department,
        status="processing",
        processing_mode=processing_mode
    )
    db.add(new_session)
    db.commit()

    if request.aggressive_processing:
        background_tasks.add_task(
            process_aggressive_pipeline,
            request.session_id, request.department, request.files, db
        )
    else:
        # Legacy unified pipeline (handles RLM inside via config or env if needed)
        background_tasks.add_task(
            process_unified_pipeline,
            request.session_id, request.department, request.files, db
        )

    return InitiateResponse(
        session_id=request.session_id,
        message="Pipeline started. Use /api/status/{session_id} to track progress."
    )


@app.get("/api/status/{session_id}", response_model=StatusResponse)
def get_status(session_id: str, db: Session = Depends(get_db)):
    s = db.query(DFDSession).filter(DFDSession.session_id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return StatusResponse(
        session_id=s.session_id,
        status=s.status,
        error_message=s.error_message,
        created_at=s.created_at,
        updated_at=s.updated_at
    )


@app.get("/api/results/{session_id}")
def get_results(session_id: str, db: Session = Depends(get_db)):
    s = db.query(DFDSession).filter(DFDSession.session_id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    mapping_rows = (
        db.query(DataMappingRow)
        .filter(DataMappingRow.session_id == session_id)
        .order_by(DataMappingRow.s_no)
        .all()
    )

    kg_nodes = (
        db.query(KnowledgeGraphNode)
        .filter(KnowledgeGraphNode.session_id == session_id)
        .all()
    )
    
    kg_edges = (
        db.query(KnowledgeGraphEdge)
        .filter(KnowledgeGraphEdge.session_id == session_id)
        .all()
    )

    return {
        "session_id": s.session_id,
        "status": s.status,
        "department": s.department,
        "processing_mode": s.processing_mode,
        "schema_one_json": s.schema_one_json,
        "dfd_json": s.dfd_json,
        "privacy_dfd_md": s.privacy_dfd_md,
        "actors_json": s.actors_json,
        "systems_json": s.systems_json,
        "data_elements_json": s.data_elements_json,
        "flows_json": s.flows_json,
        "risks_json": s.risks_json,
        "compliance_schema_json": s.compliance_schema_json,
        "verification_report_json": s.verification_report_json,
        "interactive_html": s.interactive_html,
        "knowledge_graph": {
            "nodes": [
                {
                    "node_id": n.node_id,
                    "name": n.name,
                    "type": n.type,
                    "aliases": n.aliases,
                    "data_elements": n.data_elements,
                    "risks": n.risks,
                    "sources": n.sources
                } for n in kg_nodes
            ],
            "edges": [
                {
                    "source_node": e.source_node,
                    "target_node": e.target_node,
                    "data_elements": e.data_elements,
                    "flow_type": e.flow_type,
                    "channel": e.channel,
                    "inferred": bool(e.inferred),
                    "sources": e.sources
                } for e in kg_edges
            ]
        },
        "data_mapping_rows": [
            {
                "s_no": row.s_no,
                "data_category": row.data_category,
                "description": row.description,
                "purpose": row.purpose,
                "data_owner": row.data_owner,
                "storage_location": row.storage_location,
                "data_classification": row.data_classification,
                "retention_period": row.retention_period,
                "legal_basis": row.legal_basis
            }
            for row in mapping_rows
        ]
    }


@app.delete("/api/session/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    s = db.query(DFDSession).filter(DFDSession.session_id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    db.query(DataMappingRow).filter(DataMappingRow.session_id == session_id).delete()
    db.query(KnowledgeGraphNode).filter(KnowledgeGraphNode.session_id == session_id).delete()
    db.query(KnowledgeGraphEdge).filter(KnowledgeGraphEdge.session_id == session_id).delete()
    db.delete(s)
    db.commit()

    return {"message": f"Session {session_id} and all related records deleted."}
