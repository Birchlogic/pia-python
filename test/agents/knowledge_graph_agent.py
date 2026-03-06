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

    def __init__(self):
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

        # ── Step 8: Export ────────────────────────────
        logger.info("[8] Exporting graph files...")

        graph_dir = output_dir / "graph"
        dfd_dir = output_dir / "dfd"
        dfd_dir.mkdir(parents=True, exist_ok=True)

        kg_paths = self.exporter.export_all(G, graph_dir)
        # Also export DFD separately
        self.exporter.export_privacy_dfd(G, dfd_dir / "privacy_dfd.json")
        self.exporter.export_render_plan(G, dfd_dir / "dfd_render_plan.json")

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
