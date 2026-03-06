"""
Graph Reasoning Agent — Infers implicit data flows not explicitly
mentioned in text using transitive, storage, and integration rules.
"""
import networkx as nx
from utils.logger import setup_logger

logger = setup_logger("GraphReasoning")


class GraphReasoningAgent:

    def __init__(self):
        self.inferred_count = 0

    def reason(self, G):
        """
        Apply reasoning rules to infer implicit flows.

        Rules:
          1. Transitive flow: A→B, B→C ⟹ A→C (via B)
          2. Storage propagation: Agent→Excel, Excel→OneDrive ⟹ Agent→OneDrive
          3. Integration inference: if system A integrates with system B, propagate flows

        All inferred edges are marked with inferred=True.

        Args:
            G: NetworkX DiGraph (modified in-place)

        Returns:
            list of inferred edge dicts
        """
        inferred_edges = []

        # ── Rule 1: Transitive flows ──────────────────
        transitive = self._infer_transitive(G)
        inferred_edges.extend(transitive)

        # ── Rule 2: Storage propagation ───────────────
        storage = self._infer_storage_propagation(G)
        inferred_edges.extend(storage)

        # ── Rule 3: External → system chain ───────────
        external = self._infer_external_chains(G)
        inferred_edges.extend(external)

        self.inferred_count = len(inferred_edges)
        logger.info(f"Inferred {len(inferred_edges)} implicit flows")
        return inferred_edges

    def _infer_transitive(self, G):
        """Rule 1: If A→B and B→C, infer A→C when B is a system/process."""
        inferred = []
        for b_node in list(G.nodes):
            b_type = G.nodes[b_node].get("type", "")
            if b_type not in ("system", "process"):
                continue

            predecessors = list(G.predecessors(b_node))
            successors = list(G.successors(b_node))

            for a in predecessors:
                for c in successors:
                    if a == c:
                        continue
                    if G.has_edge(a, c):
                        continue

                    # Combine data elements from both legs
                    ab_data = G[a][b_node].get("data_elements", [])
                    bc_data = G[b_node][c].get("data_elements", [])
                    shared = sorted(set(ab_data) & set(bc_data)) or sorted(set(ab_data + bc_data))

                    b_name = G.nodes[b_node].get("name", b_node)
                    G.add_edge(a, c,
                        data_elements=shared,
                        flow_type="transfer",
                        inferred=True,
                        channel=f"via {b_name}",
                        sources=[],
                        evidence=[f"Transitive: {a}→{b_node}→{c}"]
                    )
                    inferred.append({
                        "source": a, "target": c,
                        "data_elements": shared,
                        "rule": "transitive",
                        "via": b_node
                    })
        return inferred

    def _infer_storage_propagation(self, G):
        """Rule 2: If Actor→DataStore1 and DataStore1→DataStore2, infer Actor→DataStore2."""
        inferred = []
        data_stores = [n for n, d in G.nodes(data=True) if d.get("type") == "data_store"]

        for ds1 in data_stores:
            for ds2 in G.successors(ds1):
                if G.nodes.get(ds2, {}).get("type") != "data_store":
                    continue
                # Propagate all incoming flows to ds1 through to ds2
                for pred in G.predecessors(ds1):
                    if pred == ds2 or G.has_edge(pred, ds2):
                        continue
                    pred_type = G.nodes.get(pred, {}).get("type", "")
                    if pred_type in ("actor", "process", "system"):
                        data = G[pred][ds1].get("data_elements", [])
                        ds1_name = G.nodes[ds1].get("name", ds1)
                        G.add_edge(pred, ds2,
                            data_elements=data,
                            flow_type="storage",
                            inferred=True,
                            channel=f"via {ds1_name}",
                            sources=[],
                            evidence=[f"Storage propagation: {pred}→{ds1}→{ds2}"]
                        )
                        inferred.append({
                            "source": pred, "target": ds2,
                            "data_elements": data,
                            "rule": "storage_propagation",
                            "via": ds1
                        })
        return inferred

    def _infer_external_chains(self, G):
        """Rule 3: If External→SystemA and SystemA→SystemB, infer External→SystemB."""
        inferred = []
        externals = [n for n, d in G.nodes(data=True) if d.get("type") == "external_entity"]

        for ext in externals:
            for sys_a in G.successors(ext):
                if G.nodes.get(sys_a, {}).get("type") != "system":
                    continue
                for sys_b in G.successors(sys_a):
                    if G.nodes.get(sys_b, {}).get("type") != "system":
                        continue
                    if ext == sys_b or G.has_edge(ext, sys_b):
                        continue
                    data = G[ext][sys_a].get("data_elements", [])
                    sys_a_name = G.nodes[sys_a].get("name", sys_a)
                    G.add_edge(ext, sys_b,
                        data_elements=data,
                        flow_type="collection",
                        inferred=True,
                        channel=f"via {sys_a_name}",
                        sources=[],
                        evidence=[f"Integration: {ext}→{sys_a}→{sys_b}"]
                    )
                    inferred.append({
                        "source": ext, "target": sys_b,
                        "data_elements": data,
                        "rule": "integration_inference",
                        "via": sys_a
                    })
        return inferred
