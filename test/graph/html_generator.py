"""
HTML Generator Agent — Produces RLM-style swimlane DFD from
knowledge_graph.json + dfd_render_plan.json produced by the
aggressive processing pipeline.

Visual structure (matches agent/dfd_html_renderer.py output):
Actors | DATA COLLECTION | DATA PROCESSING | DATA DISPERSAL | STORAGE
with department name shown in the center processing column.
SVG arrows are drawn in JavaScript after DOM layout.
"""
import json
from pathlib import Path
from typing import Any, Dict, List
from utils.logger import setup_logger

logger = setup_logger("HTMLGenerator")

ACTOR_COLORS = {
    "external": {"bg": "#fffde7", "border": "#f9a825", "label": "#f57f17"},
    "internal": {"bg": "#fce4ec", "border": "#e91e63", "label": "#880e4f"},
    "vendor":   {"bg": "#f1f8e9", "border": "#7cb342", "label": "#33691e"},
}

SINK_PALETTE = [
    "#1565c0", "#e91e63", "#4caf50", "#7b1fa2", "#ff6f00",
    "#00838f", "#c62828", "#6a1b9a", "#2196f3", "#9c27b0",
    "#f44336", "#009688", "#ff9800", "#3f51b5", "#795548",
]


class HTMLGeneratorAgent:
    """Generates an RLM-style swimlane DFD HTML from aggressive pipeline data."""

    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}

    def generate_from_data(self, kg, render_plan, pipeline_docs=None):
        """
        Generate HTML entirely in memory from data dicts.
        No file reads or writes.

        Args:
            kg: knowledge_graph dict with nodes, edges, dialogue_records
            render_plan: render plan dict with levels
            pipeline_docs: optional dict of pipeline intelligence docs

        Returns:
            str: self-contained HTML
        """
        pipeline_docs = pipeline_docs or {}
        nodes = kg.get("nodes", [])
        edges = kg.get("edges", [])
        levels = render_plan.get("levels", [])

        col_map = self._build_column_map(nodes, levels, kg)
        row_map = self._build_row_map(nodes)

        logger.info(f"Building HTML (in-memory): {len(nodes)} nodes, {len(edges)} edges")
        return self._build_html(nodes, edges, kg, pipeline_docs, col_map, row_map)

    def generate(self, graph_dir, pipeline_dir, output_path, **kwargs):
        graph_dir = Path(graph_dir)
        pipeline_dir = Path(pipeline_dir)
        output_path = Path(output_path)

        def load_json(path):
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return {}

        kg = load_json(graph_dir / "graph" / "knowledge_graph.json")
        render_plan = load_json(graph_dir / "graph" / "dfd_render_plan.json")
        pipeline_docs = {}
        for p in pipeline_dir.glob("*_intelligence.json"):
            pipeline_docs[p.name] = load_json(p)

        nodes = kg.get("nodes", [])
        edges = kg.get("edges", [])
        levels = render_plan.get("levels", [])

        col_map = self._build_column_map(nodes, levels, kg)
        row_map = self._build_row_map(nodes)

        logger.info(f"Building HTML: {len(nodes)} nodes, {len(edges)} edges")
        html = self._build_html(nodes, edges, kg, pipeline_docs, col_map, row_map)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info(f"✅ HTML written to {output_path} ({len(html)} chars)")
        return str(output_path)

    def _build_column_map(self, nodes, levels, kg):
        col_map = {}
        level_lookup = {}
        for i, level_names in enumerate(levels):
            for name in level_names:
                level_lookup[name] = i
        max_level = max(level_lookup.values()) if level_lookup else 0
        for node in nodes:
            nid = node["id"]
            ntype = node.get("type", "unknown")
            if ntype == "data_store":
                col_map[nid] = 3
                continue
            level = level_lookup.get(node["name"])
            if level is not None:
                if max_level <= 3:
                    col_map[nid] = level
                else:
                    if level == 0:
                        col_map[nid] = 0
                    elif level <= 2:
                        col_map[nid] = 1
                    else:
                        col_map[nid] = 2
            else:
                col_map[nid] = 1
        return col_map

    def _build_row_map(self, nodes):
        row_map = {}
        for node in nodes:
            nid = node["id"]
            ntype = node.get("type", "unknown")
            if ntype == "data_store":
                row_map[nid] = 1
            elif ntype == "system":
                row_map[nid] = 1
            elif ntype in ("actor", "external_entity"):
                name_lower = node.get("name", "").lower()
                internal_kw = ["team lead", "agent", "qa", "quality", "retention",
                               "compliance", "email system", "shared mailbox", "cti",
                               "department", "head", "manager", "supervisor",
                               "analyst", "officer", "executive"]
                vendor_kw = ["vendor", "partner", "dsa", "third party", "outsource"]
                external_kw = ["customer", "client", "borrower", "applicant", "caller"]
                if any(kw in name_lower for kw in external_kw):
                    row_map[nid] = 0
                elif any(kw in name_lower for kw in vendor_kw):
                    row_map[nid] = 2
                elif any(kw in name_lower for kw in internal_kw):
                    row_map[nid] = 1
                else:
                    row_map[nid] = 1  # Default actors to internal
            else:
                name_lower = node.get("name", "").lower()
                row_map[nid] = 0 if "customer" in name_lower else 1
        return row_map

    @staticmethod
    def _build_speaker_role_map(dialogue_records):
        """Build a mapping of speaker names → roles from dialogue records."""
        role_map = {}
        for rec in (dialogue_records or []):
            speaker = rec.get("speaker", "").strip()
            role = rec.get("role", "").strip()
            if speaker and role and speaker not in role_map:
                role_map[speaker] = role
        return role_map

    @staticmethod
    def _get_connected_node_ids(edges):
        """Return set of node IDs that appear in at least one edge."""
        connected = set()
        for e in edges:
            connected.add(e.get("source", ""))
            connected.add(e.get("target", ""))
        return connected

    def _transform_to_dfd(self, nodes, edges, col_map, row_map, department="Department"):
        external_nodes, internal_nodes, vendor_nodes, data_stores = [], [], [], []
        for n in nodes:
            ntype = n.get("type", "unknown")
            row = row_map.get(n["id"], 1)
            if ntype == "data_store":
                data_stores.append(n)
            elif row == 0:
                external_nodes.append(n)
            elif row == 2:
                vendor_nodes.append(n)
            else:
                internal_nodes.append(n)

        def build_actor(aid, aname, atype, anodes):
            bps = []
            for n in anodes:
                bps.append({
                    "id": f"bp_{n['id']}",
                    "name": n["name"],
                    "collection_sources": [{
                        "name": n["name"],
                        "data_elements": n.get("data_elements", [])[:8]
                    }]
                })
            return {"id": aid, "name": aname, "type": atype, "business_processes": bps}

        actors = []
        if external_nodes:
            actors.append(build_actor("external", "External Parties", "external", external_nodes))
        else:
            actors.append({"id": "external", "name": "External Parties", "type": "external", "business_processes": []})
        if internal_nodes:
            actors.append(build_actor("internal", "Internal Departments", "internal", internal_nodes))
        else:
            actors.append({"id": "internal", "name": "Internal Departments", "type": "internal", "business_processes": []})
        if vendor_nodes:
            actors.append(build_actor("vendors", "Vendors/Partners", "vendor", vendor_nodes))
        else:
            actors.append({"id": "vendors", "name": "Vendors/Partners", "type": "vendor", "business_processes": []})

        # Build dispersal sinks
        incoming_count = {}
        for e in edges:
            incoming_count[e.get("target", "")] = incoming_count.get(e.get("target", ""), 0) + 1
        sink_candidates = []
        for n in nodes:
            nid = n["id"]
            if n.get("type") == "data_store":
                continue
            if incoming_count.get(nid, 0) >= 2 or len(n.get("risks", [])) > 0:
                row = row_map.get(nid, 1)
                actor_id = "external" if row == 0 else ("vendors" if row == 2 else "internal")
                sink_candidates.append({
                    "id": f"sink_{nid}", "name": n["name"], "actor_id": actor_id,
                    "node_id": nid, "color": SINK_PALETTE[len(sink_candidates) % len(SINK_PALETTE)]
                })

        storage_systems = [{"name": ds["name"], "type": "cloud"} for ds in data_stores]
        for n in nodes:
            if n.get("type") == "system":
                storage_systems.append({"name": n["name"], "type": "cloud"})

        data_flows = []
        ci = 0
        for actor in actors:
            for bp in actor.get("business_processes", []):
                srcs = bp.get("collection_sources", [])
                lbl = ", ".join(e for s in srcs for e in s.get("data_elements", [])[:2])[:60]
                data_flows.append({
                    "from_id": bp["id"], "to_id": "central_process",
                    "color": SINK_PALETTE[ci % len(SINK_PALETTE)], "label": lbl
                })
                ci += 1
        for sink in sink_candidates:
            data_flows.append({
                "from_id": "central_process", "to_id": sink["id"],
                "color": sink["color"], "label": ""
            })

        return {
            "department": department, "version": "1.0",
            "central_process": f"{department} Processing Hub",
            "actors": actors, "dispersal_sinks": sink_candidates,
            "storage_systems": storage_systems, "data_flows": data_flows,
        }

    def _build_html(self, nodes, edges, kg, pipeline_docs, col_map, row_map, department="Department"):
        dept = department
        for doc_name, doc_data in (pipeline_docs or {}).items():
            if isinstance(doc_data, dict):
                md = doc_data.get("metadata", doc_data)
                if md.get("department"):
                    dept = md["department"]
                    break

        # Get dialogue records from KG for evidence provenance
        dialogue_records = kg.get("dialogue_records", [])
        role_map = self._build_speaker_role_map(dialogue_records)

        # Filter out unconnected actor nodes (actors with no edges)
        connected_ids = self._get_connected_node_ids(edges)
        filtered_nodes = []
        for n in nodes:
            ntype = n.get("type", "unknown")
            # Always keep systems and data stores; only filter actors
            if ntype in ("actor", "external_entity"):
                if n["id"] in connected_ids:
                    filtered_nodes.append(n)
            else:
                filtered_nodes.append(n)

        dfd = self._transform_to_dfd(filtered_nodes, edges, col_map, row_map, dept)
        version = dfd["version"]
        central = dfd["central_process"]
        actors = dfd["actors"]
        sinks = dfd["dispersal_sinks"]
        storage = dfd["storage_systems"]
        flows = dfd["data_flows"]

        sinks_by_actor = {}
        for s in sinks:
            sinks_by_actor.setdefault(s.get("actor_id", ""), []).append(s)

        rows_html = ""
        for actor in actors:
            rows_html += self._render_actor_row(actor, central, sinks_by_actor, storage)

        dfd_json = json.dumps(dfd, indent=2)
        kg_json = json.dumps(kg, indent=2)
        flows_json = json.dumps(flows)
        role_map_json = json.dumps(role_map)
        dialogue_json = json.dumps(dialogue_records[:500])  # Cap for HTML size

        return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>DFD - {dept}</title><style>{self._css()}</style></head><body>
<div class="dfd-wrapper" id="dfd-wrapper">
  <div class="dfd-title-bar"><span class="dfd-main-title">Data Flow Diagram (DFD)</span><div class="header-controls"><label class="toggle-switch"><input type="checkbox" id="show-all-arrows" onchange="toggleAllArrows()"><span class="slider"></span><span class="toggle-label">Show All Arrows</span></label></div><span class="dfd-version">v {version}</span></div>
  <div class="dept-header">{dept}</div>
  <div class="col-headers"><div class="col-actor-label"></div><div class="col-header">Data Collection</div><div class="col-header">Data Processing</div><div class="col-header">Data Dispersal</div><div class="col-header col-storage">Storage</div></div>
  <div class="swimlane-body" id="swimlane-body">{rows_html}</div>
  <svg id="arrows-svg" style="position:absolute;top:0;left:0;pointer-events:none;overflow:visible"></svg>
  <script id="dfd-data" type="application/json">{dfd_json}</script>
  <script id="kg-data" type="application/json">{kg_json}</script>
</div>
<div class="edit-panel"><button class="detail-btn" onclick="toggleDetailPanel()">Details</button></div>
<div class="detail-panel" id="detail-panel"><div class="detail-header"><h3>Node Details</h3><button class="detail-close" onclick="toggleDetailPanel()">&times;</button></div><div class="detail-body" id="detail-body"><p style="color:#999;text-align:center;padding:40px">Click a node in the DFD to see details</p></div></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
<script>
var flows={flows_json};
var kgData={kg_json};
var roleMap={role_map_json};
var dialogueRecords={dialogue_json};
{self._javascript()}
</script></body></html>"""

    def _render_actor_row(self, actor, central, sinks_by_actor, storage_items):
        aid = actor.get("id", "")
        aname = actor.get("name", "")
        atype = actor.get("type", "external")
        bps = actor.get("business_processes", [])
        colors = ACTOR_COLORS.get(atype, ACTOR_COLORS["external"])
        row_sinks = sinks_by_actor.get(aid, [])

        collection_html = ""
        for bp in bps:
            sources_html = ""
            for src in bp.get("collection_sources", []):
                elems = src.get("data_elements", [])
                elem_html = "<ul>" + "".join(f"<li>{e}</li>" for e in elems) + "</ul>" if elems else ""
                safe_name = src.get('name', '').replace(' ', '_').replace("'", "")
                sources_html += f'<div class="data-source-box" data-id="src_{safe_name}"><div class="data-source-name" contenteditable="false">{src.get("name","")}</div>{elem_html}</div>'
            bp_id = bp.get('id', '').replace("'", "")
            collection_html += f'<div class="biz-process-group" data-id="{bp_id}" data-bp-name="{bp.get("name","")}"><div class="biz-process-label" contenteditable="false">{bp.get("name","")}</div>{sources_html}</div>'

        dispersal_html = ""
        for sink in row_sinks:
            color = sink.get("color", "#546e7a")
            sname = sink.get('name', '')
            icon = "🏢" if "department" in sname.lower() else "📊" if any(k in sname.lower() for k in ["salesforce","ameyo","excel"]) else "🖥️" if any(k in sname.lower() for k in ["whatsapp","vendor"]) else "➡️"
            sid = sink.get('id', '').replace("'", "")
            dispersal_html += f'<div class="sink-box" data-id="{sid}" style="--sink-color:{color};"><div class="sink-color-bar" style="background:{color};"></div><div class="sink-content"><span class="sink-icon">{icon}</span><span class="sink-name" contenteditable="false">{sname}</span></div></div>'

        central_html = f'<div class="central-process-box" id="central-process" data-id="central_process"><div class="central-label" contenteditable="false">{central}</div></div>'

        storage_html = ""
        for sys in storage_items:
            icon = "☁️" if sys.get("type") == "cloud" else "🗄️"
            safe_name = sys.get('name', '').replace(' ', '_').replace("'", "")
            storage_html += f'<div class="storage-item" data-id="st_{safe_name}"><div class="storage-icon">{icon}</div><div class="storage-name" contenteditable="false">{sys.get("name","")}</div></div>'

        return f"""<div class="swimlane-row" style="--row-bg:{colors['bg']};--row-border:{colors['border']};" data-actor-id="{aid}">
      <div class="actor-label" style="background:{colors['bg']};border-right:3px solid {colors['border']};"><div class="actor-label-text" style="color:{colors['label']};">{aname}</div></div>
      <div class="cell cell-collection" data-col="collection" data-actor="{aid}">{collection_html}</div>
      <div class="cell cell-processing" data-col="processing" data-actor="{aid}">{central_html if aid == "internal" else ""}</div>
      <div class="cell cell-dispersal" data-col="dispersal" data-actor="{aid}">{dispersal_html}</div>
      <div class="cell cell-storage" data-col="storage" data-actor="{aid}">{storage_html if aid == "internal" else ""}</div>
    </div>"""

    def _css(self):
        return """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; background: #ecf0f1; padding: 20px; }
.dfd-wrapper { position: relative; background: #fff; border-radius: 10px; box-shadow: 0 4px 24px rgba(0,0,0,0.15); overflow: visible; min-width: 900px; }
.dfd-title-bar { display: flex; justify-content: space-between; align-items: center; padding: 12px 20px; background: linear-gradient(135deg, #1a237e 0%, #283593 100%); border-bottom: 3px solid #ffcc02; }
.dfd-main-title { font-size: 18px; font-weight: 700; color: #fff; letter-spacing: 0.5px; }
.header-controls { display: flex; align-items: center; gap: 16px; }
.toggle-switch { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.toggle-switch input[type="checkbox"] { display: none; }
.slider { position: relative; width: 44px; height: 24px; background: rgba(255,255,255,0.3); border-radius: 24px; transition: background 0.3s; }
.toggle-switch input:checked + .slider { background: #4caf50; }
.slider::before { content: ''; position: absolute; width: 18px; height: 18px; left: 3px; top: 3px; background: #fff; border-radius: 50%; transition: transform 0.3s; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }
.toggle-switch input:checked + .slider::before { transform: translateX(20px); }
.toggle-label { font-size: 12px; color: #fff; font-weight: 600; white-space: nowrap; }
.dfd-version { font-size: 11px; color: #fff; border: 1px solid rgba(255,255,255,0.3); border-radius: 4px; padding: 2px 7px; background: rgba(255,255,255,0.1); }
.dept-header { background: #34495e; color: #fff; text-align: center; font-weight: 700; font-size: 15px; padding: 8px; letter-spacing: 0.5px; }
.col-headers { display: grid; grid-template-columns: 110px 1fr 180px 1fr 160px; background: #2c3e50; }
.col-actor-label { background: #1a252f; }
.col-header { color: #fff; font-weight: 600; font-size: 13px; text-align: center; padding: 9px 6px; border-left: 1px solid rgba(255,255,255,0.15); }
.col-storage { background: #1a252f; }
.swimlane-body { display: flex; flex-direction: column; }
.swimlane-row { display: grid; grid-template-columns: 110px 1fr 180px 1fr 160px; border-bottom: 1px solid #dee2e6; min-height: 140px; }
.actor-label { display: flex; align-items: center; justify-content: center; padding: 12px 6px; writing-mode: vertical-rl; text-orientation: mixed; transform: rotate(180deg); }
.actor-label-text { font-weight: 700; font-size: 13px; letter-spacing: 1px; }
.cell { padding: 12px 10px; border-left: 1px solid #dee2e6; background: var(--row-bg); }
.cell-processing { background: #eaf4fb; display: flex; align-items: center; justify-content: center; }
.cell-storage { background: #f8f9fa; display: flex; flex-direction: column; gap: 12px; align-items: center; justify-content: center; padding: 16px 8px; }
.biz-process-group { margin-bottom: 12px; background: rgba(255,255,255,0.5); border-radius: 8px; padding: 8px; border: 1px solid rgba(0,0,0,0.07); }
.biz-process-label { font-weight: 700; font-size: 12px; color: #2c3e50; margin-bottom: 7px; padding-bottom: 4px; border-bottom: 1px dashed #bdc3c7; }
.data-source-box { margin: 5px 0; background: #fff; border: 1px solid #bdc3c7; border-radius: 6px; padding: 6px 9px; font-size: 11.5px; cursor: pointer; transition: box-shadow 0.2s, border-color 0.2s, transform 0.2s; }
.data-source-box:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.1); border-color: #2980b9; }
.data-source-box.node-selected, .sink-box.node-selected, .biz-process-group.node-selected, .storage-item.node-selected, .central-process-box.node-selected { box-shadow: 0 0 0 3px #ffcc02, 0 4px 12px rgba(0,0,0,0.2); border-color: #f9a825; transform: scale(1.02); }
.data-source-name { font-weight: 600; color: #34495e; margin-bottom: 4px; }
.data-source-box ul { list-style: disc; padding-left: 16px; color: #555; }
.data-source-box ul li { font-size: 11px; margin: 1px 0; }
.central-process-box { background: #2980b9; color: #fff; border-radius: 8px; padding: 14px 16px; text-align: center; font-weight: 700; font-size: 13px; box-shadow: 0 3px 12px rgba(41,128,185,0.4); min-width: 130px; cursor: pointer; transition: box-shadow 0.2s, transform 0.2s; }
.central-label { color: #fff; }
.sink-box { display: flex; align-items: stretch; background: #fff; border-radius: 7px; margin: 6px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.10); overflow: hidden; cursor: pointer; transition: box-shadow 0.2s, transform 0.15s, border-color 0.2s; border: 1px solid rgba(0,0,0,0.08); }
.sink-box:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.18); transform: translateX(2px); }
.sink-color-bar { width: 6px; min-height: 100%; flex-shrink: 0; }
.sink-content { display: flex; align-items: center; gap: 8px; padding: 8px 10px; flex: 1; }
.sink-icon { font-size: 16px; flex-shrink: 0; }
.sink-name { font-size: 11.5px; font-weight: 600; color: #2c3e50; line-height: 1.3; }
.storage-item { display: flex; flex-direction: column; align-items: center; gap: 4px; cursor: pointer; padding: 8px; border-radius: 8px; transition: background 0.2s, transform 0.2s; }
.storage-item:hover { background: rgba(0,0,0,0.03); }
.storage-icon { font-size: 32px; }
.storage-name { font-size: 10px; text-align: center; color: #555; font-weight: 600; }
.edit-panel { position: fixed; bottom: 24px; right: 24px; display: flex; gap: 8px; z-index: 1000; }
.edit-toggle, .export-btn, .detail-btn { background: #2c3e50; color: #fff; border: none; border-radius: 24px; padding: 10px 20px; cursor: pointer; font-size: 13px; font-weight: 600; box-shadow: 0 3px 12px rgba(0,0,0,0.2); transition: background 0.2s; }
.edit-toggle:hover { background: #1a252f; }
.export-btn { background: #27ae60; }
.export-btn:hover { background: #1e8449; }
.detail-btn { background: #1565c0; }
.detail-btn:hover { background: #0d47a1; }
body.edit-mode [contenteditable] { outline: 2px dashed #e74c3c; border-radius: 3px; cursor: text; background: rgba(255,235,59,0.15); }
[contenteditable]:focus { outline: 2px solid #e74c3c !important; }
.detail-panel { position: fixed; top: 0; right: -450px; width: 430px; height: 100vh; background: rgba(255,255,255,0.97); backdrop-filter: blur(12px); box-shadow: -4px 0 20px rgba(0,0,0,0.15); z-index: 1000; transition: right 0.35s ease; display: flex; flex-direction: column; }
.detail-panel.open { right: 0; }
.detail-header { display: flex; justify-content: space-between; align-items: center; padding: 18px 20px; border-bottom: 1px solid #e0e0e0; background: #f5f5f5; }
.detail-header h3 { font-size: 16px; margin: 0; color: #1a237e; }
.detail-close { background: none; border: none; font-size: 22px; cursor: pointer; color: #757575; padding: 4px 8px; }
.detail-close:hover { color: #c62828; }
.detail-body { flex: 1; overflow-y: auto; padding: 16px; }
.detail-section { margin-bottom: 16px; }
.detail-section h4 { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 2px solid #e0e0e0; }
.detail-section h4.risks { color: #c62828; border-color: #ef9a9a; }
.detail-section h4.flows { color: #1565c0; border-color: #90caf9; }
.detail-section h4.data { color: #2e7d32; border-color: #a5d6a7; }
.detail-section h4.evidence { color: #e65100; border-color: #ffcc02; }
.risk-card { background: #fff5f5; border: 1px solid #ffcdd2; border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; }
.risk-severity { display: inline-block; font-size: 9px; font-weight: 700; padding: 2px 8px; border-radius: 4px; text-transform: uppercase; margin-right: 6px; }
.risk-severity.critical { background: #c62828; color: #fff; }
.risk-severity.high { background: #e65100; color: #fff; }
.risk-severity.medium { background: #f9a825; color: #fff; }
.risk-severity.low { background: #66bb6a; color: #fff; }
.risk-desc { font-size: 11px; color: #424242; line-height: 1.5; }
.flow-item { font-size: 11px; padding: 6px 10px; border-radius: 6px; margin-bottom: 4px; display: flex; align-items: center; gap: 6px; }
.flow-out { background: #e8f5e9; border: 1px solid #c8e6c9; }
.flow-in { background: #e3f2fd; border: 1px solid #bbdefb; }
.flow-dir { font-weight: 700; font-size: 13px; }
.data-pill { display: inline-block; font-size: 10px; padding: 2px 8px; border-radius: 12px; margin: 2px; background: #e8f5e9; color: #2e7d32; font-weight: 500; }
.evidence-quote { font-size: 11px; color: #555; font-style: italic; border-left: 3px solid #ffcc02; padding: 6px 10px; margin: 6px 0; background: #fffde7; border-radius: 0 6px 6px 0; line-height: 1.5; }
.detail-section h4.pipeline { color: #4527a0; border-color: #b39ddb; }
.detail-section h4.actors { color: #00695c; border-color: #80cbc4; }
.actor-card { background: #e0f2f1; border: 1px solid #b2dfdb; border-radius: 8px; padding: 8px 12px; margin-bottom: 6px; }
.actor-role-badge { display: inline-block; font-size: 10px; font-weight: 700; padding: 2px 10px; border-radius: 12px; background: #00897b; color: #fff; text-transform: capitalize; }
.evidence-card { background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }
.ev-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }
.ev-timestamp { display: inline-flex; align-items: center; font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 4px; background: #e3f2fd; color: #1565c0; font-family: monospace; }
.ev-speaker { display: inline-flex; align-items: center; font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 4px; background: #f3e5f5; color: #7b1fa2; }
.ev-source { display: inline-flex; align-items: center; font-size: 9px; padding: 2px 8px; border-radius: 4px; background: #fff3e0; color: #e65100; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ev-quote { font-size: 11px; color: #424242; font-style: italic; line-height: 1.5; }
#arrows-svg { position: absolute; top: 0; left: 0; pointer-events: none; overflow: visible; z-index: 10; }
@page { size: A3 landscape; margin: 10mm; }
@media print {
  * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; color-adjust: exact !important; }
  body { background: #fff !important; padding: 0 !important; margin: 0 !important; }
  .dfd-wrapper { border-radius: 0 !important; box-shadow: none !important; overflow: visible !important; min-width: 100% !important; width: 100% !important; }
  .edit-panel, .detail-panel { display: none !important; }
  #arrows-svg { display: block !important; overflow: visible !important; position: absolute !important; }
  .central-process-box { background: #2980b9 !important; color: #fff !important; }
  .dept-header, .col-header, .col-actor-label, .col-headers { background-color: #2c3e50 !important; color: #fff !important; }
  .swimlane-row, .biz-process-group, .sink-box, .data-source-box { page-break-inside: avoid; break-inside: avoid; }
}
        """

    def _javascript(self):
        return r"""
// ─── Utility: resolve speaker name to role ──────────
function speakerToRole(name) {
  if (!name) return '';
  if (roleMap && roleMap[name]) return roleMap[name];
  return name;
}
function displayName(name) {
  // Show role if available, never show person name
  if (!name) return '';
  if (roleMap && roleMap[name]) {
    var role = roleMap[name];
    return role.charAt(0).toUpperCase() + role.slice(1);
  }
  return name;
}
function escHtml(s) { var d=document.createElement('div'); d.textContent=s; return d.innerHTML; }

// ─── Arrow visibility state ───────────────────────────────
var showAllArrows = false;
var selectedNodeId = null;

function normalizeNodeId(id) {
  return (id || '').replace(/^(src_|sink_|bp_|st_)/, '');
}

function findNodeEl(id) {
  if (!id) return null;
  var el = document.querySelector('[data-id="' + id + '"]');
  if (el) return el;
  var prefixes = ['src_', 'sink_', 'bp_', 'st_'];
  for (var i = 0; i < prefixes.length; i++) {
    el = document.querySelector('[data-id="' + (prefixes[i] + id) + '"]');
    if (el) return el;
  }
  return null;
}

function toggleAllArrows() {
  showAllArrows = document.getElementById('show-all-arrows').checked;
  selectedNodeId = null;
  drawArrows();
}

function toggleDetailPanel() { var p = document.getElementById('detail-panel'); if (p) p.classList.toggle('open'); }

function exportPDF() {
  var element = document.getElementById('dfd-wrapper');

  // Temporarily show all arrows for export
  var wasShowingAll = showAllArrows;
  var wasSelected = selectedNodeId;
  showAllArrows = true;
  selectedNodeId = null;
  drawArrows();

  // Prefer html2pdf.js when available; fall back to browser print.
  try {
    if (typeof html2pdf !== 'undefined') {
      var opt = {
        margin: 10,
        filename: 'DFD_Export.pdf',
        image: { type: 'jpeg', quality: 0.98 },
        html2canvas: { scale: 2, useCORS: true, logging: false },
        jsPDF: { unit: 'mm', format: 'a3', orientation: 'landscape' }
      };
      html2pdf().set(opt).from(element).save().then(function() {
        // Restore previous state
        showAllArrows = wasShowingAll;
        selectedNodeId = wasSelected;
        drawArrows();
      }).catch(function() {
        // Fallback if html2pdf fails mid-run
        window.print();
        showAllArrows = wasShowingAll;
        selectedNodeId = wasSelected;
        drawArrows();
      });
      return;
    }
  } catch (e) {
    // ignore and fall through to print
  }

  window.print();
  // Restore previous state after print dialog
  showAllArrows = wasShowingAll;
  selectedNodeId = wasSelected;
  drawArrows();
}

// ─── Find dialogue records mentioning a node ────────
function findDialogueForNode(nodeName) {
  if (!dialogueRecords || !nodeName) return [];
  var lower = nodeName.toLowerCase();
  var matches = [];
  for (var i = 0; i < dialogueRecords.length; i++) {
    var r = dialogueRecords[i];
    if (r.text && r.text.toLowerCase().indexOf(lower) !== -1) {
      matches.push(r);
    }
    // Also check systems array
    if (r.systems) {
      for (var j = 0; j < r.systems.length; j++) {
        if (r.systems[j].toLowerCase() === lower && matches.indexOf(r) === -1) {
          matches.push(r);
        }
      }
    }
  }
  return matches;
}

// ─── Find actors (speakers) connected to a node ─────
function findConnectedActors(nodeId, nodeName) {
  var actorSet = {};
  // 1. From dialogue records mentioning this node
  var mentions = findDialogueForNode(nodeName);
  mentions.forEach(function(r) {
    if (r.speaker) {
      var role = speakerToRole(r.speaker);
      var key = r.speaker;
      if (!actorSet[key]) actorSet[key] = { name: r.speaker, role: role, mentions: 0, files: {} };
      actorSet[key].mentions++;
      if (r.source_file) actorSet[key].files[r.source_file] = true;
    }
  });
  // 2. From edge evidence_trail
  var edges = kgData.edges || [];
  edges.forEach(function(e) {
    if (e.source !== nodeId && e.target !== nodeId) return;
    (e.evidence_trail || []).forEach(function(t) {
      if (t.speaker) {
        var role = t.speaker_role || speakerToRole(t.speaker);
        var key = t.speaker;
        if (!actorSet[key]) actorSet[key] = { name: t.speaker, role: role, mentions: 0, files: {} };
        actorSet[key].mentions++;
        if (t.source_file) actorSet[key].files[t.source_file] = true;
      }
    });
  });
  return Object.values(actorSet);
}

// ─── Main detail panel renderer ─────────────────────
function showNodeDetail(nodeId) {
  var nodes = kgData.nodes || [];
  var edges = kgData.edges || [];
  var node = nodes.find(function(n) { return n.id === nodeId; });
  if (!node) return;

  var b = '';

  // ── Header ──
  b += '<h3 style="font-size:16px;font-weight:700;color:#1a237e;margin-bottom:4px">' + escHtml(node.name||nodeId) + '</h3>';
  b += '<p style="font-size:11px;color:#757575;text-transform:uppercase;margin-bottom:12px">' + escHtml((node.type||'').replace(/_/g,' ')) + '</p>';

  // ── Processing Pipeline Info ──
  b += '<div class="detail-section">';
  b += '<h4 class="pipeline">How This Was Identified</h4>';
  b += '<div style="font-size:11px;color:#555;line-height:1.6;padding:8px 10px;background:#f5f5f5;border-radius:6px;margin-bottom:8px">';
  b += '<b>1. NLP Cleaning:</b> Raw transcripts cleaned, dialogue parsed with timestamps &amp; speaker roles<br>';
  b += '<b>2. Entity Extraction:</b> Systems, actors, and data elements identified deterministically + by AI<br>';
  b += '<b>3. Flow Analysis:</b> Data flows inferred from structured transcript with evidence references<br>';
  b += '<b>4. Graph Construction:</b> Entities merged across sessions, flows canonicalized, risks attached<br>';
  b += '<b>5. Verification:</b> Pipeline output verified against source text for accuracy';
  b += '</div></div>';

  // ── Data Elements ──
  var dels = node.data_elements || [];
  if (dels.length) {
    b += '<div class="detail-section"><h4 class="data">Data Elements (' + dels.length + ')</h4><div>';
    dels.forEach(function(d){ b += '<span class="data-pill">' + escHtml(d) + '</span>'; });
    b += '</div></div>';
  }

  // ── Connected Actors (speakers who mentioned this node) ──
  var actors = findConnectedActors(nodeId, node.name);
  if (actors.length) {
    b += '<div class="detail-section"><h4 class="actors">Related People (' + actors.length + ')</h4>';
    actors.forEach(function(a) {
      var fileList = Object.keys(a.files);
      b += '<div class="actor-card">';
      b += '<span class="actor-role-badge">' + escHtml(a.role || 'unknown') + '</span>';
      b += '<span style="font-size:11px;color:#555"> &mdash; mentioned ' + a.mentions + ' time(s)</span>';
      if (fileList.length) {
        b += '<div style="font-size:10px;color:#888;margin-top:2px">Source: ' + fileList.map(escHtml).join(', ') + '</div>';
      }
      b += '</div>';
    });
    b += '</div>';
  }

  // ── Risks ──
  var risks = node.risks || [];
  if (risks.length) {
    b += '<div class="detail-section"><h4 class="risks">Risks (' + risks.length + ')</h4>';
    risks.forEach(function(r) {
      var sev = typeof r === 'object' ? (r.severity||'') : '';
      var desc = typeof r === 'string' ? r : (r.description || JSON.stringify(r));
      var src = typeof r === 'object' ? (r.source || '') : '';
      b += '<div class="risk-card">';
      if (sev) b += '<span class="risk-severity ' + sev + '">' + escHtml(sev) + '</span>';
      b += '<span class="risk-desc">' + escHtml(desc) + '</span>';
      if (src) b += '<div style="font-size:9px;color:#999;margin-top:4px">Source: ' + escHtml(src) + '</div>';
      b += '</div>';
    });
    b += '</div>';
  }

  // ── Data Flows ──
  var outE = edges.filter(function(e){ return e.source === nodeId; });
  var inE = edges.filter(function(e){ return e.target === nodeId; });
  if (outE.length || inE.length) {
    b += '<div class="detail-section"><h4 class="flows">Data Flows</h4>';
    outE.forEach(function(e) {
      var targetNode = nodes.find(function(n){ return n.id === e.target; });
      var tName = targetNode ? targetNode.name : e.target;
      b += '<div class="flow-item flow-out"><span class="flow-dir">&rarr;</span><b>' + escHtml(tName) + '</b>';
      b += ' <span style="color:#999;margin-left:4px">via ' + escHtml(e.channel||'unspecified') + ' (' + (e.data_elements||[]).length + ' elements)</span></div>';
    });
    inE.forEach(function(e) {
      var sourceNode = nodes.find(function(n){ return n.id === e.source; });
      var sName = sourceNode ? sourceNode.name : e.source;
      b += '<div class="flow-item flow-in"><span class="flow-dir">&larr;</span><b>' + escHtml(sName) + '</b>';
      b += ' <span style="color:#999;margin-left:4px">via ' + escHtml(e.channel||'unspecified') + ' (' + (e.data_elements||[]).length + ' elements)</span></div>';
    });
    b += '</div>';
  }

  // ── Evidence Trail (with timestamps, speakers, document proof) ──
  var relEdges = edges.filter(function(e){ return e.source === nodeId || e.target === nodeId; });
  var allTrail = [];
  relEdges.forEach(function(e) {
    (e.evidence_trail || []).forEach(function(t) {
      if (t.evidence) allTrail.push(t);
    });
  });
  // Also get matching dialogue records as additional evidence
  var dialogueMatches = findDialogueForNode(node.name);

  if (allTrail.length || dialogueMatches.length) {
    b += '<div class="detail-section"><h4 class="evidence">Evidence Trail &amp; Transcript Proof</h4>';

    // Show structured evidence trail from AI extraction
    if (allTrail.length) {
      b += '<div style="font-size:10px;color:#888;margin-bottom:6px;font-weight:600">From AI Analysis:</div>';
      allTrail.slice(0, 8).forEach(function(t) {
        b += '<div class="evidence-card">';
        var meta = '';
        if (t.timestamp) meta += '<span class="ev-timestamp">' + escHtml(t.timestamp) + '</span>';
        if (t.speaker) meta += '<span class="ev-speaker">' + escHtml(displayName(t.speaker)) + '</span>';
        if (t.source_file) meta += '<span class="ev-source">' + escHtml(t.source_file) + '</span>';
        if (meta) b += '<div class="ev-meta">' + meta + '</div>';
        b += '<div class="ev-quote">&ldquo;' + escHtml(t.evidence) + '&rdquo;</div>';
        b += '</div>';
      });
      if (allTrail.length > 8) b += '<p style="font-size:10px;color:#999">+' + (allTrail.length-8) + ' more from AI analysis</p>';
    }

    // Show raw dialogue matches as ground-truth proof
    if (dialogueMatches.length) {
      b += '<div style="font-size:10px;color:#888;margin:10px 0 6px;font-weight:600">From Original Transcripts:</div>';
      dialogueMatches.slice(0, 6).forEach(function(r) {
        b += '<div class="evidence-card">';
        var meta = '';
        if (r.timestamp) meta += '<span class="ev-timestamp">' + escHtml(r.timestamp) + '</span>';
        if (r.speaker) meta += '<span class="ev-speaker">' + escHtml(displayName(r.speaker)) + '</span>';
        if (r.source_file) meta += '<span class="ev-source">' + escHtml(r.source_file) + '</span>';
        if (meta) b += '<div class="ev-meta">' + meta + '</div>';
        b += '<div class="ev-quote">&ldquo;' + escHtml(r.text.length > 200 ? r.text.substring(0,200) + '...' : r.text) + '&rdquo;</div>';
        b += '</div>';
      });
      if (dialogueMatches.length > 6) b += '<p style="font-size:10px;color:#999">+' + (dialogueMatches.length-6) + ' more transcript references</p>';
    }

    b += '</div>';
  }

  // Also show plain evidence strings as fallback
  var plainEvs = [];
  relEdges.forEach(function(e) {
    (e.evidence || []).forEach(function(ev) {
      if (typeof ev === 'string' && plainEvs.indexOf(ev) === -1) plainEvs.push(ev);
    });
  });
  if (plainEvs.length && !allTrail.length) {
    b += '<div class="detail-section"><h4 class="evidence">Evidence</h4>';
    plainEvs.slice(0,8).forEach(function(ev) {
      b += '<div class="evidence-quote">&ldquo;' + escHtml(ev) + '&rdquo;</div>';
    });
    b += '</div>';
  }

  document.getElementById('detail-body').innerHTML = b;
  var panel = document.getElementById('detail-panel');
  if (panel && !panel.classList.contains('open')) panel.classList.add('open');
}

// ─── Geometry helpers ───────────────────────────────
function getBounds(el) {
  var wr = document.getElementById('dfd-wrapper');
  var wb = wr.getBoundingClientRect();
  var b = el.getBoundingClientRect();
  return { left: b.left-wb.left, right: b.right-wb.left, top: b.top-wb.top, bottom: b.bottom-wb.top, cx: b.left-wb.left+b.width/2, cy: b.top-wb.top+b.height/2, w: b.width, h: b.height };
}
function cubicBezier(x1,y1,cx1,cy1,cx2,cy2,x2,y2) { return 'M'+x1+','+y1+' C'+cx1+','+cy1+' '+cx2+','+cy2+' '+x2+','+y2; }

// ─── Arrow draw ─────────────────────────────────────
var _markers = {};
function ensureMarker(svg, id, color) {
  if (_markers[id]) return;
  _markers[id] = true;
  var ns = 'http://www.w3.org/2000/svg';
  var defs = svg.querySelector('defs');
  if (!defs) { defs = document.createElementNS(ns,'defs'); svg.prepend(defs); }
  var marker = document.createElementNS(ns,'marker');
  marker.setAttribute('id',id); marker.setAttribute('markerWidth','10'); marker.setAttribute('markerHeight','7');
  marker.setAttribute('refX','9'); marker.setAttribute('refY','3.5'); marker.setAttribute('orient','auto');
  var poly = document.createElementNS(ns,'polygon');
  poly.setAttribute('points','0 0, 10 3.5, 0 7'); poly.setAttribute('fill',color);
  marker.appendChild(poly); defs.appendChild(marker);
}

function drawPath(svg, d, color, label, lx, ly) {
  var ns = 'http://www.w3.org/2000/svg';
  var shadow = document.createElementNS(ns,'path');
  shadow.setAttribute('d',d); shadow.setAttribute('stroke','rgba(0,0,0,0.15)');
  shadow.setAttribute('stroke-width','5'); shadow.setAttribute('fill','none'); shadow.setAttribute('stroke-linecap','round');
  svg.appendChild(shadow);
  var path = document.createElementNS(ns,'path');
  path.setAttribute('d',d); path.setAttribute('stroke',color); path.setAttribute('stroke-width','2.5');
  path.setAttribute('fill','none'); path.setAttribute('stroke-linecap','round');
  var markerId = 'ah_' + color.replace('#','');
  ensureMarker(svg, markerId, color);
  path.setAttribute('marker-end','url(#'+markerId+')');
  svg.appendChild(path);
  if (label) {
    var bg = document.createElementNS(ns,'rect');
    bg.setAttribute('x',lx-2); bg.setAttribute('y',ly-10);
    bg.setAttribute('width',Math.min(label.length*5.5+4, 200)); bg.setAttribute('height',14);
    bg.setAttribute('rx','3'); bg.setAttribute('fill','rgba(255,255,255,0.88)');
    svg.appendChild(bg);
    var txt = document.createElementNS(ns,'text');
    txt.setAttribute('x',lx); txt.setAttribute('y',ly);
    txt.setAttribute('font-size','9'); txt.setAttribute('font-family','Segoe UI, Arial');
    txt.setAttribute('fill',color); txt.setAttribute('font-weight','600');
    txt.textContent = label.length > 35 ? label.substring(0,35)+'...' : label;
    svg.appendChild(txt);
  }
}

function drawArrows() {
  var wrapper = document.getElementById('dfd-wrapper');
  var svg = document.getElementById('arrows-svg');
  if (!svg || !wrapper) return;
  svg.setAttribute('width', wrapper.offsetWidth);
  svg.setAttribute('height', wrapper.offsetHeight);
  svg.innerHTML = '<defs><marker id="ah" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#555"/></marker></defs>';

  var central = document.getElementById('central-process');
  if (!central) return;
  var cp = getBounds(central);

  var inbound = flows.filter(function(f){ return f.to_id === 'central_process'; });
  var outbound = flows.filter(function(f){ return f.from_id === 'central_process'; });

  // Filter flows based on visibility mode
  if (!showAllArrows && selectedNodeId) {
    // Show only arrows connected to selected node
    var sel = normalizeNodeId(selectedNodeId);
    inbound = inbound.filter(function(f) { return normalizeNodeId(f.from_id) === sel; });
    outbound = outbound.filter(function(f) { return normalizeNodeId(f.to_id) === sel; });
  } else if (!showAllArrows && !selectedNodeId) {
    // Show a small subset by default to avoid a "blank" DFD while keeping large graphs fast
    var maxDefaultArrows = 80;
    var half = Math.floor(maxDefaultArrows / 2);
    inbound = inbound.slice(0, half);
    outbound = outbound.slice(0, half);
  }

  var inboundCount = Math.max(inbound.length, 1);
  inbound.forEach(function(flow, idx) {
    var fromEl = findNodeEl(flow.from_id);
    if (!fromEl) return;
    var f = getBounds(fromEl);
    var color = flow.color || '#546e7a';
    var fraction = (idx+1)/(inboundCount+1);
    var x2 = cp.left, y2 = cp.top + cp.h*fraction;
    var x1 = f.right, y1 = f.cy;
    var dx = (x2-x1)*0.55;
    drawPath(svg, cubicBezier(x1,y1,x1+dx,y1,x2-dx,y2,x2,y2), color, flow.label, x1+(x2-x1)*0.5, y1+(y2-y1)*0.5);
  });

  var outboundCount = Math.max(outbound.length, 1);
  outbound.forEach(function(flow, idx) {
    var toEl = findNodeEl(flow.to_id);
    if (!toEl) return;
    var t = getBounds(toEl);
    var color = flow.color || '#546e7a';
    var fraction = (idx+1)/(outboundCount+1);
    var x1 = cp.right, y1 = cp.top + cp.h*fraction;
    var x2 = t.left, y2 = t.cy;
    var dx = (x2-x1)*0.55;
    drawPath(svg, cubicBezier(x1,y1,x1+dx,y1,x2-dx,y2,x2,y2), color, flow.label, x1+(x2-x1)*0.5, y1+(y2-y1)*0.5);
  });
}

// ─── Click handlers for nodes ──────────────────────
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.data-source-box, .sink-box, .biz-process-group, .storage-item, .central-process-box').forEach(function(el) {
    el.addEventListener('click', function() {
      var dataId = el.getAttribute('data-id') || '';
      var nodeId = dataId.replace(/^(src_|sink_|bp_|st_)/, '');
      
      // Highlight selected node and show its arrows
      document.querySelectorAll('.data-source-box, .sink-box, .biz-process-group, .storage-item, .central-process-box').forEach(function(n) {
        n.classList.remove('node-selected');
      });
      el.classList.add('node-selected');
      
      selectedNodeId = nodeId;
      if (!showAllArrows) {
        drawArrows();
      }
      
      showNodeDetail(nodeId);
    });
  });
});

// ─── Init ───────────────────────────────────────────
window.addEventListener('load', function() {
  requestAnimationFrame(function() { setTimeout(drawArrows, 600); });
  window.addEventListener('resize', function() { _markers = {}; requestAnimationFrame(function() { setTimeout(drawArrows, 50); }); });
});
window.addEventListener('beforeprint', function() { _markers = {}; drawArrows(); });
window.addEventListener('afterprint', function() { _markers = {}; setTimeout(drawArrows, 100); });
"""
