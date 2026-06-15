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
from api.models import DFDSession, DataMappingRow, KnowledgeGraphNode, KnowledgeGraphEdge, PipelineStageLog, MasterDFD
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

class StageDetail(BaseModel):
    stage: Optional[str] = None
    stage_order: Optional[int] = None
    output: Optional[dict] = None
    in_tokens: int = 0
    out_tokens: int = 0
    duration_ms: int = 0

class StatusResponse(BaseModel):
    session_id: str
    status: str
    current_stage: Optional[str] = None
    progress_percent: float = 0.0
    current_stage_detail: Optional[StageDetail] = None
    total_in_tokens: int = 0
    total_out_tokens: int = 0
    total_duration_ms: int = 0
    stages_completed: int = 0
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


def _combine_transcripts(local_files: List[str], include_file_headers: bool = True) -> str:
    """Read and combine all transcript files into a single string."""
    combined = ""
    for lf in local_files:
        if include_file_headers:
            combined += f"\n--- File: {os.path.basename(lf)} ---\n"
        ext = os.path.splitext(lf)[1].lower()
        if ext in (".txt", ".md", ".csv", ".log") or ext == "":
            with open(lf, 'r', encoding='utf-8') as f:
                combined += f.read() + "\n"
        elif ext == ".pdf":
            try:
                import pdfplumber
            except Exception as e:
                raise RuntimeError(
                    "PDF processing requires 'pdfplumber'. Install dependencies and redeploy."
                ) from e

            extracted_pages = []
            with pdfplumber.open(lf) as pdf:
                for i, page in enumerate(pdf.pages):
                    page_text = page.extract_text() or ""
                    page_text = page_text.strip()
                    if page_text:
                        extracted_pages.append(f"\n[Page {i + 1}]\n{page_text}\n")

            extracted_text = "\n".join(extracted_pages).strip()
            if not extracted_text:
                raise ValueError(
                    f"PDF '{os.path.basename(lf)}' contains no extractable text. "
                    "If it is a scanned PDF, OCR is required (not supported yet)."
                )
            combined += extracted_text + "\n"
        else:
            raise ValueError(
                f"Unsupported file type '{ext}' for '{os.path.basename(lf)}'. "
                "Upload .txt or .pdf."
            )
    return combined


# ── Unified Background Pipeline ─────────────────────

PIPELINE_STAGES = [
    "ingest_and_clean",
    "deterministic_extraction",
    "agentic_extraction",
    "entity_normalization",
    "flow_canonicalization",
    "verification",
    "schema_generation",
    "dfd_generation",
    "knowledge_graph",
    "html_generation",
    "saving_to_db",
]

def _stage_percent(stage_order: int) -> float:
    """Map stage order (1-based) to progress percentage."""
    return min(round(stage_order / len(PIPELINE_STAGES) * 100, 1), 100.0)


def process_aggressive_pipeline(session_id: str, department: str, files: List[str], ai_config: dict = None, notification_email: Optional[str] = None):
    from api.database import SessionLocal
    db = SessionLocal()

    # Hash the API key for logging (last 6 chars only)
    api_key_raw = (ai_config or {}).get("apiKey", "")
    api_key_hash = f"...{api_key_raw[-6:]}" if len(api_key_raw) > 6 else ""

    def _update_progress(stage_name: str, percent: float):
        """Update session progress in DB (non-blocking)."""
        try:
            sess = db.query(DFDSession).filter(DFDSession.session_id == session_id).first()
            if sess:
                sess.current_stage = stage_name
                sess.progress_percent = percent
                sess.updated_at = datetime.utcnow()
                db.commit()
        except Exception:
            db.rollback()

    def _log_stage(stage_name, stage_order, output_summary, in_tokens, out_tokens, duration_ms):
        """Stage callback: log to DB + update progress."""
        try:
            log = PipelineStageLog(
                id=str(uuid.uuid4()),
                session_id=session_id,
                stage=stage_name,
                stage_order=stage_order,
                output=output_summary,
                api_key_hash=api_key_hash,
                in_tokens=in_tokens,
                out_tokens=out_tokens,
                duration_ms=duration_ms,
            )
            db.add(log)
            db.commit()
        except Exception:
            db.rollback()
        _update_progress(stage_name, _stage_percent(stage_order))

    try:
        logger.info(f"[{session_id}] Aggressive Pipeline starting for department: {department}")
        _update_progress("starting", 0.0)

        from test.orchestrator.pipeline_runner import PipelineRunner
        from test.agents.knowledge_graph_agent import KnowledgeGraphAgent
        from test.graph.html_generator import HTMLGeneratorAgent

        ai_config = ai_config or {}

        with tempfile.TemporaryDirectory() as temp_dir:
            # 1. Download files (still needs temp dir for downloads)
            local_files = _download_files(files, temp_dir)
            # IMPORTANT: preserve transcript formatting for downstream doc-type detection
            combined_transcript = _combine_transcripts(local_files, include_file_headers=False)
            combined_path = os.path.join(temp_dir, "combined_source.txt")
            with open(combined_path, "w") as f:
                f.write(combined_transcript)

            # 2. Run Pipeline (Phases 1-9) — all in-memory with stage callbacks
            runner = PipelineRunner(ai_config=ai_config, stage_callback=_log_stage)
            result = runner.process_file(combined_path)

        # 3. Build Knowledge Graph — fully in-memory
        _update_progress("knowledge_graph", _stage_percent(9))
        kg_agent = KnowledgeGraphAgent(ai_config=ai_config)
        graph_output = kg_agent.build_graph_from_result(result)
        graph_data = graph_output["kg_dict"]
        render_plan_data = graph_output["render_plan_dict"]
        kg_result = graph_output["kg_result"]

        schema_one_json = result.get("compliance_schema")
        if (not graph_data.get("nodes") or not graph_data.get("edges")) and schema_one_json:
            logger.info(f"[{session_id}] Empty KG from pipeline result, falling back to Schema-1 based DFD regeneration")
            fallback_output = kg_agent.build_graph_from_schema_one(
                schema_one_json,
                metadata={"department": department, "session_id": session_id},
                dialogue_records=result.get("dialogue_records", []) or [],
            )
            graph_data = fallback_output["kg_dict"]
            render_plan_data = fallback_output["render_plan_dict"]
            kg_result = fallback_output["kg_result"]

        _log_stage("knowledge_graph", len(PIPELINE_STAGES) - 2, {
            "nodes": len(graph_data.get("nodes", [])),
            "edges": len(graph_data.get("edges", []))
        }, 0, 0, 0)

        # 4. Generate HTML DFD — fully in-memory (no file write)
        _update_progress("html_generation", _stage_percent(10))
        html_gen = HTMLGeneratorAgent()
        try:
            interactive_html = html_gen.generate_from_data(
                graph_data,
                render_plan_data,
                pipeline_docs={"metadata": {"department": department}},
            )
        except Exception as e:
            logger.error(f"[{session_id}] HTML generation failed: {e}", exc_info=True)
            raise

        if not interactive_html or len(interactive_html.strip()) < 200:
            raise ValueError(
                f"HTML generation returned empty output (nodes={len(graph_data.get('nodes', []))}, "
                f"edges={len(graph_data.get('edges', []))})."
            )

        _log_stage("html_generation", len(PIPELINE_STAGES) - 1, {
            "html_length": len(interactive_html)
        }, 0, 0, 0)

        # 5. Schema Generation (Schema-1 + Data Inventory)
        inventory_rows = result.get("data_inventory", [])

        if not schema_one_json:
            generator = SchemaGenerator(ai_config=ai_config)
            try:
                schema_one_json = generator.generate_schema_one(combined_transcript)
                logger.info(f"[{session_id}] Schema-1 generated")
            except Exception as e:
                logger.error(f"[{session_id}] Schema-1 generation failed: {e}", exc_info=True)

        if schema_one_json and not inventory_rows:
            try:
                generator = SchemaGenerator(ai_config=ai_config)
                inventory_rows = generator.generate_data_inventory(schema_one_json)
                logger.info(f"[{session_id}] Data inventory: {len(inventory_rows)} rows")
            except Exception as e:
                logger.error(f"[{session_id}] Data inventory generation failed: {e}", exc_info=True)

        # 6. Save everything to DB
        _update_progress("saving_to_db", _stage_percent(11))
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
            db_session.current_stage = "completed"
            db_session.progress_percent = 100.0
            db_session.updated_at = datetime.utcnow()

        # Save KG Nodes
        kg_nodes_list = graph_data.get("nodes", [])
        kg_edges_list = graph_data.get("edges", [])

        for n in kg_nodes_list:
            db.add(KnowledgeGraphNode(
                id=str(uuid.uuid4()),
                session_id=session_id,
                node_id=n.get("id", ""),
                name=n.get("name", ""),
                type=n.get("type", ""),
                aliases=n.get("aliases", []),
                data_elements=n.get("data_elements", []),
                risks=n.get("risks", []),
                sources=n.get("sources", [])
            ))

        for e in kg_edges_list:
            db.add(KnowledgeGraphEdge(
                id=str(uuid.uuid4()),
                session_id=session_id,
                source_node=e.get("source", ""),
                target_node=e.get("target", ""),
                data_elements=e.get("data_elements", []),
                flow_type=e.get("flow_type", ""),
                channel=e.get("channel", ""),
                inferred=1 if e.get("inferred") else 0,
                sources=e.get("sources", [])
            ))

        # Save data mapping rows
        if not inventory_rows:
            inventory_rows = result.get("data_inventory", [])
        s_no = 1
        for row in (inventory_rows or []):
            db.add(DataMappingRow(
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
            ))
            s_no += 1

        _log_stage("saving_to_db", len(PIPELINE_STAGES), {
            "kg_nodes": len(kg_nodes_list),
            "kg_edges": len(kg_edges_list),
            "mapping_rows": len(inventory_rows or [])
        }, 0, 0, 0)

        db.commit()
        logger.info(f"[{session_id}] Pipeline complete: {len(kg_nodes_list)} nodes, {len(kg_edges_list)} edges")

        # Send email notification if provided
        if notification_email:
            from utils.email_service import send_pipeline_completion_email
            send_pipeline_completion_email(notification_email, session_id, "completed")

    except Exception as e:
        logger.error(f"[{session_id}] Aggressive Pipeline failed: {str(e)}", exc_info=True)
        try:
            db.rollback()
            db_session = db.query(DFDSession).filter(DFDSession.session_id == session_id).first()
            if db_session:
                db_session.status = "failed"
                db_session.error_message = str(e)
                db_session.current_stage = "failed"
                db_session.progress_percent = 0.0
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
        notification_email = payload_data.get("email")
    except Exception as e:
        logger.error(f"JWT decode error: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid or missing token: {str(e)}")
        
    req_session_id = payload_data.get("session_id")
    req_department = payload_data.get("department")
    req_files = payload_data.get("files", [])
    use_rlm = payload_data.get("use_rlm", False)
    
    if not req_session_id or not req_department:
        raise HTTPException(status_code=400, detail="Missing required session_id or department in token data")

    processing_mode = "rlm" if use_rlm else "aggressive"
    logger.info(f"[{req_session_id}] Mode: {processing_mode} | Department: {req_department}")

    # Clean up existing session if re-running
    existing = db.query(DFDSession).filter(DFDSession.session_id == req_session_id).first()
    if existing:
        db.query(DataMappingRow).filter(DataMappingRow.session_id == req_session_id).delete()
        db.query(KnowledgeGraphNode).filter(KnowledgeGraphNode.session_id == req_session_id).delete()
        db.query(KnowledgeGraphEdge).filter(KnowledgeGraphEdge.session_id == req_session_id).delete()
        db.query(PipelineStageLog).filter(PipelineStageLog.session_id == req_session_id).delete()
        db.delete(existing)
        db.commit()
        logger.info(f"[{req_session_id}] Existing session deleted — restarting pipeline")

    new_session = DFDSession(
        session_id=req_session_id,
        department=req_department,
        status="processing",
        processing_mode=processing_mode
    )
    db.add(new_session)
    db.commit()

    background_tasks.add_task(
        process_aggressive_pipeline,
        req_session_id, req_department, req_files or [], ai_config, notification_email
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

    # Get all stage logs for totals
    all_stages = (
        db.query(PipelineStageLog)
        .filter(PipelineStageLog.session_id == session_id)
        .order_by(PipelineStageLog.stage_order)
        .all()
    )

    total_in = sum(st.in_tokens or 0 for st in all_stages)
    total_out = sum(st.out_tokens or 0 for st in all_stages)
    total_dur = sum(st.duration_ms or 0 for st in all_stages)

    # Latest stage detail
    current_detail = None
    if all_stages:
        latest = all_stages[-1]
        current_detail = StageDetail(
            stage=latest.stage,
            stage_order=latest.stage_order,
            output=latest.output,
            in_tokens=latest.in_tokens or 0,
            out_tokens=latest.out_tokens or 0,
            duration_ms=latest.duration_ms or 0
        )

    return StatusResponse(
        session_id=s.session_id,
        status=s.status,
        current_stage=s.current_stage,
        progress_percent=s.progress_percent or 0.0,
        current_stage_detail=current_detail,
        total_in_tokens=total_in,
        total_out_tokens=total_out,
        total_duration_ms=total_dur,
        stages_completed=len(all_stages),
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
    db.query(PipelineStageLog).filter(PipelineStageLog.session_id == session_id).delete()
    db.delete(s)
    db.commit()

    return {"message": f"Session {session_id} and all related records deleted."}


@app.get("/api/stages/{session_id}")
def get_pipeline_stages(session_id: str, db: Session = Depends(get_db)):
    """Return all pipeline stage logs for a session — used by frontend to show progress."""
    s = db.query(DFDSession).filter(DFDSession.session_id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    stages = (
        db.query(PipelineStageLog)
        .filter(PipelineStageLog.session_id == session_id)
        .order_by(PipelineStageLog.stage_order)
        .all()
    )

    return {
        "session_id": session_id,
        "status": s.status,
        "current_stage": s.current_stage,
        "progress_percent": s.progress_percent or 0.0,
        "stages": [
            {
                "stage": st.stage,
                "stage_order": st.stage_order,
                "output": st.output,
                "api_key_hash": st.api_key_hash,
                "in_tokens": st.in_tokens,
                "out_tokens": st.out_tokens,
                "duration_ms": st.duration_ms,
                "created_at": st.created_at.isoformat() if st.created_at else None
            }
            for st in stages
        ],
        "total_in_tokens": sum(st.in_tokens or 0 for st in stages),
        "total_out_tokens": sum(st.out_tokens or 0 for st in stages),
        "total_duration_ms": sum(st.duration_ms or 0 for st in stages)
    }

# ── Dynamic HTML Generator API ────────────────────────────────

from fastapi.responses import HTMLResponse
from fastapi.responses import Response

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


@app.get("/api/dfd/pdf/{session_id}")
async def download_dfd_pdf(session_id: str, db: Session = Depends(get_db)):
    """Download a DFD as a PDF for an existing session.

    Uses Playwright to render the stored interactive HTML and export to PDF.
    """
    s = db.query(DFDSession).filter(DFDSession.session_id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    html = (s.interactive_html or "").strip()
    if not html:
        raise HTTPException(status_code=400, detail="No interactive_html found for this session")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": 1600, "height": 900})
            await page.set_content(html, wait_until="load")
            await page.wait_for_timeout(1200)
            pdf_bytes = await page.pdf(
                format="A3",
                landscape=True,
                print_background=True,
                margin={"top": "10mm", "bottom": "10mm", "left": "10mm", "right": "10mm"},
            )
        finally:
            await browser.close()

    filename = f"DFD_{session_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
    )


@app.post("/api/dfd/regenerate/{session_id}")
@app.get("/api/dfd/regenerate/{session_id}")
def regenerate_dfd_from_schema(session_id: str, db: Session = Depends(get_db)):
    """Regenerate the DFD (KG + render plan + HTML) from stored Schema-1 JSON.

    This avoids rerunning the expensive ingestion/extraction pipeline when Schema-1 / Data Matrix
    already exists but the DFD is missing or empty.
    """
    s = db.query(DFDSession).filter(DFDSession.session_id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    schema_one_json = s.schema_one_json or s.compliance_schema_json
    if not schema_one_json:
        raise HTTPException(status_code=400, detail="No Schema-1 JSON found on this session")

    from test.agents.knowledge_graph_agent import KnowledgeGraphAgent
    from test.graph.html_generator import HTMLGeneratorAgent

    kg_agent = KnowledgeGraphAgent(ai_config={})
    graph_output = kg_agent.build_graph_from_schema_one(
        schema_one_json,
        metadata={"department": s.department, "session_id": session_id},
        dialogue_records=[],
    )

    graph_data = graph_output["kg_dict"]
    render_plan_data = graph_output["render_plan_dict"]
    kg_result = graph_output["kg_result"]

    html_gen = HTMLGeneratorAgent()
    interactive_html = html_gen.generate_from_data(
        graph_data,
        render_plan_data,
        pipeline_docs={"metadata": {"department": s.department}},
    )

    if not interactive_html or len(interactive_html.strip()) < 200:
        raise HTTPException(
            status_code=500,
            detail=(
                f"HTML generation returned empty output (nodes={len(graph_data.get('nodes', []))}, "
                f"edges={len(graph_data.get('edges', []))})."
            ),
        )

    # Persist to session
    s.dfd_json = kg_result
    s.dfd_render_plan_json = render_plan_data
    s.interactive_html = interactive_html
    s.updated_at = datetime.utcnow()

    # Replace KG nodes/edges rows for this session
    db.query(KnowledgeGraphNode).filter(KnowledgeGraphNode.session_id == session_id).delete()
    db.query(KnowledgeGraphEdge).filter(KnowledgeGraphEdge.session_id == session_id).delete()

    for n in graph_data.get("nodes", []):
        db.add(KnowledgeGraphNode(
            id=str(uuid.uuid4()),
            session_id=session_id,
            node_id=n.get("id", ""),
            name=n.get("name", ""),
            type=n.get("type", ""),
            aliases=n.get("aliases", []),
            data_elements=n.get("data_elements", []),
            risks=n.get("risks", []),
            sources=n.get("sources", []),
        ))

    for e in graph_data.get("edges", []):
        db.add(KnowledgeGraphEdge(
            id=str(uuid.uuid4()),
            session_id=session_id,
            source_node=e.get("source", ""),
            target_node=e.get("target", ""),
            data_elements=e.get("data_elements", []),
            flow_type=e.get("flow_type", ""),
            channel=e.get("channel", ""),
            inferred=1 if e.get("inferred") else 0,
            sources=e.get("sources", []),
        ))

    db.commit()

    return {
        "session_id": session_id,
        "status": "ok",
        "nodes": len(graph_data.get("nodes", [])),
        "edges": len(graph_data.get("edges", [])),
        "html_length": len(interactive_html),
    }


# ── Master DFD API ────────────────────────────────────

class MasterDFDRequest(BaseModel):
    token: str  # JWT token containing session IDs, project info, and email

class MasterDFDResponse(BaseModel):
    project_id: str
    status: str
    message: str


def process_master_dfd(project_id: str, session_ids: List[str], project_name: Optional[str], notification_email: Optional[str], ai_config: dict, db_session: Session):
    """
    Background task to aggregate multiple session DFDs into a master DFD.
    """
    logger.info(f"[{project_id}] Starting master DFD generation for {len(session_ids)} sessions")
    
    def update_stage(stage: str, progress: float):
        """Helper to update current stage and progress."""
        master = db_session.query(MasterDFD).filter(MasterDFD.project_id == project_id).first()
        if master:
            master.current_stage = stage
            master.progress_percent = progress
            master.updated_at = datetime.utcnow()
            db_session.commit()
            logger.info(f"[{project_id}] Stage: {stage} ({progress}%)")
    
    try:
        # Update status to processing
        master = db_session.query(MasterDFD).filter(MasterDFD.project_id == project_id).first()
        if not master:
            logger.error(f"[{project_id}] Master DFD record not found")
            return
        
        master.status = "processing"
        master.current_stage = "initializing"
        master.progress_percent = 0.0
        db_session.commit()
        
        # Fetch session data
        update_stage("fetching_sessions", 10.0)
        
        # Debug: Show all available sessions
        all_sessions = db_session.query(DFDSession.session_id, DFDSession.status).all()
        logger.info(f"[{project_id}] Available sessions in DB: {[(s.session_id, s.status) for s in all_sessions]}")
        logger.info(f"[{project_id}] Requested session IDs: {session_ids}")
        
        sessions_data = []
        for idx, session_id in enumerate(session_ids):
            session = db_session.query(DFDSession).filter(DFDSession.session_id == session_id).first()
            if not session:
                logger.warning(f"[{project_id}] Session {session_id} not found in database, skipping")
                continue
            
            # Fetch KG nodes and edges
            kg_nodes_raw = db_session.query(KnowledgeGraphNode).filter(
                KnowledgeGraphNode.session_id == session_id
            ).all()
            
            kg_edges_raw = db_session.query(KnowledgeGraphEdge).filter(
                KnowledgeGraphEdge.session_id == session_id
            ).all()
            
            # Convert to dicts
            kg_nodes = [
                {
                    "id": n.node_id,
                    "name": n.name,
                    "type": n.type,
                    "aliases": n.aliases or [],
                    "data_elements": n.data_elements or [],
                    "risks": n.risks or [],
                    "sources": n.sources or []
                }
                for n in kg_nodes_raw
            ]
            
            kg_edges = [
                {
                    "source": e.source_node,
                    "target": e.target_node,
                    "data_elements": e.data_elements or [],
                    "flow_type": e.flow_type or "data_flow",
                    "channel": e.channel or "",
                    "evidence": [],
                    "evidence_trail": []
                }
                for e in kg_edges_raw
            ]
            
            # Fetch ALL session data
            sessions_data.append({
                "session_id": session_id,
                "kg_nodes": kg_nodes,
                "kg_edges": kg_edges,
                "dfd_render_plan": session.dfd_render_plan_json or {},
                "actors_json": session.actors_json or [],
                "systems_json": session.systems_json or [],
                "flows_json": session.flows_json or [],
                "risks_json": session.risks_json or [],
                "data_elements_json": session.data_elements_json or [],
                "compliance_schema_json": session.compliance_schema_json,
                "verification_report_json": session.verification_report_json,
                "metadata": {
                    "project_name": project_name or "Master Project",
                    "department": session.department
                }
            })
            
            # Update progress for fetching
            progress = 10.0 + (idx + 1) / len(session_ids) * 20.0
            update_stage(f"fetching_sessions ({idx + 1}/{len(session_ids)})", progress)
        
        if not sessions_data:
            error_msg = f"No valid sessions found to aggregate. Requested: {session_ids}, Found in DB: {[s.session_id for s in all_sessions]}"
            logger.error(f"[{project_id}] {error_msg}")
            raise ValueError(error_msg)
        
        # Aggregate using MasterDFDAgent with AI validation
        update_stage("aggregating_data", 35.0)
        from test.agents.master_dfd_agent import MasterDFDAgent
        agent = MasterDFDAgent(ai_config=ai_config)
        result = agent.aggregate_sessions(sessions_data, use_ai_validation=True)
        
        update_stage("merging_complete", 60.0)
        
        master_kg = result["master_kg"]
        master_render_plan = result["master_render_plan"]
        overview_summary = result["overview_summary"]
        
        # Generate HTML using HTMLGeneratorAgent
        update_stage("generating_html", 75.0)
        from test.graph.html_generator import HTMLGeneratorAgent
        html_gen = HTMLGeneratorAgent()
        
        # Create pipeline_docs with metadata for proper department/project name display
        pipeline_docs = {
            "master_metadata": {
                "metadata": {
                    "department": overview_summary.get("project_name", project_name),
                    "project_name": overview_summary.get("project_name", project_name),
                    "total_sessions": overview_summary.get("total_sessions", len(session_ids)),
                    "departments": overview_summary.get("departments", [])
                }
            }
        }
        
        master_html = html_gen.generate_from_data(
            kg=master_kg,
            render_plan=master_render_plan,
            pipeline_docs=pipeline_docs
        )
        
        update_stage("finalizing", 90.0)
        
        # Update master DFD record
        master.master_kg_json = master_kg
        master.master_render_plan_json = master_render_plan
        master.master_html = master_html
        master.overview_summary = overview_summary
        master.project_name = overview_summary.get("project_name", project_name)
        master.total_sessions = overview_summary.get("total_sessions", len(session_ids))
        master.total_nodes = overview_summary.get("total_nodes", 0)
        master.total_edges = overview_summary.get("total_edges", 0)
        master.total_risks = overview_summary.get("total_risks", 0)
        master.status = "completed"
        master.current_stage = "completed"
        master.progress_percent = 100.0
        master.updated_at = datetime.utcnow()
        
        db_session.commit()
        logger.info(f"[{project_id}] Master DFD generation completed successfully")
        
        # Send email notification if provided
        if notification_email:
            from utils.email_service import send_master_dfd_completion_email
            send_master_dfd_completion_email(
                notification_email, project_id, "completed", 
                total_sessions=overview_summary.get("total_sessions", len(session_ids))
            )
        
    except Exception as e:
        logger.error(f"[{project_id}] Master DFD generation failed: {e}", exc_info=True)
        master = db_session.query(MasterDFD).filter(MasterDFD.project_id == project_id).first()
        if master:
            master.status = "failed"
            master.current_stage = "failed"
            master.error_message = str(e)
            db_session.commit()
            
            # Send failure email notification if provided
            if notification_email:
                from utils.email_service import send_master_dfd_completion_email
                send_master_dfd_completion_email(notification_email, project_id, "failed", error_message=str(e))


@app.post("/api/master-dfd/generate", response_model=MasterDFDResponse)
def generate_master_dfd(
    request: MasterDFDRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Generate a master DFD by aggregating multiple session DFDs.
    
    Request body:
    {
        "token": "jwt_token_here",
        "email": "user@example.com" (optional)
    }
    
    Token payload should contain:
    {
        "data": {
            "session_ids": ["session_id_1", "session_id_2", ...],
            "project_id": "project_123",
            "project_name": "DPDPA Compliance Project" (optional),
            "email": "user@example.com" (optional)
        },
        "ai_config": {
            "apiKey": "your-api-key",
            "model": "gpt-4" (optional)
        }
    }
    """
    # Decode JWT token
    import jwt
    from config import Config
    
    try:
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
        logger.error(f"JWT decode error in master DFD: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid or missing token: {str(e)}")
    
    # Extract data from token
    session_ids = payload_data.get("session_ids", [])
    project_id = payload_data.get("project_id")
    project_name = payload_data.get("project_name")
    notification_email = payload_data.get("email")
    
    if not session_ids:
        raise HTTPException(status_code=400, detail="Session IDs list cannot be empty in token data")
    
    if not project_id:
        raise HTTPException(status_code=400, detail="Project ID is required in token data")
    
    logger.info(f"Received master DFD request for project {project_id} with {len(session_ids)} sessions")
    
    # Check if master DFD already exists
    existing = db.query(MasterDFD).filter(MasterDFD.project_id == project_id).first()
    if existing:
        # Re-generate: reset status and clear old data
        logger.info(f"Re-generating master DFD for project {project_id}")
        existing.session_ids = session_ids
        existing.status = "pending"
        existing.error_message = None
        existing.master_kg_json = None
        existing.master_render_plan_json = None
        existing.master_html = None
        existing.overview_summary = None
        existing.project_name = project_name
        existing.notification_email = notification_email
        existing.updated_at = datetime.utcnow()
        db.commit()
    else:
        # Create new master DFD record
        master = MasterDFD(
            project_id=project_id,
            session_ids=session_ids,
            status="pending",
            project_name=project_name,
            notification_email=notification_email
        )
        db.add(master)
        db.commit()
    
    # Start background processing
    background_tasks.add_task(process_master_dfd, project_id, session_ids, project_name, notification_email, ai_config, SessionLocal())
    
    return MasterDFDResponse(
        project_id=project_id,
        status="pending",
        message=f"Master DFD generation started for {len(session_ids)} sessions"
    )


@app.get("/api/master-dfd/{project_id}")
def get_master_dfd(project_id: str, db: Session = Depends(get_db)):
    """
    Fetch master DFD results for a project.
    
    Returns:
    {
        "project_id": "project_123",
        "status": "completed",
        "project_name": "DPDPA Compliance Project",
        "session_ids": ["session_1", "session_2"],
        "overview_summary": {...},
        "master_html": "<html>...",
        "master_kg": {...},
        "master_render_plan": {...},
        "total_sessions": 5,
        "total_nodes": 42,
        "total_edges": 38,
        "total_risks": 12,
        "error_message": null,
        "created_at": "2026-03-23T14:30:00",
        "updated_at": "2026-03-23T14:35:00"
    }
    """
    master = db.query(MasterDFD).filter(MasterDFD.project_id == project_id).first()
    if not master:
        raise HTTPException(status_code=404, detail="Master DFD not found")
    
    return {
        "project_id": master.project_id,
        "status": master.status,
        "project_name": master.project_name,
        "session_ids": master.session_ids,
        "overview_summary": master.overview_summary,
        "master_html": master.master_html,
        "master_kg": master.master_kg_json,
        "master_render_plan": master.master_render_plan_json,
        "total_sessions": master.total_sessions,
        "total_nodes": master.total_nodes,
        "total_edges": master.total_edges,
        "total_risks": master.total_risks,
        "error_message": master.error_message,
        "created_at": master.created_at.isoformat() if master.created_at else None,
        "updated_at": master.updated_at.isoformat() if master.updated_at else None
    }


@app.get("/api/master-dfd/status/{project_id}")
def get_master_dfd_status(project_id: str, db: Session = Depends(get_db)):
    """
    Get real-time status of master DFD generation with stage details.
    
    Returns:
    {
        "project_id": "project_123",
        "status": "processing",
        "current_stage": "aggregating_data",
        "progress_percent": 45.0,
        "project_name": "DPDPA Project",
        "total_sessions": 5,
        "error_message": null,
        "created_at": "2026-03-23T14:30:00",
        "updated_at": "2026-03-23T14:32:15"
    }
    """
    master = db.query(MasterDFD).filter(MasterDFD.project_id == project_id).first()
    if not master:
        raise HTTPException(status_code=404, detail="Master DFD not found")
    
    return {
        "project_id": master.project_id,
        "status": master.status,
        "current_stage": master.current_stage,
        "progress_percent": master.progress_percent or 0.0,
        "project_name": master.project_name,
        "total_sessions": len(master.session_ids) if master.session_ids else 0,
        "error_message": master.error_message,
        "created_at": master.created_at.isoformat() if master.created_at else None,
        "updated_at": master.updated_at.isoformat() if master.updated_at else None
    }
