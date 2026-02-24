"""
DFD HTML Renderer
Converts a validated DFD JSON object into a professional interactive HTML file
that exactly matches the reference image style:

Visual structure:
┌──────────────────────────────────────────────────────────────────────────────┐
│ Data Flow Diagram (DFD)     [Department Name]             v1.0               │
├────────────────┬────────────────────┬────────────────────┬────────────────────┤
│ Actors         │ DATA COLLECTION    │ DATA PROCESSING    │ DATA DISPERSAL   │ STORAGE │
├────────────────┼────────────────────┼────────────────────┼────────────────────┤
│ Customers      │ [biz processes +   │                    │ [sink boxes]     │ [icons] │
│                │  data sources]     │  [central process] │                  │         │
├────────────────┼────────────────────┼────────────────────┼────────────────────┤
│ Internal Depts │ [biz processes]    │                    │ [sink boxes]     │ [icons] │
├────────────────┼────────────────────┼────────────────────┼────────────────────┤
│ Vendors        │                    │                    │ [sink boxes]     │ [icons] │
└────────────────┴────────────────────┴────────────────────┴────────────────────┘

SVG arrows are drawn in JavaScript after DOM layout.
All text nodes are contenteditable for in-browser editing.
"""

import json
from typing import Any, Dict


# Color palette matching reference image
ACTOR_COLORS = {
    "external": {"bg": "#fffde7", "border": "#f9a825", "label": "#f57f17"},
    "internal": {"bg": "#fce4ec", "border": "#e91e63", "label": "#880e4f"},
    "vendor":   {"bg": "#f1f8e9", "border": "#7cb342", "label": "#33691e"},
}

COLUMN_HEADER_BG = "#2c3e50"
COLUMN_HEADER_FG = "#ffffff"
DEPT_HEADER_BG = "#34495e"


class DFDHTMLRenderer:

    def render(self, dfd: Dict[str, Any]) -> str:
        """Render a DFD JSON object to a complete HTML string."""
        dept = dfd.get("department", "Department")
        version = dfd.get("version", "1.0")
        central = dfd.get("central_process", "Central Process")
        actors = dfd.get("actors", [])
        sinks = dfd.get("dispersal_sinks", [])
        storage = dfd.get("storage_systems", [])
        flows = dfd.get("data_flows", [])
        citations = dfd.get("citations", [])
        dfd_json = json.dumps(dfd, indent=2)

        # Group sinks by actor_id
        sinks_by_actor: Dict[str, list] = {}
        for s in sinks:
            aid = s.get("actor_id", "")
            sinks_by_actor.setdefault(aid, []).append(s)

        # Group storage by actor_id (if not provided just distribute)
        storage_items = storage  # render all on the right

        rows_html = ""
        for actor in actors:
            rows_html += self._render_actor_row(actor, central, sinks_by_actor, storage_items)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>DFD - {dept}</title>
<style>
{self._css()}
</style>
</head>
<body>

<div class="dfd-wrapper" id="dfd-wrapper">

  <!-- Top title bar -->
  <div class="dfd-title-bar">
    <span class="dfd-main-title">Data Flow Diagram (DFD)</span>
    <span class="dfd-version">v {version}</span>
  </div>

  <!-- Department header -->
  <div class="dept-header">{dept}</div>

  <!-- Column headers -->
  <div class="col-headers">
    <div class="col-actor-label"></div>
    <div class="col-header">Data Collection</div>
    <div class="col-header">Data Processing</div>
    <div class="col-header">Data Dispersal</div>
    <div class="col-header col-storage">Storage</div>
  </div>

  <!-- Swimlane rows -->
  <div class="swimlane-body" id="swimlane-body">
    {rows_html}
  </div>

  <!-- SVG overlay for arrows -->
  <svg id="arrows-svg" style="position:absolute;top:0;left:0;pointer-events:none;overflow:visible"></svg>

  <!-- Data flows definition (used by JS) -->
  <script id="dfd-data" type="application/json">
  {dfd_json}
  </script>

</div>

<!-- Edit panel -->
<div class="edit-panel" id="edit-panel">
  <button class="edit-toggle" onclick="toggleEdit()">
    <span id="edit-icon">✏️</span> Edit Mode
  </button>
  <button class="export-btn" onclick="exportPNG()">📥 Export PNG</button>
  <button class="cite-btn" onclick="toggleCitations()">
    📋 Sources <span class="cite-count">{len(citations)}</span>
  </button>
</div>

<!-- Citation Panel -->
<div class="citation-panel" id="citation-panel">
  <div class="citation-header">
    <h3>📋 Source Citations ({len(citations)})</h3>
    <button class="citation-close" onclick="toggleCitations()">✕</button>
  </div>
  <div class="citation-list">
    {self._render_citations(citations)}
  </div>
</div>

<script>
{self._javascript(flows)}
</script>
</body>
</html>"""

    # ─────────────────────────────────────────────────
    def _render_actor_row(self, actor, central, sinks_by_actor, storage_items):
        aid = actor.get("id", "")
        aname = actor.get("name", "")
        atype = actor.get("type", "external")
        bps = actor.get("business_processes", [])
        colors = ACTOR_COLORS.get(atype, ACTOR_COLORS["external"])
        row_sinks = sinks_by_actor.get(aid, [])

        # ── Data Collection cell ──
        collection_html = ""
        for bp in bps:
            sources = bp.get("collection_sources", [])
            sources_html = ""
            for src in sources:
                elems = src.get("data_elements", [])
                elem_list = "".join(f"<li>{e}</li>" for e in elems)
                elem_html = f"<ul>{elem_list}</ul>" if elem_list else ""
                sources_html += f"""
                <div class="data-source-box" data-id="src_{src.get('name','').replace(' ','_')}">
                  <div class="data-source-name" contenteditable="false">{src.get('name','')}</div>
                  {elem_html}
                </div>"""
            collection_html += f"""
            <div class="biz-process-group" data-id="{bp.get('id','""')}"
                 data-bp-name="{bp.get('name','')}">
              <div class="biz-process-label" contenteditable="false">{bp.get('name','')}</div>
              {sources_html}
            </div>"""

        # ── Data Dispersal cell ──
        dispersal_html = ""
        for sink in row_sinks:
            color = sink.get("color", "#546e7a")
            sink_name = sink.get('name', '')
            # Determine a short icon based on sink type name
            icon = "🏢" if "department" in sink_name.lower() or "dept" in sink_name.lower() else \
                   "📲" if "reminder" in sink_name.lower() or "payment" in sink_name.lower() else \
                   "🖥️" if any(k in sink_name.lower() for k in ["kalyera","exotel","vendor","partner"]) else "➡️"
            dispersal_html += f"""
            <div class="sink-box" data-id="{sink.get('id','')}"
                 style="--sink-color:{color};">
              <div class="sink-color-bar" style="background:{color};"></div>
              <div class="sink-content">
                <span class="sink-icon">{icon}</span>
                <span class="sink-name" contenteditable="false">{sink_name}</span>
              </div>
            </div>"""

        # For the Processing column: only show central process in the FIRST actor row
        is_first = (actor == actor)  # always render but use CSS to handle visual
        central_html = f"""
            <div class="central-process-box" id="central-process" data-id="central_process">
              <div class="central-label" contenteditable="false">{central}</div>
            </div>"""

        # ── Storage cell ──
        storage_html = ""
        for sys in storage_items:
            stype = sys.get("type", "cloud")
            icon = "☁️" if stype == "cloud" else "🗄️"
            storage_html += f"""
            <div class="storage-item" data-id="st_{sys.get('name','').replace(' ','_')}">
              <div class="storage-icon">{icon}</div>
              <div class="storage-name" contenteditable="false">{sys.get('name','')}</div>
            </div>"""

        return f"""
    <div class="swimlane-row" style="--row-bg:{colors['bg']};--row-border:{colors['border']};"
         data-actor-id="{aid}">
      <!-- Actor label -->
      <div class="actor-label" style="background:{colors['bg']};border-right:3px solid {colors['border']};">
        <div class="actor-label-text" style="color:{colors['label']};">{aname}</div>
      </div>
      <!-- Data Collection -->
      <div class="cell cell-collection" data-col="collection" data-actor="{aid}">
        {collection_html}
      </div>
      <!-- Data Processing (central process only in internal row) -->
      <div class="cell cell-processing" data-col="processing" data-actor="{aid}">
        {central_html if aid == "internal" else ""}
      </div>
      <!-- Data Dispersal -->
      <div class="cell cell-dispersal" data-col="dispersal" data-actor="{aid}">
        {dispersal_html}
      </div>
      <!-- Storage (show items only in internal row; all rows get the cell to maintain grid) -->
      <div class="cell cell-storage" data-col="storage" data-actor="{aid}">
        {storage_html if aid == "internal" else ""}
      </div>
    </div>"""

    # ─────────────────────────────────────────────────
    def _render_citations(self, citations):
        """Render citations as HTML cards for the citation panel."""
        if not citations:
            return '<div class="no-citations">No source citations available.</div>'

        html = ""
        for i, cite in enumerate(citations, 1):
            source_type = cite.get("source_type", "unknown")
            badge_class = "badge-docx" if source_type == "docx_table" else "badge-inferred"
            badge_label = "📄 Document" if source_type == "docx_table" else "🔍 Inferred"
            # Escape HTML in source text
            source_text = cite.get("source_text", "").replace("<", "&lt;").replace(">", "&gt;")
            element_name = cite.get("element_name", "").replace("<", "&lt;").replace(">", "&gt;")
            section = cite.get("source_section", "").replace("<", "&lt;").replace(">", "&gt;")

            html += f"""
            <div class="citation-card" data-cite-id="{cite.get('element_id', '')}">
              <div class="citation-num">{i}</div>
              <div class="citation-body">
                <div class="citation-element">{element_name}</div>
                <div class="citation-section">{section}</div>
                <blockquote class="citation-quote">&ldquo;{source_text}&rdquo;</blockquote>
                <span class="citation-badge {badge_class}">{badge_label}</span>
              </div>
            </div>"""
        return html

    # ─────────────────────────────────────────────────
    def _css(self):
        return """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', Arial, sans-serif; background: #ecf0f1; padding: 20px; }

.dfd-wrapper {
  position: relative;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.15);
  overflow: visible;   /* must NOT be hidden — SVG arrows need to overflow */
  min-width: 900px;
}

/* ── Title bar ── */
.dfd-title-bar {
  background: #fff;
  padding: 14px 24px 6px;
  display: flex;
  align-items: center;
  gap: 16px;
  border-bottom: 1px solid #eee;
}
.dfd-main-title {
  font-size: 20px;
  font-weight: 700;
  color: #2c3e50;
}
.dfd-version {
  font-size: 11px;
  color: #7f8c8d;
  border: 1px solid #bdc3c7;
  border-radius: 4px;
  padding: 2px 7px;
}

/* ── Department header ── */
.dept-header {
  background: #34495e;
  color: #fff;
  text-align: center;
  font-weight: 700;
  font-size: 15px;
  padding: 8px;
  letter-spacing: 0.5px;
}

/* ── Column headers ── */
.col-headers {
  display: grid;
  grid-template-columns: 110px 1fr 180px 1fr 160px;
  background: #2c3e50;
}
.col-actor-label { background: #1a252f; }
.col-header {
  color: #fff;
  font-weight: 600;
  font-size: 13px;
  text-align: center;
  padding: 9px 6px;
  border-left: 1px solid rgba(255,255,255,0.15);
}
.col-storage { background: #1a252f; }

/* ── Swimlane rows ── */
.swimlane-body { display: flex; flex-direction: column; }
.swimlane-row {
  display: grid;
  grid-template-columns: 110px 1fr 180px 1fr 160px;
  border-bottom: 1px solid #dee2e6;
  min-height: 140px;
}

/* ── Actor label ── */
.actor-label {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px 6px;
  writing-mode: vertical-rl;
  text-orientation: mixed;
  transform: rotate(180deg);
}
.actor-label-text {
  font-weight: 700;
  font-size: 13px;
  letter-spacing: 1px;
}

/* ── Cells ── */
.cell {
  padding: 12px 10px;
  border-left: 1px solid #dee2e6;
  background: var(--row-bg);
}
.cell-processing {
  background: #eaf4fb;
  display: flex;
  align-items: center;
  justify-content: center;
}
.cell-storage {
  background: #f8f9fa;
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: center;
  justify-content: center;
  padding: 16px 8px;
}

/* ── Business process groups ── */
.biz-process-group {
  margin-bottom: 12px;
  background: rgba(255,255,255,0.5);
  border-radius: 8px;
  padding: 8px;
  border: 1px solid rgba(0,0,0,0.07);
}
.biz-process-label {
  font-weight: 700;
  font-size: 12px;
  color: #2c3e50;
  margin-bottom: 7px;
  padding-bottom: 4px;
  border-bottom: 1px dashed #bdc3c7;
}

/* ── Data source boxes ── */
.data-source-box {
  margin: 5px 0;
  background: #fff;
  border: 1px solid #bdc3c7;
  border-radius: 6px;
  padding: 6px 9px;
  font-size: 11.5px;
}
.data-source-name {
  font-weight: 600;
  color: #34495e;
  margin-bottom: 4px;
}
.data-source-box ul {
  list-style: disc;
  padding-left: 16px;
  color: #555;
}
.data-source-box ul li { font-size: 11px; margin: 1px 0; }

/* ── Central process box ── */
.central-process-box {
  background: #2980b9;
  color: #fff;
  border-radius: 8px;
  padding: 14px 16px;
  text-align: center;
  font-weight: 700;
  font-size: 13px;
  box-shadow: 0 3px 12px rgba(41,128,185,0.4);
  min-width: 130px;
}
.central-label { color: #fff; }

/* ── Sink / Dispersal boxes ── */
.sink-box {
  display: flex;
  align-items: stretch;
  background: #fff;
  border-radius: 7px;
  margin: 6px 0;
  box-shadow: 0 2px 8px rgba(0,0,0,0.10);
  overflow: hidden;
  cursor: pointer;
  transition: box-shadow 0.2s, transform 0.15s;
  border: 1px solid rgba(0,0,0,0.08);
}
.sink-box:hover {
  box-shadow: 0 4px 16px rgba(0,0,0,0.18);
  transform: translateX(2px);
}
.sink-color-bar {
  width: 6px;
  min-height: 100%;
  flex-shrink: 0;
}
.sink-content {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  flex: 1;
}
.sink-icon {
  font-size: 16px;
  flex-shrink: 0;
}
.sink-name {
  font-size: 11.5px;
  font-weight: 600;
  color: #2c3e50;
  line-height: 1.3;
}

/* ── Storage items ── */
.storage-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.storage-icon { font-size: 32px; }
.storage-name {
  font-size: 10px;
  text-align: center;
  color: #555;
  font-weight: 600;
}

/* ── Edit controls ── */
.edit-panel {
  position: fixed;
  bottom: 24px;
  right: 24px;
  display: flex;
  gap: 8px;
  z-index: 1000;
}
.edit-toggle, .export-btn {
  background: #2c3e50;
  color: #fff;
  border: none;
  border-radius: 24px;
  padding: 10px 20px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  box-shadow: 0 3px 12px rgba(0,0,0,0.2);
  transition: background 0.2s;
}
.edit-toggle:hover { background: #1a252f; }
.export-btn { background: #27ae60; }
.export-btn:hover { background: #1e8449; }

/* ── Edit mode ── */
body.edit-mode [contenteditable] {
  outline: 2px dashed #e74c3c;
  border-radius: 3px;
  cursor: text;
  background: rgba(255,235,59,0.15);
}
[contenteditable]:focus { outline: 2px solid #e74c3c !important; }

/* ── Citation Panel ── */
.cite-btn {
  background: #1565c0; color: #fff; border: none;
  padding: 6px 14px; border-radius: 8px; cursor: pointer;
  font-size: 13px; display: inline-flex; align-items: center; gap: 6px;
}
.cite-btn:hover { background: #0d47a1; }
.cite-count {
  background: #fff; color: #1565c0; border-radius: 50%;
  padding: 1px 7px; font-weight: 700; font-size: 11px;
}
.citation-panel {
  position: fixed; top: 0; right: -420px; width: 400px; height: 100vh;
  background: rgba(255,255,255,0.97); backdrop-filter: blur(12px);
  box-shadow: -4px 0 20px rgba(0,0,0,0.15);
  z-index: 1000; transition: right 0.35s ease;
  display: flex; flex-direction: column;
}
.citation-panel.open { right: 0; }
.citation-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 18px 20px; border-bottom: 1px solid #e0e0e0;
  background: #f5f5f5;
}
.citation-header h3 { font-size: 16px; margin: 0; color: #1a237e; }
.citation-close {
  background: none; border: none; font-size: 22px;
  cursor: pointer; color: #757575; padding: 4px 8px;
}
.citation-close:hover { color: #c62828; }
.citation-list {
  flex: 1; overflow-y: auto; padding: 16px;
}
.citation-card {
  display: flex; gap: 12px; padding: 14px;
  border: 1px solid #e8e8e8; border-radius: 10px;
  margin-bottom: 12px; background: #fafafa;
  transition: all 0.2s;
}
.citation-card:hover {
  border-color: #90caf9; background: #e3f2fd;
  box-shadow: 0 2px 8px rgba(21,101,192,0.1);
}
.citation-num {
  font-size: 13px; font-weight: 700; color: #fff;
  background: #1565c0; border-radius: 50%;
  min-width: 26px; height: 26px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.citation-body { flex: 1; min-width: 0; }
.citation-element {
  font-weight: 700; font-size: 14px; color: #1a237e;
  margin-bottom: 4px;
}
.citation-section {
  font-size: 11px; color: #757575; margin-bottom: 6px;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.citation-quote {
  font-size: 12px; color: #424242; font-style: italic;
  border-left: 3px solid #90caf9; padding: 6px 10px;
  margin: 6px 0; background: #fff; border-radius: 0 6px 6px 0;
  line-height: 1.5;
}
.citation-badge {
  display: inline-block; font-size: 10px; padding: 2px 8px;
  border-radius: 4px; margin-top: 6px; font-weight: 600;
}
.badge-docx { background: #e8f5e9; color: #2e7d32; }
.badge-inferred { background: #fff3e0; color: #e65100; }
.no-citations {
  text-align: center; color: #bdbdbd; padding: 40px;
  font-size: 14px;
}

/* ── Arrow SVG ── */
#arrows-svg {
  position: absolute;
  top: 0; left: 0;
  pointer-events: none;
  overflow: visible;
  z-index: 10;
}

/* ────────────────────────
   PRINT / PDF STYLES
   ──────────────────────── */
@page {
  size: A3 landscape;
  margin: 10mm;
}

@media print {
  /* Force all background colors and images to print */
  * {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
    color-adjust: exact !important;
  }

  /* Reset page chrome */
  body {
    background: #fff !important;
    padding: 0 !important;
    margin: 0 !important;
  }

  /* Wrapper fills the page, no shadow, no clip */
  .dfd-wrapper {
    border-radius: 0 !important;
    box-shadow: none !important;
    overflow: visible !important;
    min-width: 100% !important;
    width: 100% !important;
  }

  /* Hide browser/screen-only UI */
  .edit-panel { display: none !important; }
  .citation-panel { display: none !important; }

  /* SVG arrows: keep visible in print — beforeprint JS redraws them
     at the correct print-layout positions */
  #arrows-svg {
    display: block !important;
    overflow: visible !important;
    position: absolute !important;
    top: 0 !important; left: 0 !important;
  }


  /* Ensure swimlane colors stay intact */
  .swimlane-row,
  .actor-label,
  .cell,
  .cell-collection,
  .cell-processing,
  .cell-dispersal,
  .cell-storage {
    background-color: var(--row-bg, #fff) !important;
  }

  /* Central process box keeps its blue */
  .central-process-box {
    background: #2980b9 !important;
    color: #fff !important;
  }

  /* Sink boxes keep their left color bars */
  .sink-color-bar {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }

  /* Keep department / column headers dark */
  .dept-header,
  .col-header,
  .col-actor-label,
  .col-headers {
    background-color: #2c3e50 !important;
    color: #fff !important;
  }

  /* Prevent page break inside rows/cells */
  .swimlane-row,
  .biz-process-group,
  .sink-box,
  .data-source-box {
    page-break-inside: avoid;
    break-inside: avoid;
  }

  /* Ensure text is black (legible on white paper) */
  .biz-process-label,
  .data-source-name,
  .sink-name,
  .storage-name,
  .actor-label-text { color: inherit !important; }
}
        """

    # ─────────────────────────────────────────────────
    def _javascript(self, flows):
        flows_json = json.dumps(flows)
        static_js = r"""
const flows = __FLOWS_JSON__;

// ─── Edit mode toggle ───────────────────────────────
let editMode = false;
function toggleEdit() {
  editMode = !editMode;
  document.body.classList.toggle('edit-mode', editMode);
  document.querySelectorAll('[contenteditable]')
    .forEach(function(el) { el.setAttribute('contenteditable', editMode); });
  var icon = document.getElementById('edit-icon');
  if (icon) icon.textContent = editMode ? 'Save' : 'Edit';
}

// ─── Citation panel toggle ──────────────────────────
function toggleCitations() {
  var panel = document.getElementById('citation-panel');
  if (panel) panel.classList.toggle('open');
}

// ─── Geometry helpers ───────────────────────────────
function getBounds(el) {
  var wr = document.getElementById('dfd-wrapper');
  var wb = wr.getBoundingClientRect();
  var b  = el.getBoundingClientRect();
  return {
    left:   b.left   - wb.left,
    right:  b.right  - wb.left,
    top:    b.top    - wb.top,
    bottom: b.bottom - wb.top,
    cx:     b.left   - wb.left + b.width  / 2,
    cy:     b.top    - wb.top  + b.height / 2,
    w:      b.width,
    h:      b.height
  };
}

function cubicBezier(x1, y1, cx1, cy1, cx2, cy2, x2, y2) {
  return 'M' + x1 + ',' + y1 +
    ' C' + cx1 + ',' + cy1 +
    ' ' + cx2 + ',' + cy2 +
    ' ' + x2 + ',' + y2;
}

// ─── Main arrow draw function ────────────────────────
function drawArrows() {
  var wrapper = document.getElementById('dfd-wrapper');
  var svg = document.getElementById('arrows-svg');
  if (!svg || !wrapper) return;

  // Match SVG size to wrapper
  svg.setAttribute('width',  wrapper.offsetWidth);
  svg.setAttribute('height', wrapper.offsetHeight);

  // Clear and add arrowhead marker
  svg.innerHTML = '' +
    '<defs>' +
      '<marker id="ah" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">' +
        '<polygon points="0 0, 10 3.5, 0 7" fill="var(--ah-color, #555)"/>' +
      '</marker>' +
      '<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">' +
        '<feDropShadow dx="0" dy="1" stdDeviation="1" flood-opacity="0.18"/>' +
      '</filter>' +
    '</defs>';

  var central = document.getElementById('central-process');
  if (!central) { console.warn('[DFD] central-process element not found'); return; }
  var cp = getBounds(central);

  // Separate inbound (→ central) and outbound (central →) flows
  var inbound  = flows.filter(function(f) { return f.to_id   === 'central_process'; });
  var outbound = flows.filter(function(f) { return f.from_id === 'central_process'; });

  // Inbound: distribute entry points evenly on the LEFT edge of central process box
  var inboundCount = Math.max(inbound.length, 1);
  inbound.forEach(function(flow, idx) {
    var fromEl = document.querySelector('[data-id="' + flow.from_id + '"]');
    if (!fromEl) { console.warn('[DFD] Source not found:', flow.from_id); return; }
    var f = getBounds(fromEl);
    var color = flow.color || '#546e7a';

    // Fan entry points across the left edge
    var fraction = (idx + 1) / (inboundCount + 1);
    var x2 = cp.left;
    var y2 = cp.top + cp.h * fraction;

    // Exit from the right edge of the source box
    var x1 = f.right;
    var y1 = f.cy;

    // Control points for smooth S-curve
    var dx = (x2 - x1) * 0.55;
    var path = cubicBezier(x1, y1, x1 + dx, y1, x2 - dx, y2, x2, y2);

    drawPath(svg, path, color, flow.label, x1 + (x2-x1)*0.5, y1 + (y2-y1)*0.5);
  });

  // Outbound: distribute exit points evenly on the RIGHT edge of central process box
  var outboundCount = Math.max(outbound.length, 1);
  outbound.forEach(function(flow, idx) {
    var toEl = document.querySelector('[data-id="' + flow.to_id + '"]');
    if (!toEl) { console.warn('[DFD] Sink not found:', flow.to_id); return; }
    var t = getBounds(toEl);
    var color = flow.color || '#546e7a';

    // Fan exit points across the right edge
    var fraction = (idx + 1) / (outboundCount + 1);
    var x1 = cp.right;
    var y1 = cp.top + cp.h * fraction;

    // Enter the left edge of the sink box
    var x2 = t.left;
    var y2 = t.cy;

    var dx = (x2 - x1) * 0.55;
    var path = cubicBezier(x1, y1, x1 + dx, y1, x2 - dx, y2, x2, y2);

    drawPath(svg, path, color, flow.label, x1 + (x2-x1)*0.5, y1 + (y2-y1)*0.5);
  });
}

function drawPath(svg, d, color, label, lx, ly) {
  var ns = 'http://www.w3.org/2000/svg';

  // Shadow path (slightly offset, translucent)
  var shadow = document.createElementNS(ns, 'path');
  shadow.setAttribute('d', d);
  shadow.setAttribute('stroke', 'rgba(0,0,0,0.15)');
  shadow.setAttribute('stroke-width', '5');
  shadow.setAttribute('fill', 'none');
  shadow.setAttribute('stroke-linecap', 'round');
  svg.appendChild(shadow);

  // Colored arrow path
  var path = document.createElementNS(ns, 'path');
  path.setAttribute('d', d);
  path.setAttribute('stroke', color);
  path.setAttribute('stroke-width', '2.5');
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke-linecap', 'round');
  // Inline arrowhead using a separate marker for each color
  var markerId = 'ah_' + color.replace('#','');
  ensureMarker(svg, markerId, color);
  path.setAttribute('marker-end', 'url(#' + markerId + ')');
  svg.appendChild(path);

  // Flow label (if provided)
  if (label) {
    var bg = document.createElementNS(ns, 'rect');
    bg.setAttribute('x', lx - 2);
    bg.setAttribute('y', ly - 10);
    bg.setAttribute('width', label.length * 6 + 4);
    bg.setAttribute('height', 14);
    bg.setAttribute('rx', '3');
    bg.setAttribute('fill', 'rgba(255,255,255,0.88)');
    svg.appendChild(bg);

    var txt = document.createElementNS(ns, 'text');
    txt.setAttribute('x', lx);
    txt.setAttribute('y', ly);
    txt.setAttribute('font-size', '9');
    txt.setAttribute('font-family', 'Segoe UI, Arial, sans-serif');
    txt.setAttribute('fill', color);
    txt.setAttribute('font-weight', '600');
    txt.textContent = label;
    svg.appendChild(txt);
  }
}

// Create a per-color arrowhead marker (so colors match exactly)
var _markers = {};
function ensureMarker(svg, id, color) {
  if (_markers[id]) return;
  _markers[id] = true;
  var ns = 'http://www.w3.org/2000/svg';
  var defs = svg.querySelector('defs');
  if (!defs) { defs = document.createElementNS(ns, 'defs'); svg.prepend(defs); }
  var marker = document.createElementNS(ns, 'marker');
  marker.setAttribute('id', id);
  marker.setAttribute('markerWidth', '10');
  marker.setAttribute('markerHeight', '7');
  marker.setAttribute('refX', '9');
  marker.setAttribute('refY', '3.5');
  marker.setAttribute('orient', 'auto');
  var poly = document.createElementNS(ns, 'polygon');
  poly.setAttribute('points', '0 0, 10 3.5, 0 7');
  poly.setAttribute('fill', color);
  marker.appendChild(poly);
  defs.appendChild(marker);
}

// ─── Export PNG ─────────────────────────────────────
function exportPNG() {
  alert('To save:\n1. File > Print > Save as PDF\n2. Or use browser screenshot tools');
}

// ─── Init ───────────────────────────────────────────
window.addEventListener('load', function() {
  requestAnimationFrame(function() {
    setTimeout(function() {
      drawArrows();
    }, 600);
  });
  window.addEventListener('resize', function() {
    _markers = {};
    requestAnimationFrame(function() { setTimeout(drawArrows, 50); });
  });
});

// ─── Print support: redraw arrows at print-layout positions ─────
// beforeprint fires AFTER the browser has applied @media print CSS,
// so element getBoundingClientRect() returns print-layout positions.
function redrawForPrint() {
  _markers = {};       // reset per-color arrowhead markers
  drawArrows();        // re-measure and redraw at print positions
}

window.addEventListener('beforeprint', redrawForPrint);

// Restore screen arrows after printing
window.addEventListener('afterprint', function() {
  _markers = {};
  setTimeout(drawArrows, 100); // small delay to let screen CSS reapply
});

// Safari fallback (uses matchMedia instead of beforeprint)
if (window.matchMedia) {
  var printMQ = window.matchMedia('print');
  if (printMQ.addEventListener) {
    printMQ.addEventListener('change', function(mq) {
      _markers = {};
      setTimeout(drawArrows, 150);
    });
  } else if (printMQ.addListener) {
    printMQ.addListener(function() {
      _markers = {};
      setTimeout(drawArrows, 150);
    });
  }
}
"""
        return static_js.replace("__FLOWS_JSON__", flows_json)


