"""
Graph Exporter — Exports the unified Knowledge Graph to:
  1. knowledge_graph.json — full graph with all metadata
  2. privacy_dfd.json — DFD-ready format
  3. dfd_render_plan.json — layout instructions for visualization
"""
import json
import networkx as nx
from pathlib import Path
from collections import defaultdict
from utils.logger import setup_logger

logger = setup_logger("GraphExporter")

# DFD type mapping
DFD_TYPE_MAP = {
    "external_entity": "external_entity",
    "system": "process",
    "actor": "process",
    "data_store": "data_store",
    "process": "process",
    "unknown": "process"
}

DFD_SHAPE_MAP = {
    "external_entity": "square",
    "process": "circle",
    "data_store": "open_rectangle"
}


class GraphExporter:

    def export_all(self, G, output_dir, dialogue_records=None):
        """Export graph in all formats."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        kg_path = output_dir / "knowledge_graph.json"
        dfd_path = output_dir / "privacy_dfd.json"
        plan_path = output_dir / "dfd_render_plan.json"

        self.export_knowledge_graph(G, kg_path, dialogue_records=dialogue_records)
        self.export_privacy_dfd(G, dfd_path)
        self.export_render_plan(G, plan_path)

        return {
            "knowledge_graph": str(kg_path),
            "privacy_dfd": str(dfd_path),
            "dfd_render_plan": str(plan_path)
        }

    def build_knowledge_graph_dict(self, G, dialogue_records=None):
        """Build knowledge graph dict in memory (no file write)."""
        nodes = []
        for node_id, data in G.nodes(data=True):
            nodes.append({
                "id": node_id,
                "name": data.get("name", node_id),
                "type": data.get("type", "unknown"),
                "aliases": data.get("aliases", []),
                "data_elements": data.get("data_elements", []),
                "risks": data.get("risks", []),
                "sources": data.get("sources", [])
            })

        edges = []
        for src, tgt, data in G.edges(data=True):
            edges.append({
                "source": src,
                "target": tgt,
                "data_elements": data.get("data_elements", []),
                "flow_type": data.get("flow_type", "unknown"),
                "channel": data.get("channel", ""),
                "inferred": data.get("inferred", False),
                "sources": data.get("sources", []),
                "evidence": data.get("evidence", []),
                "evidence_trail": data.get("evidence_trail", [])
            })

        return {
            "nodes": nodes,
            "edges": edges,
            "dialogue_records": dialogue_records or [],
            "metadata": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "inferred_edges": sum(1 for e in edges if e["inferred"])
            }
        }

    def build_render_plan_dict(self, G):
        """Build render plan dict in memory (no file write)."""
        levels = self._compute_levels(G)
        plan = {
            "layout": "left_to_right",
            "levels": levels,
            "node_styles": {}
        }
        for node_id, data in G.nodes(data=True):
            orig_type = data.get("type", "unknown")
            dfd_type = DFD_TYPE_MAP.get(orig_type, "process")
            risk_count = len(data.get("risks", []))
            plan["node_styles"][node_id] = {
                "shape": DFD_SHAPE_MAP.get(dfd_type, "circle"),
                "color": self._risk_color(risk_count),
                "label": data.get("name", node_id)
            }
        return plan

    def export_knowledge_graph(self, G, path, dialogue_records=None):
        """Export full knowledge graph JSON to file."""
        kg = self.build_knowledge_graph_dict(G, dialogue_records)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(kg, f, indent=2)
        logger.info(f"Exported knowledge_graph.json ({len(kg['nodes'])} nodes, {len(kg['edges'])} edges)")

    def export_privacy_dfd(self, G, path):
        """Export DFD-ready JSON."""
        nodes = []
        for node_id, data in G.nodes(data=True):
            orig_type = data.get("type", "unknown")
            dfd_type = DFD_TYPE_MAP.get(orig_type, "process")
            nodes.append({
                "id": node_id,
                "name": data.get("name", node_id),
                "dfd_type": dfd_type,
                "shape": DFD_SHAPE_MAP.get(dfd_type, "circle"),
                "data_elements": data.get("data_elements", []),
                "risk_count": len(data.get("risks", []))
            })

        flows = []
        for src, tgt, data in G.edges(data=True):
            flows.append({
                "from": src,
                "to": tgt,
                "label": ", ".join(data.get("data_elements", [])[:3]) or "data",
                "inferred": data.get("inferred", False)
            })

        dfd = {"nodes": nodes, "flows": flows}

        with open(path, "w", encoding="utf-8") as f:
            json.dump(dfd, f, indent=2)
        logger.info(f"Exported privacy_dfd.json ({len(nodes)} nodes, {len(flows)} flows)")

    def export_render_plan(self, G, path):
        """Generate DFD layout instructions using topological ordering."""
        levels = self._compute_levels(G)

        plan = {
            "layout": "left_to_right",
            "levels": levels,
            "node_styles": {}
        }

        for node_id, data in G.nodes(data=True):
            orig_type = data.get("type", "unknown")
            dfd_type = DFD_TYPE_MAP.get(orig_type, "process")
            risk_count = len(data.get("risks", []))
            plan["node_styles"][node_id] = {
                "shape": DFD_SHAPE_MAP.get(dfd_type, "circle"),
                "color": self._risk_color(risk_count),
                "label": data.get("name", node_id)
            }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2)
        logger.info(f"Exported dfd_render_plan.json ({len(levels)} levels)")

    def _compute_levels(self, G):
        """Compute hierarchical levels using longest-path layering."""
        # Use topological sort for DAG-like ordering
        try:
            topo = list(nx.topological_sort(G))
        except nx.NetworkXUnfeasible:
            # Graph has cycles — break them for layout
            topo = list(G.nodes)

        # Assign levels based on longest path from sources
        level_map = {}
        for node in topo:
            preds = list(G.predecessors(node))
            if not preds:
                level_map[node] = 0
            else:
                level_map[node] = max(level_map.get(p, 0) for p in preds) + 1

        # Group by level
        level_groups = defaultdict(list)
        for node, level in level_map.items():
            name = G.nodes[node].get("name", node)
            level_groups[level].append(name)

        levels = [level_groups[i] for i in sorted(level_groups.keys())]
        return levels

    def _risk_color(self, risk_count):
        """Return color based on risk count."""
        if risk_count >= 3:
            return "#ff4444"
        elif risk_count >= 1:
            return "#ffaa00"
        else:
            return "#44cc44"
