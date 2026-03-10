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
from api.models import DFDSession, DataMappingRow, KnowledgeGraphNode, KnowledgeGraphEdge, InteractiveDFD
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
    files: List[str] = []
    use_rlm: Optional[bool] = False
    aggressive_processing: Optional[bool] = False
    processing_mode: Optional[str] = None  # accepted but derived internally

class InitiateResponse(BaseModel):
    session_id: str
    message: str

class StatusResponse(BaseModel):
    session_id: str
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class InteractiveDFDCreate(BaseModel):
    name: str = "Untitled DFD"
    nodes: list = []
    edges: list = []
    levels: list = []
    pipeline_docs: dict = {}

class InteractiveDFDUpdate(BaseModel):
    name: Optional[str] = None
    nodes: Optional[list] = None
    edges: Optional[list] = None
    levels: Optional[list] = None
    pipeline_docs: Optional[dict] = None

class HTMLPreviewRequest(BaseModel):
    nodes: list = []
    edges: list = []
    levels: list = []
    pipeline_docs: dict = {}

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

            # 5b. Read graph JSONs BEFORE temp_dir is cleaned up
            graph_json_path = os.path.join(graph_dir, "graph", "knowledge_graph.json")
            graph_data = {"nodes": [], "edges": []}
            if os.path.exists(graph_json_path):
                with open(graph_json_path, "r") as f:
                    graph_data = json.load(f)

            render_plan_path = os.path.join(graph_dir, "graph", "dfd_render_plan.json")
            render_plan_data = {"levels": []}
            if os.path.exists(render_plan_path):
                with open(render_plan_path, "r") as f:
                    render_plan_data = json.load(f)

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
            db_session.dfd_render_plan_json = render_plan_data
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


def process_unified_pipeline(session_id: str, department: str, files: List[str], use_rlm: bool, db: Session):
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

            # ── 2. Ingest transcripts ────────────────
            kb_builder = KBBuilder()
            retrieval_agent = RetrievalAgent()
            learning_loop = LearningLoop(kb_builder)

            if use_rlm:
                # ── 2a. RLM-powered ingestion (all files at once) ──
                from agent.rlm_ingestion import RLMIngestionAgent
                logger.info(f"[{session_id}] Using RLM ingestion for cross-transcript analysis")
                rlm_agent = RLMIngestionAgent(verbose=False)
                try:
                    consolidated_data = rlm_agent.ingest_all(local_files)
                    extracted_data_list = [consolidated_data]
                    logger.info(f"[{session_id}] RLM ingestion completed successfully")
                except Exception as e:
                    logger.warning(f"[{session_id}] RLM ingestion failed, falling back to standard: {e}")
                    ingestion_agent = IngestionAgent()
                    extracted_data_list = []
                    for idx, file_path in enumerate(local_files):
                        data = ingestion_agent.ingest_transcript(file_path)
                        extracted_data_list.append(data)
            else:
                # ── 2b. Standard per-file ingestion (original behavior) ──
                ingestion_agent = IngestionAgent()
                extracted_data_list = []
                for idx, file_path in enumerate(local_files):
                    data = ingestion_agent.ingest_transcript(file_path)
                    extracted_data_list.append(data)

            # Always add transcripts to KB for context retrieval
            for idx, file_path in enumerate(local_files):
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
            schema_one_json = None
            inventory_rows = []

            generator = SchemaGenerator()
            try:
                schema_one_json = generator.generate_schema_one(combined_transcript)
                logger.info(f"[{session_id}] Schema-1 generated")
            except Exception as e:
                logger.error(f"[{session_id}] Schema-1 generation failed: {e}", exc_info=True)

            if schema_one_json:
                try:
                    inventory_rows = generator.generate_data_inventory(schema_one_json)
                    if not inventory_rows:
                        logger.warning(f"[{session_id}] Data inventory returned 0 rows — LLM may have hit token limit or returned empty inventory")
                    else:
                        logger.info(f"[{session_id}] Data inventory generated ({len(inventory_rows)} rows)")
                except Exception as e:
                    logger.error(f"[{session_id}] Data inventory generation failed: {e}", exc_info=True)
            else:
                logger.warning(f"[{session_id}] Skipping data inventory — Schema-1 was not generated")

            # ── 5. DFD Extraction (with validation) ──
            dfd_json = None
            try:
                dfd_extractor = DFDExtractor()
                dfd_json = dfd_extractor.extract(department, extracted_data_list, context)
                final_validation = validate_dfd(dfd_json)
                logger.info(f"[{session_id}] DFD validation: {final_validation['score']}/100")
            except Exception as e:
                logger.error(f"[{session_id}] DFD extraction failed: {e}", exc_info=True)

            # ── 6. Mermaid Privacy DFD ────────────────
            privacy_dfd_md = None
            try:
                privacy_dfd_agent = PrivacyDFDAgent()
                privacy_dfd_md = privacy_dfd_agent.generate_department_dfd(
                    department, extracted_data_list, context
                )
                logger.info(f"[{session_id}] Mermaid Privacy DFD generated")
            except Exception as e:
                logger.error(f"[{session_id}] Privacy DFD generation failed: {e}", exc_info=True)

            # ── 7. Learning loop ─────────────────────
            if dfd_json:
                try:
                    learning_loop.process_feedback(
                        f"report_{department}",
                        json.dumps(dfd_json, indent=2),
                        {"department": department, "date": datetime.now().strftime("%Y-%m-%d")}
                    )
                except Exception as e:
                    logger.warning(f"[{session_id}] Learning loop failed (non-critical): {e}")

        # ── 8. Save everything to DB ─────────────────
        db_session = db.query(DFDSession).filter(DFDSession.session_id == session_id).first()
        if db_session:
            db_session.schema_one_json = schema_one_json
            db_session.dfd_json = dfd_json
            db_session.privacy_dfd_md = privacy_dfd_md
            db_session.status = "completed"
            db_session.updated_at = datetime.utcnow()
            db.commit()

        # Save data mapping rows (with null-safe defaults)
        if inventory_rows:
            s_no = 1
            for row in inventory_rows:
                db_row = DataMappingRow(
                    id=str(uuid.uuid4()),
                    session_id=session_id,
                    s_no=s_no,
                    data_category=row.get("data_category") or "Unknown",
                    description=row.get("description") or "",
                    purpose=row.get("purpose") or "",
                    data_owner=row.get("data_owner") or "",
                    storage_location=row.get("storage_location") or "",
                    data_classification=row.get("data_classification") or "",
                    retention_period=row.get("retention_period") or "",
                    legal_basis=row.get("legal_basis") or ""
                )
                db.add(db_row)
                s_no += 1
            db.commit()
            logger.info(f"[{session_id}] Saved {s_no - 1} data mapping rows")
        else:
            logger.warning(f"[{session_id}] No data mapping rows to save")

        logger.info(f"[{session_id}] Pipeline completed successfully")

    except Exception as e:
        logger.error(f"[{session_id}] Pipeline failed: {str(e)}", exc_info=True)
        db_session = db.query(DFDSession).filter(DFDSession.session_id == session_id).first()
        if db_session:
            db_session.status = "failed"
            db_session.error_message = str(e)
            db_session.updated_at = datetime.utcnow()
            db.commit()


class UpdateSessionDFDRequest(BaseModel):
    session_id: str
    dfd_json: dict
    knowledge_graph: dict
    dfd_plan_json: dict

# ── API Endpoints ────────────────────────────────────

@app.post("/api/initiate", response_model=InitiateResponse)
def initiate(request: InitiateRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    existing = db.query(DFDSession).filter(DFDSession.session_id == request.session_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Session ID already exists")

    # Normalize None → False so downstream never sees None
    use_rlm = bool(request.use_rlm)
    aggressive = bool(request.aggressive_processing)

    processing_mode = "normal"
    if aggressive:
        processing_mode = "aggressive_processing"
    elif use_rlm:
        processing_mode = "rlm"

    new_session = DFDSession(
        session_id=request.session_id,
        department=request.department,
        status="processing",
        processing_mode=processing_mode
    )
    db.add(new_session)
    db.commit()

    if aggressive:
        background_tasks.add_task(
            process_aggressive_pipeline,
            request.session_id, request.department, request.files or [], db
        )
    else:
        background_tasks.add_task(
            process_unified_pipeline,
            request.session_id, request.department, request.files or [], use_rlm, db
        )

    return InitiateResponse(
        session_id=request.session_id,
        message="Pipeline started. Use /api/status/{session_id} to track progress."
    )


@app.post("/api/dfd/update_session")
def update_session_dfd(data: UpdateSessionDFDRequest, db: Session = Depends(get_db)):
    """
    Manually update DFD data for a session and regenerate its interactive HTML.
    Updates dfd_json, dfd_render_plan_json, and the Knowledge Graph tables.
    """
    # 1. Find session
    db_session = db.query(DFDSession).filter(DFDSession.session_id == data.session_id).first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # 2. Update main session record
    db_session.dfd_json = data.dfd_json
    db_session.dfd_render_plan_json = data.dfd_plan_json
    
    # 3. Update Knowledge Graph Tables
    # Clear existing nodes and edges for this session
    db.query(KnowledgeGraphNode).filter(KnowledgeGraphNode.session_id == data.session_id).delete()
    db.query(KnowledgeGraphEdge).filter(KnowledgeGraphEdge.session_id == data.session_id).delete()
    
    nodes = data.knowledge_graph.get("nodes", [])
    edges = data.knowledge_graph.get("edges", [])
    
    for n in nodes:
        db_node = KnowledgeGraphNode(
            id=str(uuid.uuid4()),
            session_id=data.session_id,
            node_id=n.get("id") or n.get("node_id") or "",
            name=n.get("name", ""),
            type=n.get("type", ""),
            aliases=n.get("aliases", []),
            data_elements=n.get("data_elements", []),
            risks=n.get("risks", []),
            sources=n.get("sources", [])
        )
        db.add(db_node)
        
    for e in edges:
        db_edge = KnowledgeGraphEdge(
            id=str(uuid.uuid4()),
            session_id=data.session_id,
            source_node=e.get("source") or e.get("source_node") or "",
            target_node=e.get("target") or e.get("target_node") or "",
            data_elements=e.get("data_elements", []),
            flow_type=e.get("flow_type", ""),
            channel=e.get("channel", ""),
            inferred=1 if e.get("inferred") else 0,
            sources=e.get("sources", [])
        )
        db.add(db_edge)
        
    # 4. Re-generate Interactive HTML
    from test.graph.html_generator import HTMLGeneratorAgent
    html_gen = HTMLGeneratorAgent()
    
    kg = data.knowledge_graph
    levels = data.dfd_plan_json.get("levels", [])
    
    # Reconstruct col/row maps and generate HTML
    col_map = html_gen._build_column_map(nodes, levels, kg)
    row_map = html_gen._build_row_map(nodes)
    
    # Generate HTML string (passing empty dict for pipeline_docs as default)
    interactive_html = html_gen._build_html(nodes, edges, kg, {}, col_map, row_map)
    db_session.interactive_html = interactive_html
    
    db_session.updated_at = datetime.utcnow()
    db.commit()
    
    return {
        "status": "success",
        "message": "Session DFD data and HTML updated successfully",
        "session_id": data.session_id
    }



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
        "dfd_render_plan": s.dfd_render_plan_json,
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

# ── Interactive DFD CRUD & Preview ────────────────────────────

@app.post("/api/interactive_dfd", response_model=dict)
def create_interactive_dfd(data: InteractiveDFDCreate, db: Session = Depends(get_db)):
    db_obj = InteractiveDFD(
        id=str(uuid.uuid4()),
        name=data.name,
        nodes=data.nodes,
        edges=data.edges,
        levels=data.levels,
        pipeline_docs=data.pipeline_docs
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return {"id": db_obj.id, "message": "Interactive DFD created successfully"}

@app.get("/api/interactive_dfd/{dfd_id}", response_model=dict)
def get_interactive_dfd(dfd_id: str, db: Session = Depends(get_db)):
    db_obj = db.query(InteractiveDFD).filter(InteractiveDFD.id == dfd_id).first()
    if not db_obj:
        raise HTTPException(status_code=404, detail="DFD not found")
    return {
        "id": db_obj.id,
        "name": db_obj.name,
        "nodes": db_obj.nodes,
        "edges": db_obj.edges,
        "levels": db_obj.levels,
        "pipeline_docs": db_obj.pipeline_docs,
        "created_at": db_obj.created_at,
        "updated_at": db_obj.updated_at
    }

@app.put("/api/interactive_dfd/{dfd_id}", response_model=dict)
def update_interactive_dfd(dfd_id: str, data: InteractiveDFDUpdate, db: Session = Depends(get_db)):
    db_obj = db.query(InteractiveDFD).filter(InteractiveDFD.id == dfd_id).first()
    if not db_obj:
        raise HTTPException(status_code=404, detail="DFD not found")
    
    if data.name is not None: db_obj.name = data.name
    if data.nodes is not None: db_obj.nodes = data.nodes
    if data.edges is not None: db_obj.edges = data.edges
    if data.levels is not None: db_obj.levels = data.levels
    if data.pipeline_docs is not None: db_obj.pipeline_docs = data.pipeline_docs
    
    db_obj.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "DFD updated successfully"}

@app.delete("/api/interactive_dfd/{dfd_id}", response_model=dict)
def delete_interactive_dfd(dfd_id: str, db: Session = Depends(get_db)):
    db_obj = db.query(InteractiveDFD).filter(InteractiveDFD.id == dfd_id).first()
    if not db_obj:
        raise HTTPException(status_code=404, detail="DFD not found")
    db.delete(db_obj)
    db.commit()
    return {"message": "DFD deleted successfully"}

# ── Dynamic HTML Generator API ────────────────────────────────

from fastapi.responses import HTMLResponse

@app.post("/api/dfd/preview")
def preview_html(data: HTMLPreviewRequest):
    """Generate HTML DFD view directly from JSON body payload."""
    from test.graph.html_generator import HTMLGeneratorAgent
    
    html_gen = HTMLGeneratorAgent()
    kg = {"nodes": data.nodes, "edges": data.edges}
    
    col_map = html_gen._build_column_map(data.nodes, data.levels, kg)
    row_map = html_gen._build_row_map(data.nodes)
    html = html_gen._build_html(data.nodes, data.edges, kg, data.pipeline_docs, col_map, row_map)
    
    return {"html": html}

@app.get("/api/interactive_dfd/{dfd_id}/preview", response_class=HTMLResponse)
def preview_db_html(dfd_id: str, db: Session = Depends(get_db)):
    """Returns the raw HTML document for a saved DFD."""
    db_obj = db.query(InteractiveDFD).filter(InteractiveDFD.id == dfd_id).first()
    if not db_obj:
        raise HTTPException(status_code=404, detail="DFD not found")
    
    from test.graph.html_generator import HTMLGeneratorAgent
    
    html_gen = HTMLGeneratorAgent()
    kg = {"nodes": db_obj.nodes, "edges": db_obj.edges}
    
    col_map = html_gen._build_column_map(db_obj.nodes, db_obj.levels, kg)
    row_map = html_gen._build_row_map(db_obj.nodes)
    html = html_gen._build_html(db_obj.nodes, db_obj.edges, kg, db_obj.pipeline_docs, col_map, row_map)
    
    return html
