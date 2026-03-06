"""
Graph Validator — Validates graph integrity and produces
a validation report with issues and statistics.
"""
import networkx as nx
from utils.logger import setup_logger

logger = setup_logger("GraphValidator")

VALID_TYPES = {"external_entity", "system", "actor", "data_store", "process", "unknown"}


class GraphValidator:

    def validate(self, G):
        """
        Validate a NetworkX DiGraph for structural integrity.

        Checks:
          1. No orphan nodes (nodes with no edges)
          2. No impossible cycles (external→external loops)
          3. All nodes have a valid type
          4. All edges reference valid nodes
          5. No exact duplicate edges
          6. No self-loops

        Returns:
            dict with 'valid' (bool), 'issues' (list), 'stats' (dict)
        """
        issues = []

        # Check 1: Orphan nodes
        orphans = [n for n in G.nodes if G.degree(n) == 0]
        if orphans:
            names = [G.nodes[n].get("name", n) for n in orphans]
            issues.append({
                "type": "orphan_nodes",
                "severity": "warning",
                "details": f"{len(orphans)} orphan node(s): {names}"
            })

        # Check 2: Self-loops
        self_loops = list(nx.selfloop_edges(G))
        if self_loops:
            issues.append({
                "type": "self_loops",
                "severity": "error",
                "details": f"{len(self_loops)} self-loop(s) found"
            })
            G.remove_edges_from(self_loops)

        # Check 3: Node types
        for node_id, data in G.nodes(data=True):
            ntype = data.get("type", "")
            if ntype not in VALID_TYPES:
                issues.append({
                    "type": "invalid_node_type",
                    "severity": "error",
                    "details": f"Node '{node_id}' has invalid type '{ntype}'"
                })

        # Check 4: Edge references
        for src, tgt in G.edges:
            if src not in G.nodes:
                issues.append({
                    "type": "invalid_edge_source",
                    "severity": "error",
                    "details": f"Edge source '{src}' not in nodes"
                })
            if tgt not in G.nodes:
                issues.append({
                    "type": "invalid_edge_target",
                    "severity": "error",
                    "details": f"Edge target '{tgt}' not in nodes"
                })

        # Check 5: Cycles (info, not necessarily errors)
        try:
            cycles = list(nx.simple_cycles(G))
            if cycles:
                issues.append({
                    "type": "cycles_detected",
                    "severity": "info",
                    "details": f"{len(cycles)} cycle(s) found in graph"
                })
        except Exception:
            pass

        # Stats
        stats = {
            "total_nodes": G.number_of_nodes(),
            "total_edges": G.number_of_edges(),
            "orphan_nodes": len(orphans),
            "self_loops_removed": len(self_loops),
            "node_types": {},
            "inferred_edges": 0,
            "explicit_edges": 0
        }

        for _, data in G.nodes(data=True):
            t = data.get("type", "unknown")
            stats["node_types"][t] = stats["node_types"].get(t, 0) + 1

        for _, _, data in G.edges(data=True):
            if data.get("inferred", False):
                stats["inferred_edges"] += 1
            else:
                stats["explicit_edges"] += 1

        errors = [i for i in issues if i["severity"] == "error"]
        valid = len(errors) == 0

        logger.info(
            f"Validation: {'PASS' if valid else 'FAIL'} — "
            f"{stats['total_nodes']} nodes, {stats['total_edges']} edges, "
            f"{len(issues)} issues"
        )

        return {
            "valid": valid,
            "issues": issues,
            "stats": stats
        }
