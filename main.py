import os
import argparse
import json
import re
from config import Config
from utils.logger import setup_logger
from agent.ingestion import IngestionAgent
from agent.kb_builder import KBBuilder
from agent.retrieval import RetrievalAgent
from agent.report_gen import ReportGenerationAgent
from agent.privacy_dfd import PrivacyDFDAgent
from agent.dfd_extractor import DFDExtractor
from agent.dfd_html_renderer import DFDHTMLRenderer
from agent.dfd_validator import validate_dfd, format_validation_report
from agent.learning import LearningLoop
from datetime import datetime

logger = setup_logger("Main")

REFERENCE_DFD_DIR = os.path.join(os.path.dirname(__file__), "data", "reference_dfds")

def _slugify(name: str) -> str:
    """Match the slug logic used in reverse_engineer_dfds.py."""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _load_reference_dfd(department: str):
    """
    Look up a pre-generated reference DFD JSON for the given department.
    Returns the parsed JSON dict, or None if not found.
    """
    if not os.path.isdir(REFERENCE_DFD_DIR):
        return None

    slug = _slugify(department)

    # 1. Exact match
    exact_path = os.path.join(REFERENCE_DFD_DIR, f"{slug}.json")
    if os.path.exists(exact_path):
        with open(exact_path, "r") as f:
            logger.info(f"Reference DFD loaded (exact): {exact_path}")
            return json.load(f)

    # 2. Substring match — e.g. "Customer Care" matches "customer_care_department.json"
    for fname in os.listdir(REFERENCE_DFD_DIR):
        if fname.endswith(".json") and slug in fname:
            fpath = os.path.join(REFERENCE_DFD_DIR, fname)
            with open(fpath, "r") as f:
                logger.info(f"Reference DFD loaded (fuzzy): {fpath}")
                return json.load(f)

    return None


def run_department_assessment(input_files: list, department: str, use_reference: bool = False) -> dict:
    """
    Run full assessment for a single department.
    Produces:
      1. {dept}_Privacy_DFD_{ts}.md        — Mermaid-based Privacy DFD (existing)
      2. {dept}_Assessment_Report_{ts}.md  — Full compliance report
      3. {dept}_DFD_{ts}.html             — Interactive swimlane HTML DFD
    If use_reference=True and a reference JSON exists, uses it for zero-variance.
    Returns a dict with all paths and extracted JSON.
    """
    logger.info(f"Starting compliance assessment for: {department}")
    Config.validate()

    # Init agents
    ingestion_agent   = IngestionAgent()
    kb_builder        = KBBuilder()
    retrieval_agent   = RetrievalAgent()
    report_gen_agent  = ReportGenerationAgent()
    privacy_dfd_agent = PrivacyDFDAgent()
    dfd_extractor     = DFDExtractor()
    dfd_renderer      = DFDHTMLRenderer()
    learning_loop     = LearningLoop(kb_builder)

    extracted_data_list = []

    # ── 1. Ingest transcripts ─────────────────────────
    for idx, file_path in enumerate(input_files):
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            continue

        logger.info(f"[{department}] Processing session {idx+1}: {file_path}")
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

    # ── 2. Context retrieval ──────────────────────────
    query = (
        f"Privacy compliance assessment for {department} department. "
        f"Personal data types, legal basis, consent management, data sharing."
    )
    context = retrieval_agent.retrieve_context(query)

    # ── 3. Generate Mermaid Privacy DFD (MD) ─────────
    logger.info(f"[{department}] Generating Mermaid Privacy DFD (MD)...")
    privacy_dfd_content = privacy_dfd_agent.generate_department_dfd(
        department, extracted_data_list, context
    )

    # ── 4. Generate HTML DFD (with validation loop) ──
    # Try reference DFD first (for zero-variance demo re-runs)
    dfd_json = None
    if use_reference:
        dfd_json = _load_reference_dfd(department)
        if dfd_json:
            logger.info(f"[{department}] Using REFERENCE DFD (zero-variance mode)")
        else:
            logger.warning(f"[{department}] No reference DFD found, falling back to LLM extraction")

    if dfd_json is None:
        logger.info(f"[{department}] Extracting structured DFD JSON (with validation loop)...")
        dfd_json = dfd_extractor.extract(department, extracted_data_list, context)

    # Log final validation score
    final_validation = validate_dfd(dfd_json)
    logger.info(f"[{department}] Final DFD validation:\n{format_validation_report(final_validation)}")

    # Render HTML
    html_content = dfd_renderer.render(dfd_json)

    # ── 5. Generate full compliance report (MD) ───────
    report_metadata = {
        "department": department,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "sessions_covered": len(input_files),
    }
    logger.info(f"[{department}] Generating Assessment Report...")
    report = report_gen_agent.generate_report(
        extracted_data_list, context, report_metadata, privacy_dfd_content
    )

    # ── 6. Save all outputs ───────────────────────────
    safe_dept = department.replace(" ", "_")
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(Config.REPORTS_DIR, exist_ok=True)

    # Full assessment report MD
    report_filename = f"{safe_dept}_Assessment_Report_{timestamp}.md"
    report_path = os.path.join(Config.REPORTS_DIR, report_filename)
    with open(report_path, "w") as f:
        f.write(report)
    logger.info(f"[{department}] Report saved: {report_path}")

    # Standalone Privacy DFD MD
    dfd_md_filename = f"{safe_dept}_Privacy_DFD_{timestamp}.md"
    dfd_md_path = os.path.join(Config.REPORTS_DIR, dfd_md_filename)
    with open(dfd_md_path, "w") as f:
        f.write(f"# Privacy Data Flow Diagram\n## {department} Department\n\n")
        f.write(privacy_dfd_content)
    logger.info(f"[{department}] Privacy DFD (MD) saved: {dfd_md_path}")

    # Interactive HTML DFD
    html_filename = f"{safe_dept}_DFD_{timestamp}.html"
    html_path = os.path.join(Config.REPORTS_DIR, html_filename)
    with open(html_path, "w") as f:
        f.write(html_content)
    logger.info(f"[{department}] HTML DFD saved: {html_path}")

    # Save DFD JSON (for reference / master aggregation)
    json_filename = f"{safe_dept}_DFD_{timestamp}.json"
    json_path = os.path.join(Config.REPORTS_DIR, json_filename)
    with open(json_path, "w") as f:
        json.dump(dfd_json, f, indent=2)
    logger.info(f"[{department}] DFD JSON saved: {json_path}")

    # ── 7. Learning loop ──────────────────────────────
    learning_loop.process_feedback(f"report_{department}", report, report_metadata)

    print(f"\n[{department}] ✅ Assessment Complete")
    print(f"  → Assessment Report (MD):  {report_path}")
    print(f"  → Privacy DFD (MD):        {dfd_md_path}")
    print(f"  → Interactive HTML DFD:    {html_path}")
    print(f"  → DFD JSON:                {json_path}")
    print(f"  → Validation score:        {final_validation['score']}/100 "
          f"({'PASS' if final_validation['passed'] else 'PARTIAL'})")

    return {
        "department": department,
        "report_path": report_path,
        "dfd_md_path": dfd_md_path,
        "html_path": html_path,
        "json_path": json_path,
        "dfd_json": dfd_json,
        "privacy_dfd_content": privacy_dfd_content,
        "validation_score": final_validation["score"],
    }


def run_master_dfd(dept_results: list):
    """
    Generate a Master Privacy DFD (MD) and a Master HTML DFD across all departments.
    """
    logger.info("Generating Master Organization-Level Privacy DFD...")

    # ── Mermaid master DFD (existing) ────────────────
    privacy_dfd_agent = PrivacyDFDAgent()
    all_dept_data = {
        r["department"]: r["privacy_dfd_content"] for r in dept_results
    }
    master_dfd_md = privacy_dfd_agent.generate_master_dfd(all_dept_data)

    # ── HTML master DFD: merge all department JSONs ───
    dfd_renderer = DFDHTMLRenderer()
    all_dept_jsons = [r["dfd_json"] for r in dept_results if r.get("dfd_json")]

    if all_dept_jsons:
        master_json = _merge_dept_jsons(dept_results)
        master_html = dfd_renderer.render(master_json)
    else:
        master_html = "<html><body><h1>No DFD data available</h1></body></html>"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(Config.REPORTS_DIR, exist_ok=True)

    # Save master MD
    master_md_path = os.path.join(Config.REPORTS_DIR, f"MASTER_Privacy_DFD_{timestamp}.md")
    with open(master_md_path, "w") as f:
        f.write("# Master Privacy Data Flow Diagram\n## Organization-Wide View\n\n")
        f.write(master_dfd_md)
    logger.info(f"Master Privacy DFD (MD) saved: {master_md_path}")

    # Save master HTML
    master_html_path = os.path.join(Config.REPORTS_DIR, f"MASTER_DFD_{timestamp}.html")
    with open(master_html_path, "w") as f:
        f.write(master_html)
    logger.info(f"Master HTML DFD saved: {master_html_path}")

    print(f"\n🗺️  Master DFD (MD):   {master_md_path}")
    print(f"🌐  Master DFD (HTML): {master_html_path}")

    return {"master_md_path": master_md_path, "master_html_path": master_html_path}


def _merge_dept_jsons(dept_results: list) -> dict:
    """Merge multiple department DFD JSONs into a master organization-level DFD."""
    actor_map = {
        "customers":  {"id": "customers", "name": "Customers", "type": "external", "color": "#fffde7", "business_processes": []},
        "internal":   {"id": "internal",  "name": "Internal Departments", "type": "internal", "color": "#fce4ec", "business_processes": []},
        "vendors":    {"id": "vendors",   "name": "Vendors/Partners", "type": "vendor", "color": "#f1f8e9", "business_processes": []},
    }
    all_sinks = []
    all_storage = []
    all_flows = []
    dept_names = []

    for r in dept_results:
        dj = r.get("dfd_json", {})
        dept = r["department"]
        dept_names.append(dept)

        for actor in dj.get("actors", []):
            aid = actor.get("id")
            if aid in actor_map:
                for bp in actor.get("business_processes", []):
                    # Prefix bp names with department
                    bp_copy = dict(bp)
                    bp_copy["name"] = f"{dept} - {bp['name']}"
                    bp_copy["id"] = f"{dept.replace(' ','_')}_{bp['id']}"
                    actor_map[aid]["business_processes"].append(bp_copy)

        for sink in dj.get("dispersal_sinks", []):
            sink_copy = dict(sink)
            sink_copy["name"] = f"{dept} - {sink['name']}"
            sink_copy["id"] = f"{dept.replace(' ','_')}_{sink['id']}"
            all_sinks.append(sink_copy)

        for sys in dj.get("storage_systems", []):
            if not any(s["name"] == sys["name"] for s in all_storage):
                all_storage.append(sys)

        for flow in dj.get("data_flows", []):
            flow_copy = dict(flow)
            if flow_copy.get("from_id") != "central_process":
                flow_copy["from_id"] = f"{dept.replace(' ','_')}_{flow_copy['from_id']}"
            if flow_copy.get("to_id") != "central_process":
                flow_copy["to_id"] = f"{dept.replace(' ','_')}_{flow_copy['to_id']}"
            all_flows.append(flow_copy)

    return {
        "department": "Organization - Master View",
        "version": "1.0",
        "central_process": "Organization Data Processing Hub",
        "actors": list(actor_map.values()),
        "dispersal_sinks": all_sinks,
        "storage_systems": all_storage,
        "data_flows": all_flows,
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "pipeline":
        # ── Document Intelligence Pipeline ────────────
        from test.orchestrator.pipeline_runner import PipelineRunner
        import glob

        runner = PipelineRunner()
        input_dir = os.path.join(os.path.dirname(__file__), "example_input")
        output_dir = os.path.join(os.path.dirname(__file__), "test", "pipeline_output")

        # Accept --files flag, or default to example_input/*.txt
        if "--files" in sys.argv:
            idx = sys.argv.index("--files")
            files = sys.argv[idx + 1:]
        else:
            files = sorted(glob.glob(os.path.join(input_dir, "*.txt")))

        if not files:
            print("No input files found. Use: python main.py pipeline --files <file1> <file2> ...")
            sys.exit(1)

        print(f"\n🔬 Document Intelligence Pipeline")
        print(f"   Processing {len(files)} file(s)...\n")

        results = runner.process_files(files, output_dir=output_dir)

        print(f"\n✅ Pipeline complete. {len(results)} file(s) processed.")
        print(f"   Output saved to: {output_dir}/")

    elif len(sys.argv) > 1 and sys.argv[1] == "graph":
        # ── Knowledge Graph Builder ───────────────────
        from test.agents.knowledge_graph_agent import KnowledgeGraphAgent

        pipeline_output_dir = os.path.join(os.path.dirname(__file__), "test", "pipeline_output")
        graph_output_dir = os.path.join(os.path.dirname(__file__), "test", "graph_output")

        print(f"\n🕸️  Knowledge Graph Builder")
        print(f"   Loading documents from: {pipeline_output_dir}\n")

        agent = KnowledgeGraphAgent()
        result = agent.build_graph(pipeline_output_dir, graph_output_dir)

        if "error" not in result:
            stats = result["graph_stats"]
            print(f"\n✅ Knowledge Graph built:")
            print(f"   Nodes: {stats['total_nodes']} ({stats.get('inferred_edges', 0)} inferred edges)")
            print(f"   Edges: {stats['total_edges']}")
            print(f"   Entities merged: {result['entities_merged']}")
            print(f"   Flows merged: {result['flows_merged']}")
            print(f"   Inferred flows: {result['inferred_flows']}")
            print(f"   Validation: {'PASS ✅' if result['validation']['valid'] else 'FAIL ❌'}")
            print(f"\n   Output: {graph_output_dir}/")

    elif len(sys.argv) > 1 and sys.argv[1] == "visualize":
        # ── Deterministic HTML Visualization ──────────
        from test.graph.html_generator import HTMLGeneratorAgent

        graph_dir = os.path.join(os.path.dirname(__file__), "test", "graph_output")
        pipeline_dir = os.path.join(os.path.dirname(__file__), "test", "pipeline_output")
        output_html = os.path.join(os.path.dirname(__file__), "test", "graph_output", "privacy_dfd.html")

        print(f"\n🎨 Building Privacy DFD Dashboard (Deterministic)")
        print(f"   No LLM needed — generating directly from knowledge graph JSON...\n")

        generator = HTMLGeneratorAgent()
        result = generator.generate(graph_dir, pipeline_dir, output_html)

        if result:
            print(f"\n✅ DFD Dashboard generated!")
            print(f"   Open: file://{os.path.abspath(result)}")
        else:
            print(f"\n❌ Failed to generate HTML.")

    else:
        # ── Default: Clean transcripts ────────────────
        from test.clean_transcripts import CleanTranscripts
        clean_transcripts = CleanTranscripts()
        clean_transcripts.clean_transcripts()

    # parser = argparse.ArgumentParser(description="AI Compliance Documentation Agent")
    # subparsers = parser.add_subparsers(dest="command")

    # # ── Single department assessment ──────────────────
    # dept_parser = subparsers.add_parser(
    #     "assess", help="Assess a single department — report + Privacy DFD (MD) + HTML DFD"
    # )
    # dept_parser.add_argument("--files", nargs="+", required=True, help="Transcript file paths")
    # dept_parser.add_argument("--dept", required=True, help="Department name")
    # dept_parser.add_argument(
    #     "--use-reference", action="store_true", default=False,
    #     help="Use pre-generated reference DFD JSON (zero variance for demo re-runs)"
    # )

    # # ── Multi-department + Master DFD ─────────────────
    # master_parser = subparsers.add_parser(
    #     "master", help="Assess multiple departments and generate a Master DFD"
    # )
    # master_parser.add_argument("--depts", nargs="+", required=True)
    # master_parser.add_argument(
    #     "--file-groups", nargs="+", required=True,
    #     help="Transcript files per department separated by commas"
    # )

    # args = parser.parse_args()

    # if args.command == "assess":
    #     run_department_assessment(args.files, args.dept, use_reference=args.use_reference)

    # elif args.command == "master":
    #     if len(args.depts) != len(args.file_groups):
    #         print("ERROR: Number of --depts must match --file-groups")
    #         exit(1)
    #     dept_results = []
    #     for dept, file_group in zip(args.depts, args.file_groups):
    #         files = [f.strip() for f in file_group.split(",")]
    #         result = run_department_assessment(files, dept)
    #         dept_results.append(result)
    #     run_master_dfd(dept_results)

    # else:
    #     parser.print_help()
