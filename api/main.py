# ── Monkey-patch pydantic v1 for Python 3.12+ / spacy compat ──
import re
try:
    import pydantic.v1.validators as _pv1
    if not hasattr(_pv1, "REGEX"):
        _pv1.REGEX = type(re.compile(""))
except ImportError:
    pass

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

from api.database import get_db, engine, Base, SessionLocal
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
    token: str

class InitiateResponse(BaseModel):
    session_id: str
    message: str

class StatusResponse(BaseModel):
    session_id: str
    status: str
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
# ── DFD Data Schemas (exact shape required by HTMLGeneratorAgent) ──

class DFDRisk(BaseModel):
    description: str = ""
    severity: str = "MEDIUM"  # HIGH, MEDIUM, LOW
    risk_name: str = ""       # optional risk identifier
    source: str = ""          # originating source file

class DFDNode(BaseModel):
    id: str                                  # unique node identifier
    name: str                                # display label
    type: str = "unknown"                    # "actor" | "system" | "data_store" | "unknown"
    aliases: List[str] = []
    data_elements: List[str] = []            # e.g. ["PII", "Phone Number"]
    risks: List[DFDRisk] = []
    sources: List[str] = []                  # originating transcript filenames

class DFDEdge(BaseModel):
    source: str                              # must match a DFDNode.id
    target: str                              # must match a DFDNode.id
    data_elements: List[str] = []
    flow_type: str = "transfer"              # "collection" | "transfer" | "processing" | "storage" | "dispersal"
    channel: str = ""
    inferred: bool = False
    evidence: List[str] = []
    sources: List[str] = []

class HTMLPreviewRequest(BaseModel):
    nodes: List[DFDNode] = []
    edges: List[DFDEdge] = []
    levels: List[List[str]] = []             # [["Customer"], ["IVR", "Ameyo"], ["CRM"]]
    pipeline_docs: dict = {}

# ── Helpers ──────────────────────────────────────────

def _download_files(files: List[str], temp_dir: str) -> List[str]:
    """Download remote URLs or validate local paths. Returns list of local file paths."""
    local_files = []
    for file_ref in files:
        if file_ref.startswith("http://") or file_ref.startswith("https://"):
            logger.info(f"Downloading: {file_ref[:100]}...")
            try:
                parsed_url = urlparse(file_ref)
                filename = os.path.basename(parsed_url.path) or f"file_{len(local_files)}.txt"
                dest_path = os.path.join(temp_dir, filename)
                
                req = urllib.request.Request(file_ref, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response, open(dest_path, 'wb') as out_file:
                    out_file.write(response.read())
                local_files.append(dest_path)
                logger.info(f"Successfully downloaded to: {dest_path}")
            except urllib.error.HTTPError as e:
                error_body = e.read().decode('utf-8', errors='ignore')
                logger.error(f"HTTP Error {e.code} downloading {file_ref[:100]}: {error_body}")
                
                # Check for Supabase/JWT specific errors
                detail_msg = f"Failed to download file {filename}: {e.reason}"
                if "InvalidJWT" in error_body or "exp" in error_body.lower():
                    detail_msg = f"Supabase link expired for {filename}. Please generate a new token with fresh signed URLs."
                
                raise HTTPException(status_code=400, detail=detail_msg)
            except Exception as e:
                logger.error(f"Unexpected error downloading {file_ref[:100]}: {e}")
                raise e
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

def process_aggressive_pipeline(session_id: str, department: str, files: List[str], ai_config: dict = None):
    from api.database import SessionLocal
    db = SessionLocal()
    try:
        logger.info(f"[{session_id}] Aggressive Pipeline starting for department: {department}")

        from test.orchestrator.pipeline_runner import PipelineRunner
        from test.agents.knowledge_graph_agent import KnowledgeGraphAgent
        from test.graph.html_generator import HTMLGeneratorAgent

        ai_config = ai_config or {}


        with tempfile.TemporaryDirectory() as temp_dir:
            # 1. Download and combine
            local_files = _download_files(files, temp_dir)
            combined_transcript = _combine_transcripts(local_files)
            combined_path = os.path.join(temp_dir, "combined_source.txt")
            with open(combined_path, "w") as f:
                f.write(combined_transcript)
            
            # 2. Run Pipeline (Phases 1-9)
            runner = PipelineRunner(ai_config=ai_config)
            result = runner.process_file(combined_path)

            # 3. Save to temp for Graph Builder
            pipeline_dir = os.path.join(temp_dir, "pipeline")
            os.makedirs(pipeline_dir)
            with open(os.path.join(pipeline_dir, "combined_intelligence.json"), "w") as f:
                json.dump(result, f, indent=2)

            # 4. Build Knowledge Graph
            graph_dir = os.path.join(temp_dir, "graph")
            os.makedirs(graph_dir)
            kg_agent = KnowledgeGraphAgent(ai_config=ai_config)
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

            # 6. Schema Generation (Schema-1 + Data Inventory)
            schema_one_json = None
            inventory_rows = []

            generator = SchemaGenerator(ai_config=ai_config)
            try:
                schema_one_json = generator.generate_schema_one(combined_transcript)
                logger.info(f"[{session_id}] Schema-1 generated")
            except Exception as e:
                logger.error(f"[{session_id}] Schema-1 generation failed: {e}", exc_info=True)

            if schema_one_json:
                try:
                    inventory_rows = generator.generate_data_inventory(schema_one_json)
                    if not inventory_rows:
                        logger.warning(f"[{session_id}] Data inventory returned 0 rows")
                    else:
                        logger.info(f"[{session_id}] Data inventory generated ({len(inventory_rows)} rows)")
                except Exception as e:
                    logger.error(f"[{session_id}] Data inventory generation failed: {e}", exc_info=True)
            else:
                logger.warning(f"[{session_id}] Skipping data inventory — Schema-1 was not generated")

        # 6. Save everything to DB
        db_session = db.query(DFDSession).filter(DFDSession.session_id == session_id).first()
        if db_session:
            db_session.status = "completed"
            db_session.schema_one_json = schema_one_json
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

        # Save KG Nodes
        kg_nodes_list = graph_data.get("nodes", [])
        kg_edges_list = graph_data.get("edges", [])
        logger.info(f"[{session_id}] graph_data loaded: {len(kg_nodes_list)} nodes, {len(kg_edges_list)} edges")

        for n in kg_nodes_list:
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
        for e in kg_edges_list:
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

        # Save data mapping rows (prefer schema-generated, fallback to pipeline)
        if not inventory_rows:
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

        # Single commit for all DB operations
        db.commit()
        logger.info(f"[{session_id}] DB committed: {len(kg_nodes_list)} KG nodes, {len(kg_edges_list)} KG edges, {len(inventory_rows)} mapping rows")

        logger.info(f"[{session_id}] Aggressive Pipeline completed successfully")

    except Exception as e:
        logger.error(f"[{session_id}] Aggressive Pipeline failed: {str(e)}", exc_info=True)
        try:
            db.rollback()
            db_session = db.query(DFDSession).filter(DFDSession.session_id == session_id).first()
            if db_session:
                db_session.status = "failed"
                db_session.error_message = str(e)
                db_session.updated_at = datetime.utcnow()
                db.commit()
        except Exception:
            logger.error(f"[{session_id}] Failed to update error status in DB", exc_info=True)
    finally:
        db.close()



class UpdateSessionDFDRequest(BaseModel):
    session_id: str
    nodes: List[DFDNode] = []
    edges: List[DFDEdge] = []
    levels: List[List[str]] = []             # render plan levels
    pipeline_docs: dict = {}

# ── API Endpoints ────────────────────────────────────

@app.post("/api/initiate", response_model=InitiateResponse)
def initiate(request: InitiateRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    import jwt
    from config import Config
    
    try:
        logger.info(f"Initiating with token: {request.token[:10]}...")
        if not Config.PAYLOAD_TOKEN:
            raise ValueError("Config.PAYLOAD_TOKEN is missing")
            
        decoded = jwt.decode(
            request.token, 
            Config.PAYLOAD_TOKEN, 
            algorithms=["HS256"],
            options={"verify_exp": False}
        )
        ai_config = decoded.get("ai_config", {})
        payload_data = decoded.get("data", {})
    except Exception as e:
        logger.error(f"JWT decode error: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid or missing token: {str(e)}")
        
    req_session_id = payload_data.get("session_id")
    req_department = payload_data.get("department")
    req_files = payload_data.get("files", [])
    
    if not req_session_id or not req_department:
        raise HTTPException(status_code=400, detail="Missing required session_id or department in token data")

    # Clean up existing session if re-running
    existing = db.query(DFDSession).filter(DFDSession.session_id == req_session_id).first()
    if existing:
        db.query(DataMappingRow).filter(DataMappingRow.session_id == req_session_id).delete()
        db.query(KnowledgeGraphNode).filter(KnowledgeGraphNode.session_id == req_session_id).delete()
        db.query(KnowledgeGraphEdge).filter(KnowledgeGraphEdge.session_id == req_session_id).delete()
        db.delete(existing)
        db.commit()
        logger.info(f"[{req_session_id}] Existing session deleted — restarting pipeline")

    new_session = DFDSession(
        session_id=req_session_id,
        department=req_department,
        status="processing",
        processing_mode="aggressive"
    )
    db.add(new_session)
    db.commit()

    background_tasks.add_task(
        process_aggressive_pipeline,
        req_session_id, req_department, req_files or [], ai_config
    )

    return InitiateResponse(
        session_id=req_session_id,
        message="Pipeline started. Use /api/status/{session_id} to track progress."
    )


@app.post("/api/dfd/update_session")
def update_session_dfd(data: UpdateSessionDFDRequest, db: Session = Depends(get_db)):
    """
    Update DFD data for a session and regenerate its interactive HTML.
    Accepts typed nodes, edges, levels — the exact shape HTMLGeneratorAgent needs.
    """
    # 1. Find session
    db_session = db.query(DFDSession).filter(DFDSession.session_id == data.session_id).first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Convert Pydantic models to plain dicts for DB storage and HTML generator
    nodes_dicts = [n.model_dump() for n in data.nodes]
    edges_dicts = [e.model_dump() for e in data.edges]
    
    # 2. Update main session record
    kg_json = {"nodes": nodes_dicts, "edges": edges_dicts}
    db_session.dfd_json = kg_json
    db_session.dfd_render_plan_json = {"levels": data.levels}
    
    # 3. Replace Knowledge Graph rows
    db.query(KnowledgeGraphNode).filter(KnowledgeGraphNode.session_id == data.session_id).delete()
    db.query(KnowledgeGraphEdge).filter(KnowledgeGraphEdge.session_id == data.session_id).delete()
    
    for n in nodes_dicts:
        db.add(KnowledgeGraphNode(
            id=str(uuid.uuid4()),
            session_id=data.session_id,
            node_id=n.get("id", n.get("node_id", "")),
            name=n.get("name", ""),
            type=n.get("type", "unknown"),
            aliases=n.get("aliases", []),
            data_elements=n.get("data_elements", []),
            risks=n.get("risks", []),
            sources=n.get("sources", [])
        ))
    
    for e in edges_dicts:
        db.add(KnowledgeGraphEdge(
            id=str(uuid.uuid4()),
            session_id=data.session_id,
            source_node=e.get("source", e.get("source_node", "")),
            target_node=e.get("target", e.get("target_node", "")),
            data_elements=e.get("data_elements", []),
            flow_type=e.get("flow_type", ""),
            channel=e.get("channel", ""),
            inferred=1 if e.get("inferred") else 0,
            sources=e.get("sources", [])
        ))
    
    # 4. Re-generate Interactive HTML
    from test.graph.html_generator import HTMLGeneratorAgent
    html_gen = HTMLGeneratorAgent()
    
    col_map = html_gen._build_column_map(nodes_dicts, data.levels, kg_json)
    row_map = html_gen._build_row_map(nodes_dicts)
    interactive_html = html_gen._build_html(nodes_dicts, edges_dicts, kg_json, data.pipeline_docs, col_map, row_map)
    
    db_session.interactive_html = interactive_html
    db_session.updated_at = datetime.utcnow()
    db.commit()
    
    return {
        "status": "success",
        "message": "Session DFD data and HTML updated successfully",
        "session_id": data.session_id,
        "html_length": len(interactive_html)
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
                    "id": n.node_id,
                    "name": n.name,
                    "type": n.type,
                    "aliases": n.aliases or [],
                    "data_elements": n.data_elements or [],
                    "risks": n.risks or [],
                    "sources": n.sources or []
                } for n in kg_nodes
            ],
            "edges": [
                {
                    "source": e.source_node,
                    "target": e.target_node,
                    "data_elements": e.data_elements or [],
                    "flow_type": e.flow_type or "transfer",
                    "channel": e.channel or "",
                    "inferred": bool(e.inferred),
                    "sources": e.sources or []
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

# ── Dynamic HTML Generator API ────────────────────────────────

from fastapi.responses import HTMLResponse

@app.post("/api/dfd/preview")
def preview_html(data: HTMLPreviewRequest):
    """Generate HTML DFD view directly from JSON body payload."""
    from test.graph.html_generator import HTMLGeneratorAgent
    
    nodes_dicts = [n.model_dump() for n in data.nodes]
    edges_dicts = [e.model_dump() for e in data.edges]
    
    html_gen = HTMLGeneratorAgent()
    kg = {"nodes": nodes_dicts, "edges": edges_dicts}

    
    col_map = html_gen._build_column_map(nodes_dicts, data.levels, kg)
    row_map = html_gen._build_row_map(nodes_dicts)

    html = html_gen._build_html(nodes_dicts, edges_dicts, kg, data.pipeline_docs, col_map, row_map)
    
    return {"html": html}
