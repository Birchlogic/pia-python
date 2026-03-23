"""
Master DFD Agent — Aggregates multiple session DFDs into a single
comprehensive project-level overview.

Merges knowledge graphs, deduplicates entities, combines flows,
and generates a unified master DFD HTML.
"""
import json
from typing import List, Dict, Any
from collections import defaultdict
from utils.logger import setup_logger
from test.agents.master_dfd_agent_ai import (
    ai_validate_nodes,
    generate_executive_summary
)

logger = setup_logger("MasterDFDAgent")


class MasterDFDAgent:
    """Aggregates multiple session DFDs into a master project DFD."""

    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}

    def aggregate_sessions(self, sessions_data: List[Dict[str, Any]], use_ai_validation: bool = True) -> Dict[str, Any]:
        """
        Aggregate multiple session DFDs into a master knowledge graph.

        Args:
            sessions_data: List of dicts with keys:
                - session_id: str
                - kg_nodes: List[dict]
                - kg_edges: List[dict]
                - dfd_render_plan: dict
                - actors_json: List[dict]
                - systems_json: List[dict]
                - flows_json: List[dict]
                - risks_json: List[dict]
                - data_elements_json: List[dict]
                - compliance_schema_json: dict
                - verification_report_json: dict
                - metadata: dict (optional)

        Returns:
            Dict with:
                - master_kg: merged knowledge graph
                - master_render_plan: unified render plan
                - overview_summary: aggregated stats with ALL session data
        """
        logger.info(f"Aggregating {len(sessions_data)} sessions into master DFD")

        # Collect all data from sessions
        all_nodes = []
        all_edges = []
        all_levels = []
        all_actors = []
        all_systems = []
        all_flows = []
        all_risks = []
        all_data_elements = []
        all_compliance_schemas = []
        all_verification_reports = []
        metadata_list = []

        for session in sessions_data:
            session_id = session.get("session_id", "unknown")
            kg_nodes = session.get("kg_nodes", [])
            kg_edges = session.get("kg_edges", [])
            render_plan = session.get("dfd_render_plan", {})
            metadata = session.get("metadata", {})

            logger.info(f"  Session {session_id}: {len(kg_nodes)} nodes, {len(kg_edges)} edges")

            # Tag nodes and edges with source session
            for node in kg_nodes:
                node["_source_session"] = session_id
                all_nodes.append(node)

            for edge in kg_edges:
                edge["_source_session"] = session_id
                all_edges.append(edge)

            # Collect levels from render plan
            levels = render_plan.get("levels", [])
            if levels:
                all_levels.append(levels)

            # Collect all session-specific data
            actors = session.get("actors_json", [])
            if actors:
                for actor in actors:
                    if isinstance(actor, dict):
                        actor["_source_session"] = session_id
                        all_actors.append(actor)

            systems = session.get("systems_json", [])
            if systems:
                for system in systems:
                    if isinstance(system, dict):
                        system["_source_session"] = session_id
                        all_systems.append(system)

            flows = session.get("flows_json", [])
            if flows:
                for flow in flows:
                    if isinstance(flow, dict):
                        flow["_source_session"] = session_id
                        all_flows.append(flow)

            risks = session.get("risks_json", [])
            if risks:
                for risk in risks:
                    if isinstance(risk, dict):
                        risk["_source_session"] = session_id
                        all_risks.append(risk)

            data_elements = session.get("data_elements_json", [])
            if data_elements:
                for de in data_elements:
                    if isinstance(de, dict):
                        de["_source_session"] = session_id
                        all_data_elements.append(de)
                    elif isinstance(de, str):
                        # Handle string data elements
                        all_data_elements.append({
                            "name": de,
                            "_source_session": session_id
                        })

            compliance_schema = session.get("compliance_schema_json")
            if compliance_schema and isinstance(compliance_schema, dict):
                compliance_schema["_source_session"] = session_id
                all_compliance_schemas.append(compliance_schema)

            verification_report = session.get("verification_report_json")
            if verification_report and isinstance(verification_report, dict):
                verification_report["_source_session"] = session_id
                all_verification_reports.append(verification_report)

            if metadata:
                metadata_list.append(metadata)

        # Merge nodes (deduplicate by name + type)
        merged_nodes = self._merge_nodes(all_nodes)
        logger.info(f"Merged {len(all_nodes)} nodes → {len(merged_nodes)} unique nodes")
        
        # AI-powered validation and conflict resolution
        if use_ai_validation and self.ai_config.get("apiKey"):
            logger.info("Running AI validation on merged entities...")
            merged_nodes = self._ai_validate_nodes(merged_nodes, sessions_data)
            logger.info("AI validation complete")

        # Merge edges (deduplicate by source + target + data elements)
        merged_edges = self._merge_edges(all_edges, merged_nodes)
        logger.info(f"Merged {len(all_edges)} edges → {len(merged_edges)} unique edges")

        # Build unified render plan
        master_render_plan = self._build_master_render_plan(merged_nodes, all_levels)

        # Compute comprehensive overview summary
        overview_summary = self._compute_overview(
            merged_nodes, merged_edges, sessions_data, metadata_list,
            all_actors, all_systems, all_flows, all_risks, all_data_elements,
            all_compliance_schemas, all_verification_reports
        )
        
        # AI-generated executive summary
        if use_ai_validation and self.ai_config.get("apiKey"):
            logger.info("Generating AI executive summary...")
            overview_summary["ai_executive_summary"] = self._generate_executive_summary(
                merged_nodes, merged_edges, overview_summary
            )
            logger.info("Executive summary generated")

        master_kg = {
            "nodes": merged_nodes,
            "edges": merged_edges,
            "dialogue_records": []  # Master DFD doesn't need dialogue records
        }

        return {
            "master_kg": master_kg,
            "master_render_plan": master_render_plan,
            "overview_summary": overview_summary
        }

    def _merge_nodes(self, nodes: List[Dict]) -> List[Dict]:
        """Deduplicate nodes by (name, type), merge aliases and data elements."""
        node_map = {}

        for node in nodes:
            name = node.get("name", "").strip().lower()
            ntype = node.get("type", "unknown")
            key = (name, ntype)

            if key not in node_map:
                # First occurrence
                node_map[key] = {
                    "id": node.get("id", f"{ntype}_{name.replace(' ', '_')}"),
                    "name": node.get("name", name),
                    "type": ntype,
                    "aliases": list(set(node.get("aliases", []))),
                    "data_elements": list(set(node.get("data_elements", []))),
                    "risks": node.get("risks", []),
                    "sources": node.get("sources", []),
                    "_source_sessions": [node.get("_source_session", "unknown")]
                }
            else:
                # Merge with existing
                existing = node_map[key]
                existing["aliases"] = list(set(existing["aliases"] + node.get("aliases", [])))
                existing["data_elements"] = list(set(existing["data_elements"] + node.get("data_elements", [])))
                existing["risks"].extend(node.get("risks", []))
                existing["sources"].extend(node.get("sources", []))
                existing["_source_sessions"].append(node.get("_source_session", "unknown"))

        return list(node_map.values())

    def _merge_edges(self, edges: List[Dict], merged_nodes: List[Dict]) -> List[Dict]:
        """Deduplicate edges by (source, target), merge data elements and evidence."""
        # Build node name → id map
        name_to_id = {}
        for node in merged_nodes:
            name_to_id[node["name"].lower()] = node["id"]

        edge_map = {}

        for edge in edges:
            src = edge.get("source", "").strip().lower()
            tgt = edge.get("target", "").strip().lower()

            # Map to merged node IDs
            src_id = name_to_id.get(src, src)
            tgt_id = name_to_id.get(tgt, tgt)

            key = (src_id, tgt_id)

            if key not in edge_map:
                edge_map[key] = {
                    "source": src_id,
                    "target": tgt_id,
                    "data_elements": list(set(edge.get("data_elements", []))),
                    "flow_type": edge.get("flow_type", "data_flow"),
                    "channel": edge.get("channel", ""),
                    "evidence": edge.get("evidence", []),
                    "evidence_trail": edge.get("evidence_trail", []),
                    "_source_sessions": [edge.get("_source_session", "unknown")]
                }
            else:
                # Merge
                existing = edge_map[key]
                existing["data_elements"] = list(set(existing["data_elements"] + edge.get("data_elements", [])))
                existing["evidence"].extend(edge.get("evidence", []))
                existing["evidence_trail"].extend(edge.get("evidence_trail", []))
                existing["_source_sessions"].append(edge.get("_source_session", "unknown"))

        return list(edge_map.values())

    def _build_master_render_plan(self, nodes: List[Dict], all_levels: List[List[List[str]]]) -> Dict:
        """Build a unified render plan for the master DFD."""
        # Simple strategy: collect all unique node names by type
        actors = []
        systems = []
        data_stores = []

        for node in nodes:
            ntype = node.get("type", "unknown")
            name = node.get("name", "")

            if ntype in ("actor", "external_entity"):
                if name not in actors:
                    actors.append(name)
            elif ntype in ("system", "process"):
                if name not in systems:
                    systems.append(name)
            elif ntype in ("data_store", "database"):
                if name not in data_stores:
                    data_stores.append(name)

        # Build levels: [actors], [systems], [data_stores]
        levels = []
        if actors:
            levels.append(actors)
        if systems:
            levels.append(systems)
        if data_stores:
            levels.append(data_stores)

        return {"levels": levels}

    def _compute_overview(
        self, nodes: List[Dict], edges: List[Dict], sessions: List[Dict], metadata_list: List[Dict],
        all_actors: List[Dict], all_systems: List[Dict], all_flows: List[Dict], all_risks: List[Dict],
        all_data_elements: List[Dict], all_compliance_schemas: List[Dict], all_verification_reports: List[Dict]
    ) -> Dict[str, Any]:
        """Compute comprehensive overview statistics from aggregated data."""
        
        # Count by type
        node_types = defaultdict(int)
        for node in nodes:
            node_types[node.get("type", "unknown")] += 1

        # Extract project name from metadata
        project_name = "Master Project"
        departments = set()
        for meta in metadata_list:
            if meta.get("project_name"):
                project_name = meta["project_name"]
            if meta.get("department"):
                departments.add(meta["department"])

        # Aggregate actors by type
        actor_types = defaultdict(int)
        for actor in all_actors:
            actor_types[actor.get("type", "unknown")] += 1

        # Aggregate systems by category
        system_categories = defaultdict(int)
        for system in all_systems:
            system_categories[system.get("category", "unknown")] += 1

        # Aggregate flows by type
        flow_types = defaultdict(int)
        for flow in all_flows:
            flow_types[flow.get("flow_type", "data_flow")] += 1

        # Aggregate risks by severity
        risk_severity = defaultdict(int)
        for risk in all_risks:
            risk_severity[risk.get("severity", "MEDIUM")] += 1

        # Count unique data elements
        unique_data_elements = set()
        for de in all_data_elements:
            unique_data_elements.add(de.get("name", ""))

        # Compliance summary
        compliance_summary = {
            "total_schemas": len(all_compliance_schemas),
            "schemas_by_session": {cs.get("_source_session", "unknown"): True for cs in all_compliance_schemas}
        }

        # Verification summary
        verification_summary = {
            "total_reports": len(all_verification_reports),
            "reports_by_session": {vr.get("_source_session", "unknown"): True for vr in all_verification_reports}
        }
        
        # KG-level aggregates
        total_risks = sum(len(n.get("risks", [])) for n in nodes)
        total_data_elements = sum(len(n.get("data_elements", [])) for n in nodes)

        return {
            "project_name": project_name,
            "departments": list(departments),
            "total_sessions": len(sessions),
            "sessions_aggregated": [s.get("session_id", "unknown") for s in sessions],
            
            # Knowledge Graph Stats
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "node_types": dict(node_types),
            
            # Detailed Entity Stats
            "total_actors": len(all_actors),
            "actor_types": dict(actor_types),
            "total_systems": len(all_systems),
            "system_categories": dict(system_categories),
            "total_flows": len(all_flows),
            "flow_types": dict(flow_types),
            
            # Risk & Data Stats
            "total_risks": len(all_risks),
            "risk_severity_breakdown": dict(risk_severity),
            "total_data_elements": len(unique_data_elements),
            "unique_data_elements_list": list(unique_data_elements)[:50],
            
            # Compliance & Verification
            "compliance_summary": compliance_summary,
            "verification_summary": verification_summary,
            
            # Aggregated from KG
            "kg_total_risks": total_risks,
            "kg_total_data_elements": total_data_elements
        }
    
    def _ai_validate_nodes(self, nodes: List[Dict], sessions_data: List[Dict]) -> List[Dict]:
        """Use AI to validate and resolve conflicts in merged nodes."""
        return ai_validate_nodes(nodes, sessions_data, self.ai_config)
    
    def _generate_executive_summary(self, nodes: List[Dict], edges: List[Dict], overview: Dict) -> str:
        """Generate AI-powered executive summary for Master DFD."""
        return generate_executive_summary(nodes, edges, overview, self.ai_config)
