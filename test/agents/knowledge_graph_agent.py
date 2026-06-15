"""
Knowledge Graph Agent — Orchestrates the full graph construction pipeline.

Steps:
  1. Load all document intelligence JSON outputs
  2. Merge entities across documents (EntityMerger)
  3. Merge flows across documents (FlowMerger)
  4. Build NetworkX DiGraph (GraphBuilder)
  5. Attach risks and data elements
  6. Apply graph reasoning (GraphReasoningAgent)
  7. Validate graph integrity (GraphValidator)
  8. Export to JSON, DFD, render plan (GraphExporter)
"""
import json
from pathlib import Path
from utils.logger import setup_logger

from test.agents.entity_merger import EntityMerger
from test.agents.flow_merger import FlowMerger
from test.agents.graph_reasoning_agent import GraphReasoningAgent
from test.agents.graph_validator import GraphValidator
from test.graph.graph_builder import GraphBuilder
from test.graph.graph_exporter import GraphExporter

logger = setup_logger("KnowledgeGraphAgent")


class KnowledgeGraphAgent:

    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}
        self.entity_merger = EntityMerger()
        self.flow_merger = None  # Initialized after entity merge
        self.reasoning_agent = GraphReasoningAgent()
        self.validator = GraphValidator()
        self.builder = GraphBuilder()
        self.exporter = GraphExporter()

    def build_graph(self, input_dir, output_dir):
        """
        Build the unified Knowledge Graph from all document outputs.

        Args:
            input_dir: directory containing *_intelligence.json files
            output_dir: directory for graph/dfd output files

        Returns:
            dict with graph stats, validation report, and export paths
        """
        input_dir = Path(input_dir)
        output_dir = Path(output_dir)

        # ── Step 1: Load all document outputs ─────────
        doc_outputs = self._load_documents(input_dir)
        if not doc_outputs:
            logger.error("No intelligence documents found!")
            return {"error": "No documents found"}

        logger.info(f"[1] Loaded {len(doc_outputs)} document(s)")

        # ── Step 2: Merge entities ────────────────────
        logger.info("[2] Merging entities across documents...")
        entity_result = self.entity_merger.merge(doc_outputs)
        entities = entity_result["entities"]
        name_map = entity_result["name_map"]

        # ── Step 3: Merge flows ───────────────────────
        logger.info("[3] Merging flows across documents...")
        self.flow_merger = FlowMerger(name_map=name_map)
        merged_flows = self.flow_merger.merge(doc_outputs)

        # ── Step 4: Build graph ───────────────────────
        logger.info("[4] Building NetworkX DiGraph...")
        self.builder = GraphBuilder()
        self.builder.add_nodes(entities)
        self.builder.add_edges(merged_flows, name_map)

        # ── Step 5: Attach risks + data elements ─────
        logger.info("[5] Attaching risks and data elements...")
        self.builder.attach_risks(doc_outputs, name_map)
        self.builder.attach_data_elements(name_map)

        G = self.builder.get_graph()

        # ── Step 6: Graph reasoning ───────────────────
        logger.info("[6] Running graph reasoning...")
        inferred = self.reasoning_agent.reason(G)

        # ── Step 7: Validate ──────────────────────────
        logger.info("[7] Validating graph integrity...")
        validation = self.validator.validate(G)

        # ── Step 8: Collect dialogue records for evidence ─
        all_dialogue_records = []
        for doc in doc_outputs:
            all_dialogue_records.extend(doc.get("dialogue_records", []))

        # ── Step 9: Export ────────────────────────────
        logger.info("[9] Exporting graph files...")

        graph_dir = output_dir / "graph"
        dfd_dir = output_dir / "dfd"
        dfd_dir.mkdir(parents=True, exist_ok=True)

        kg_paths = self.exporter.export_all(G, graph_dir, dialogue_records=all_dialogue_records)
        # Also export DFD separately
        self.exporter.export_privacy_dfd(G, dfd_dir / "privacy_dfd.json")
        self.exporter.export_render_plan(G, graph_dir / "dfd_render_plan.json")

        # Summary
        stats = validation["stats"]
        result = {
            "graph_stats": stats,
            "inferred_flows": len(inferred),
            "validation": validation,
            "export_paths": kg_paths,
            "entities_merged": len(entities),
            "flows_merged": len(merged_flows)
        }

        logger.info(
            f"✅ Knowledge Graph complete — "
            f"{stats['total_nodes']} nodes, {stats['total_edges']} edges "
            f"({stats.get('inferred_edges', 0)} inferred)"
        )

        return result

    def build_graph_from_result(self, pipeline_result):
        """
        Build the unified Knowledge Graph in-memory from a single pipeline result dict.
        No file reads or writes.

        Args:
            pipeline_result: dict from PipelineRunner.process_file()

        Returns:
            dict with 'kg_dict', 'render_plan_dict', 'stats'
        """
        doc_outputs = [pipeline_result]

        logger.info(f"[1] In-memory graph build from 1 document")

        # Step 2: Merge entities
        entity_result = self.entity_merger.merge(doc_outputs)
        entities = entity_result["entities"]
        name_map = entity_result["name_map"]

        # Step 3: Merge flows
        self.flow_merger = FlowMerger(name_map=name_map)
        merged_flows = self.flow_merger.merge(doc_outputs)

        # Step 4: Build graph
        self.builder = GraphBuilder()
        self.builder.add_nodes(entities)
        self.builder.add_edges(merged_flows, name_map)

        # Step 5: Attach risks + data elements
        self.builder.attach_risks(doc_outputs, name_map)
        self.builder.attach_data_elements(name_map)

        G = self.builder.get_graph()

        # Step 6: Graph reasoning
        inferred = self.reasoning_agent.reason(G)

        # Step 7: Validate
        validation = self.validator.validate(G)

        # Step 8: Collect dialogue records
        all_dialogue_records = pipeline_result.get("dialogue_records", [])

        # Step 9: Build dicts in memory (no file writes)
        kg_dict = self.exporter.build_knowledge_graph_dict(G, dialogue_records=all_dialogue_records)
        render_plan_dict = self.exporter.build_render_plan_dict(G)

        stats = validation["stats"]
        kg_result = {
            "graph_stats": stats,
            "inferred_flows": len(inferred),
            "validation": validation,
            "entities_merged": len(entities),
            "flows_merged": len(merged_flows)
        }

        logger.info(
            f"Knowledge Graph complete (in-memory) — "
            f"{stats['total_nodes']} nodes, {stats['total_edges']} edges"
        )

        return {
            "kg_dict": kg_dict,
            "render_plan_dict": render_plan_dict,
            "kg_result": kg_result
        }

    def build_graph_from_schema_one(self, schema_one_json: dict, *, metadata: dict = None, dialogue_records: list = None):
        """Build a knowledge graph in-memory directly from Schema-1 JSON.

        This is a low-cost path that does **not** run the full pipeline. It relies on the
        structured Schema-1 output (nodes + flows) and produces the same outputs consumed
        by the HTML generator.

        Args:
            schema_one_json: Schema-1 JSON (from SchemaGenerator), must contain `nodes` and `flows`.
            metadata: optional metadata dict for validation/export context.
            dialogue_records: optional evidence records to embed into kg export.

        Returns:
            dict with 'kg_dict', 'render_plan_dict', 'kg_result'
        """
        if not schema_one_json or not isinstance(schema_one_json, dict):
            raise ValueError("schema_one_json is required")

        schema_nodes = schema_one_json.get("nodes") or []
        schema_flows = schema_one_json.get("flows") or []
        if not schema_nodes:
            raise ValueError("Schema-1 JSON has no nodes")

        # Build entities directly from schema nodes
        type_map = {
            "EXTERNAL_ENTITY": "external_entity",
            "PROCESS": "process",
            "DATA_STORE": "data_store",
            "SYSTEM": "system",
            "ACTOR": "actor",
        }

        entities = []
        schema_node_elements = {}
        for n in schema_nodes:
            node_id = (n.get("id") or "").strip()
            if not node_id:
                continue
            raw_type = (n.get("type") or "").strip()
            node_type = type_map.get(raw_type, (raw_type or "unknown").lower())
            name = (n.get("name") or node_id).strip()
            entities.append({
                "id": node_id,
                "name": name,
                "type": node_type,
                "aliases": [],
                "sources": ["schema_one"],
            })

            # Node-level data elements in schema are objects; KG nodes expect string names.
            dels = []
            for de in (n.get("data_elements") or []):
                if isinstance(de, str):
                    dels.append(de)
                elif isinstance(de, dict):
                    if de.get("name"):
                        dels.append(str(de.get("name")))
            schema_node_elements[node_id] = sorted(set([d.strip() for d in dels if str(d).strip()]))

        # Convert schema flows into the flow format GraphBuilder expects
        flows = []
        for f in schema_flows:
            if not isinstance(f, dict):
                continue
            src = (f.get("source") or "").strip()
            tgt = (f.get("target") or "").strip()
            if not src or not tgt:
                continue
            channel = (f.get("transfer_mechanism") or f.get("channel") or "")
            data_elements = f.get("data_elements") or []
            if isinstance(data_elements, str):
                data_elements = [data_elements]
            flows.append({
                "source": src,
                "target": tgt,
                "data_elements": [str(x) for x in data_elements if str(x).strip()],
                "channel": str(channel),
                "inferred": False,
                "sources": ["schema_one"],
                "evidence": [str(f.get("label"))] if f.get("label") else [],
                "evidence_trail": [],
            })

        # Build graph
        self.builder = GraphBuilder()
        self.builder.add_nodes(entities)
        self.builder.add_edges(flows, name_map={})

        # Attach node-level data elements from schema
        G = self.builder.get_graph()
        for node_id, dels in schema_node_elements.items():
            if node_id in G:
                existing = G.nodes[node_id].get("data_elements", [])
                G.nodes[node_id]["data_elements"] = sorted(set(existing + dels))

        # Reason + validate
        inferred = self.reasoning_agent.reason(G)
        validation = self.validator.validate(G)

        # Export dicts
        dialogue_records = dialogue_records or []
        kg_dict = self.exporter.build_knowledge_graph_dict(G, dialogue_records=dialogue_records)
        render_plan_dict = self.exporter.build_render_plan_dict(G)

        stats = validation["stats"]
        kg_result = {
            "graph_stats": stats,
            "inferred_flows": len(inferred),
            "validation": validation,
            "entities_merged": len(entities),
            "flows_merged": len(flows),
            "metadata": metadata or {},
        }

        logger.info(
            f"Knowledge Graph complete (schema-one) — "
            f"{stats['total_nodes']} nodes, {stats['total_edges']} edges"
        )

        return {
            "kg_dict": kg_dict,
            "render_plan_dict": render_plan_dict,
            "kg_result": kg_result,
        }

    def _load_documents(self, input_dir):
        """Load all *_intelligence.json files from directory."""
        docs = []
        for f in sorted(input_dir.glob("*_intelligence.json")):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    doc = json.load(fp)
                docs.append(doc)
                logger.info(f"  Loaded: {f.name}")
            except Exception as e:
                logger.error(f"  Failed to load {f.name}: {e}")
        return docs
