"""
Graph Builder — Loads document intelligence JSONs and builds a
unified NetworkX DiGraph with all entities, flows, and risks.
"""
import json
import networkx as nx
from pathlib import Path
from utils.logger import setup_logger

logger = setup_logger("GraphBuilder")


class GraphBuilder:

    def __init__(self):
        self.G = nx.DiGraph()

    def add_nodes(self, entities):
        """Add merged entities as nodes."""
        for ent in entities:
            node_id = ent["id"]
            self.G.add_node(
                node_id,
                name=ent["name"],
                type=ent["type"],
                aliases=ent.get("aliases", []),
                data_elements=[],
                risks=[],
                sources=ent.get("sources", [])
            )
        logger.info(f"Added {len(entities)} nodes")

    def add_edges(self, flows, name_map):
        """Add merged flows as edges."""
        added = 0
        for flow in flows:
            src = self._resolve_to_id(flow["source"], name_map)
            tgt = self._resolve_to_id(flow["target"], name_map)

            # Ensure nodes exist
            if src not in self.G:
                self.G.add_node(src, name=flow["source"], type="unknown", aliases=[], data_elements=[], risks=[], sources=[])
            if tgt not in self.G:
                self.G.add_node(tgt, name=flow["target"], type="unknown", aliases=[], data_elements=[], risks=[], sources=[])

            data_elems = flow.get("data_elements", [])

            # Merge with existing edge if present
            if self.G.has_edge(src, tgt):
                existing = self.G[src][tgt].get("data_elements", [])
                data_elems = sorted(set(existing + data_elems))

            # Merge evidence_trail if edge already exists
            existing_trail = []
            if self.G.has_edge(src, tgt):
                existing_trail = self.G[src][tgt].get("evidence_trail", [])

            new_trail = flow.get("evidence_trail", [])
            merged_trail = existing_trail + [t for t in new_trail if t not in existing_trail]

            self.G.add_edge(
                src, tgt,
                data_elements=data_elems,
                channel=flow.get("channel", ""),
                flow_type=self._infer_flow_type(flow),
                inferred=flow.get("inferred", False),
                sources=flow.get("sources", []),
                evidence=flow.get("evidence", []),
                evidence_trail=merged_trail[:10]
            )
            added += 1

        logger.info(f"Added {added} edges")

    def attach_risks(self, doc_outputs, name_map):
        """Attach risks from document outputs to relevant nodes."""
        for doc in doc_outputs:
            risks = doc.get("risks", [])
            for risk in risks:
                # Try to attach risk to a relevant node
                related = self._find_related_node(risk, name_map)
                if related and related in self.G:
                    existing_risks = self.G.nodes[related].get("risks", [])
                    existing_risks.append({
                        "risk_name": risk.get("risk_name", risk.get("risk_type", "unknown")),
                        "severity": risk.get("severity", "medium"),
                        "description": risk.get("description", risk.get("evidence", "")),
                        "source": doc.get("metadata", {}).get("source_file", "")
                    })
                    self.G.nodes[related]["risks"] = existing_risks

    def attach_data_elements(self, name_map):
        """Propagate data elements from edges to nodes."""
        for src, tgt, data in self.G.edges(data=True):
            elements = data.get("data_elements", [])
            for node_id in [src, tgt]:
                if node_id in self.G:
                    existing = self.G.nodes[node_id].get("data_elements", [])
                    self.G.nodes[node_id]["data_elements"] = sorted(set(existing + elements))

    def get_graph(self):
        """Return the built NetworkX DiGraph."""
        return self.G

    def _resolve_to_id(self, name, name_map):
        """Resolve a name to a node ID."""
        import re
        lower = name.lower().strip()
        if lower in name_map:
            canonical = name_map[lower]
        else:
            canonical = name
        return re.sub(r"[^a-z0-9]+", "_", canonical.lower().strip()).strip("_")

    def _infer_flow_type(self, flow):
        """Infer flow type from channel/context."""
        channel = flow.get("channel", "").lower()
        if any(w in channel for w in ["api", "sync", "automated"]):
            return "transfer"
        if any(w in channel for w in ["store", "save", "database"]):
            return "storage"
        if any(w in channel for w in ["collect", "form", "phone"]):
            return "collection"
        return "processing"

    def _find_related_node(self, risk, name_map):
        """Find the node most related to a risk."""
        desc = json.dumps(risk).lower() if isinstance(risk, dict) else str(risk).lower()
        best, best_overlap = None, 0
        for node_id, data in self.G.nodes(data=True):
            name = data.get("name", "").lower()
            aliases = [a.lower() for a in data.get("aliases", [])]
            for candidate in [name] + aliases:
                if candidate in desc and len(candidate) > best_overlap:
                    best = node_id
                    best_overlap = len(candidate)
        return best
