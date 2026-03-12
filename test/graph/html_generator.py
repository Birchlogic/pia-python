"""
HTML Generator Agent — Deterministic client-side template that
generates a full interactive DFD dashboard from JSON data.

Uses the dfd_render_plan.json levels for correct column placement
and knowledge_graph.json node types for row assignment.
"""
import json
from pathlib import Path
from utils.logger import setup_logger

logger = setup_logger("HTMLGenerator")

# ─── Material Icon mapping by node type ────────────────────────
ICON_MAP = {
    "actor": "person",
    "system": "dns",
    "data_store": "storage",
    "process": "settings",
    "unknown": "help_outline",
}

# ─── Color theme by node type ─────────────────────────────────
COLOR = {
    "actor":      {"border": "#3b82f6", "bg": "#eff6ff", "bg2": "#dbeafe", "icon": "#2563eb", "badge_bg": "#dbeafe", "badge_tx": "#1d4ed8"},
    "system":     {"border": "#22c55e", "bg": "#f0fdf4", "bg2": "#dcfce7", "icon": "#16a34a", "badge_bg": "#dcfce7", "badge_tx": "#15803d"},
    "data_store": {"border": "#a855f7", "bg": "#faf5ff", "bg2": "#f3e8ff", "icon": "#9333ea", "badge_bg": "#f3e8ff", "badge_tx": "#7e22ce"},
    "unknown":    {"border": "#6b7280", "bg": "#f9fafb", "bg2": "#f3f4f6", "icon": "#4b5563", "badge_bg": "#f3f4f6", "badge_tx": "#374151"},
}

# ─── Arrow color by flow_type ─────────────────────────────────
FLOW_COLORS = {
    "collection": "#ef4444", "transfer": "#3b82f6",
    "processing": "#22c55e", "storage": "#a855f7", "dispersal": "#f97316",
}

# ─── Column / Row definitions ─────────────────────────────────
COLUMNS = ["Collection", "Processing", "Dispersal", "Storage"]
COL_COLORS = ["#dbeafe", "#dcfce7", "#ffedd5", "#f3e8ff"]
COL_ICONS  = ["📥", "⚙️", "📤", "💾"]

ROWS = [
    ("External Entities", "#fce7f3", "#be185d"),
    ("Internal Processes", "#ccfbf1", "#0f766e"),
    ("Data Stores",        "#fef9c3", "#a16207"),
]


class HTMLGeneratorAgent:
    """Generates a self-contained HTML DFD dashboard from JSON data."""

    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}

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

        # Build placement map: node_id → column index
        col_map = self._build_column_map(nodes, levels, kg)
        # Build row map: node_id → row index
        row_map = self._build_row_map(nodes)

        logger.info(f"Building HTML: {len(nodes)} nodes, {len(edges)} edges")

        html = self._build_html(nodes, edges, kg, pipeline_docs, col_map, row_map)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info(f"✅ HTML written to {output_path} ({len(html)} chars)")
        return str(output_path)

    # ─── Intelligent column placement using render plan levels ──
    def _build_column_map(self, nodes, levels, kg):
        """Map each node to a column (0=Collection, 1=Processing, 2=Dispersal, 3=Storage)."""
        col_map = {}
        name_to_id = {n["name"]: n["id"] for n in nodes}
        id_to_type = {n["id"]: n.get("type", "unknown") for n in nodes}

        # Build level lookup: name → level_index
        level_lookup = {}
        for i, level_names in enumerate(levels):
            for name in level_names:
                level_lookup[name] = i

        max_level = max(level_lookup.values()) if level_lookup else 0

        for node in nodes:
            nid = node["id"]
            ntype = node.get("type", "unknown")

            # Data stores ALWAYS go to Storage column
            if ntype == "data_store":
                col_map[nid] = 3
                continue

            # Use render plan level to determine column
            level = level_lookup.get(node["name"])
            if level is not None:
                if max_level <= 3:
                    col_map[nid] = level
                else:
                    # Map 6 levels → 4 columns
                    # Level 0 → Collection
                    # Level 1-2 → Processing
                    # Level 3-4 → Dispersal
                    # Level 5 → Dispersal (overflow)
                    if level == 0:
                        col_map[nid] = 0  # Collection
                    elif level <= 2:
                        col_map[nid] = 1  # Processing
                    else:
                        col_map[nid] = 2  # Dispersal
            else:
                col_map[nid] = 1  # Default to Processing

        return col_map

    def _build_row_map(self, nodes):
        """Map each node to a row (0=External, 1=Internal, 2=Data Stores)."""
        row_map = {}
        for node in nodes:
            nid = node["id"]
            ntype = node.get("type", "unknown")

            if ntype == "data_store":
                row_map[nid] = 2
            elif ntype == "system":
                row_map[nid] = 1  # Systems are internal
            elif ntype == "actor":
                # Actors can be external (customer-facing) or internal (staff)
                # Use heuristic: if name suggests internal role → row 1
                name_lower = node.get("name", "").lower()
                internal_keywords = ["team lead", "agent", "qa", "quality", "retention",
                                     "compliance", "email system", "shared mailbox",
                                     "deepa", "priya", "cti"]
                if any(kw in name_lower for kw in internal_keywords):
                    row_map[nid] = 1
                else:
                    row_map[nid] = 0
            else:
                # Unknown types → check name
                name_lower = node.get("name", "").lower()
                if "customer" in name_lower:
                    row_map[nid] = 0
                else:
                    row_map[nid] = 1

        return row_map

    # ─── Build the full HTML ───────────────────────────────────
    def _build_html(self, nodes, edges, kg, pipeline_docs, col_map, row_map):
        # Group nodes into grid cells: (row, col) → [nodes]
        grid = {}
        for node in nodes:
            r = row_map.get(node["id"], 1)
            c = col_map.get(node["id"], 1)
            grid.setdefault((r, c), []).append(node)

        grid_html = self._render_grid(grid)
        modal_html = self._render_modal()
        arrow_js = self._render_arrows_js(edges, col_map, row_map)
        modal_js = self._render_modal_js()
        data_script = f"""<script>
window.knowledgeGraph = {json.dumps(kg)};
window.pipelineDocs = {json.dumps(pipeline_docs)};
</script>"""

        stats_actors = sum(1 for n in nodes if n.get("type") == "actor")
        stats_systems = sum(1 for n in nodes if n.get("type") == "system")
        stats_stores = sum(1 for n in nodes if n.get("type") == "data_store")
        stats_risks = sum(len(n.get("risks", [])) for n in nodes)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Privacy DFD Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/leader-line-new@1.1.9/leader-line.min.js"></script>
    {data_script}
    <style>
        * {{ font-family: 'Inter', system-ui, sans-serif; }}
        .node-card {{
            cursor: pointer;
            transition: all 0.25s cubic-bezier(.4,0,.2,1);
        }}
        .node-card:hover {{
            transform: translateY(-3px) scale(1.02);
            box-shadow: 0 12px 28px rgba(0,0,0,0.12);
        }}
        .pill {{
            display: inline-flex; align-items: center;
            font-size: 0.6rem; padding: 1px 7px;
            border-radius: 9999px; margin: 1px;
            font-weight: 500; letter-spacing: 0.02em;
        }}
        .grid-zone {{
            border: 2px dashed #e2e8f0;
            border-radius: 12px;
            padding: 10px;
            min-height: 120px;
            display: flex; flex-direction: column; gap: 8px;
            transition: border-color 0.2s;
            position: relative;
        }}
        .grid-zone:hover {{ border-color: #94a3b8; }}
        .leader-line {{ z-index: 0 !important; }}
        .node-card {{ position: relative; z-index: 10; }}
        #modal-overlay {{ transition: opacity 0.25s ease; }}
        #modal-panel {{ transition: transform 0.3s cubic-bezier(.4,0,.2,1); }}
    </style>
</head>
<body class="bg-gradient-to-br from-slate-50 via-blue-50/20 to-slate-100 min-h-screen">
    <!-- ═══ HEADER ═══ -->
    <header class="bg-white/80 backdrop-blur-xl border-b border-slate-200/60 sticky top-0 z-40">
        <div class="max-w-[1500px] mx-auto px-6 py-3 flex items-center justify-between">
            <div class="flex items-center gap-3">
                <div class="w-9 h-9 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center shadow-lg shadow-indigo-200">
                    <span class="material-icons text-white" style="font-size:18px">security</span>
                </div>
                <div>
                    <h1 class="text-lg font-bold text-slate-800 leading-tight">Privacy DFD Dashboard</h1>
                    <p class="text-[11px] text-slate-400">{len(nodes)} entities · {len(edges)} data flows · {stats_risks} risks identified</p>
                </div>
            </div>
            <div class="flex gap-2 items-center">
                <div class="flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 rounded-lg border border-blue-100">
                    <span class="material-icons text-blue-500" style="font-size:14px">person</span>
                    <span class="text-xs font-medium text-blue-700">{stats_actors} Actors</span>
                </div>
                <div class="flex items-center gap-1.5 px-3 py-1.5 bg-green-50 rounded-lg border border-green-100">
                    <span class="material-icons text-green-500" style="font-size:14px">dns</span>
                    <span class="text-xs font-medium text-green-700">{stats_systems} Systems</span>
                </div>
                <div class="flex items-center gap-1.5 px-3 py-1.5 bg-purple-50 rounded-lg border border-purple-100">
                    <span class="material-icons text-purple-500" style="font-size:14px">storage</span>
                    <span class="text-xs font-medium text-purple-700">{stats_stores} Stores</span>
                </div>
            </div>
        </div>
    </header>

    <!-- ═══ MAIN GRID ═══ -->
    <main class="max-w-[1500px] mx-auto px-6 py-6">
        <div class="bg-white/60 backdrop-blur-sm rounded-2xl border border-slate-200/60 shadow-sm overflow-visible">
            <div class="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
                <div>
                    <h2 class="text-base font-semibold text-slate-700">Data Flow Matrix</h2>
                    <p class="text-[11px] text-slate-400 mt-0.5">Click any node to see full evidence trail · Arrows show data flows between entities</p>
                </div>
                <div class="flex gap-3 text-[10px] text-slate-400 items-center">
                    <span class="flex items-center gap-1"><span class="w-4 h-0.5 rounded" style="background:#ef4444"></span>Collection</span>
                    <span class="flex items-center gap-1"><span class="w-4 h-0.5 rounded" style="background:#3b82f6"></span>Transfer</span>
                    <span class="flex items-center gap-1"><span class="w-4 h-0.5 rounded" style="background:#22c55e"></span>Processing</span>
                    <span class="flex items-center gap-1"><span class="w-4 h-0.5 rounded" style="background:#a855f7"></span>Storage</span>
                </div>
            </div>
            <div class="p-5 overflow-visible">
                <div class="grid grid-cols-[120px_1fr_1fr_1fr_1fr] gap-3" id="dfd-grid">
                    <!-- Column Headers -->
                    <div></div>
                    {self._col_headers()}
                    <!-- Grid Rows -->
                    {grid_html}
                </div>
            </div>
        </div>
    </main>

    {modal_html}
    <script>{arrow_js}\n{modal_js}</script>
</body>
</html>"""

    def _col_headers(self):
        parts = []
        for i, (name, color, icon) in enumerate(zip(COLUMNS, COL_COLORS, COL_ICONS)):
            parts.append(
                f'<div class="rounded-xl p-2.5 text-center font-semibold text-xs border"'
                f' style="background:{color};border-color:{color}">'
                f'{icon} {name}</div>'
            )
        return "\n                    ".join(parts)

    def _render_grid(self, grid):
        """Render all rows of the swimlane grid."""
        parts = []
        for row_idx, (row_label, row_bg, row_text) in enumerate(ROWS):
            # Row label
            parts.append(
                f'<div class="rounded-xl p-2 flex items-center justify-center text-xs font-semibold border"'
                f' style="background:{row_bg};color:{row_text};border-color:{row_bg};'
                f'writing-mode:vertical-lr;text-orientation:mixed;transform:rotate(180deg)">'
                f'{row_label}</div>'
            )
            # 4 column cells for this row
            for col_idx in range(4):
                cell_nodes = grid.get((row_idx, col_idx), [])
                cards = "\n".join(self._render_card(n) for n in cell_nodes)
                zone_bg = COL_COLORS[col_idx] + "22"  # Subtle tinted background
                empty_placeholder = '<span class="text-slate-300 text-[10px] m-auto">—</span>'
                parts.append(
                    f'<div class="grid-zone" style="background:{zone_bg}">'
                    f'{cards if cards else empty_placeholder}'
                    f'</div>'
                )
        return "\n                    ".join(parts)

    def _render_card(self, node):
        nid = node.get("id", "unknown")
        name = node.get("name", nid)
        ntype = node.get("type", "unknown")
        c = COLOR.get(ntype, COLOR["unknown"])
        icon = ICON_MAP.get(ntype, "help_outline")

        data_els = node.get("data_elements", [])
        risks = node.get("risks", [])
        sources = node.get("sources", [])

        # Data element pills (max 3)
        pills = ""
        for de in data_els[:3]:
            pills += f'<span class="pill" style="background:{c["badge_bg"]};color:{c["badge_tx"]}">{de}</span>'
        if len(data_els) > 3:
            pills += f'<span class="pill" style="background:#f1f5f9;color:#64748b">+{len(data_els)-3}</span>'

        # Risk badge
        risk_badge = ""
        if risks:
            risk_badge = (
                f'<span style="position:absolute;top:-6px;right:-6px;width:20px;height:20px;'
                f'background:#ef4444;color:white;border-radius:50%;display:flex;align-items:center;'
                f'justify-content:center;font-size:10px;font-weight:700;box-shadow:0 2px 6px rgba(239,68,68,0.4)">'
                f'{len(risks)}</span>'
            )

        # Source count
        src_line = ""
        if sources:
            src_line = (f'<div style="display:flex;align-items:center;gap:3px;font-size:10px;color:#94a3b8;margin-top:4px">'
                        f'<span class="material-icons" style="font-size:11px">description</span>'
                        f'{len(sources)} source{"s" if len(sources)!=1 else ""}</div>')

        return f"""<div id="{nid}" class="node-card" data-node-id="{nid}"
            style="background:linear-gradient(135deg,{c['bg']},{c['bg2']});
            border-left:4px solid {c['border']};border-radius:12px;
            padding:10px 12px;position:relative;box-shadow:0 1px 4px rgba(0,0,0,0.06)">
            {risk_badge}
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
                <span class="material-icons" style="font-size:18px;color:{c['icon']}">{icon}</span>
                <div>
                    <div style="font-size:13px;font-weight:600;color:#1e293b;line-height:1.2">{name}</div>
                    <div style="font-size:9px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.05em">{ntype.replace('_',' ')}</div>
                </div>
            </div>
            <div style="display:flex;flex-wrap:wrap">{pills}</div>
            <div style="display:flex;align-items:center;justify-content:space-between;margin-top:8px">
                {src_line}
                <button class="details-btn" onclick="openModal('{nid}', event)" 
                    style="background:white;border:1px solid #e2e8f0;border-radius:6px;padding:3px 8px;
                    font-size:9px;font-weight:600;color:#64748b;display:flex;align-items:center;gap:2px;
                    box-shadow:0 1px 2px rgba(0,0,0,0.05);cursor:pointer;transition:all 0.2s">
                    <span class="material-icons" style="font-size:11px">visibility</span> DETAILS
                </button>
            </div>
        </div>"""

    # ─── Modal HTML ────────────────────────────────────────────
    def _render_modal(self):
        return """
    <div id="modal-overlay" class="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 hidden opacity-0" onclick="closeModal()">
        <div id="modal-panel" class="absolute right-0 top-0 h-full w-full max-w-lg bg-white shadow-2xl overflow-y-auto translate-x-full" onclick="event.stopPropagation()" style="transition:transform .3s cubic-bezier(.4,0,.2,1)">
            <div class="sticky top-0 bg-white/95 backdrop-blur-md border-b border-slate-100 px-5 py-4 flex items-center justify-between z-10">
                <div>
                    <h3 id="modal-title" class="text-base font-bold text-slate-800">Node Details</h3>
                    <p id="modal-subtitle" class="text-[11px] text-slate-400 mt-0.5"></p>
                </div>
                <button onclick="closeModal()" class="w-7 h-7 rounded-lg bg-slate-100 hover:bg-slate-200 flex items-center justify-center transition">
                    <span class="material-icons text-slate-400" style="font-size:18px">close</span>
                </button>
            </div>
            <div id="modal-body" class="p-5 space-y-4"></div>
        </div>
    </div>"""

    # ─── Arrow JavaScript ──────────────────────────────────────
    def _render_arrows_js(self, edges, col_map, row_map):
        lines = [
            "// ═══ LEADER LINE ARROWS ═══",
            "let allLines = [];",
            "function drawConnections() {",
            "  allLines.forEach(l => { try { l.remove(); } catch(e){} });",
            "  allLines = [];",
            "  const pairCount = {};",
        ]
        
        for edge in edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            if not src or not tgt: continue
            
            ft = edge.get("flow_type", "transfer")
            color = FLOW_COLORS.get(ft, "#94a3b8")
            
            s_col = col_map.get(src, 1)
            t_col = col_map.get(tgt, 1)
            s_row = row_map.get(src, 1)
            t_row = row_map.get(tgt, 1)
            
            # Intelligent socket routing
            if s_col < t_col:
                path, ss, es = "fluid", "right", "left"
            elif s_col > t_col:
                path, ss, es = "magnet", "bottom", "bottom"
            else:
                if s_row == t_row:
                    path, ss, es = "magnet", "bottom", "bottom"
                elif s_row < t_row:
                    path, ss, es = "fluid", "bottom", "top"
                else:
                    path, ss, es = "fluid", "top", "bottom"

            lines.append(f"""  try {{
    var s = document.getElementById('{src}'), t = document.getElementById('{tgt}');
    if (s && t) {{
      var pairKey = s.id < t.id ? s.id + '-' + t.id : t.id + '-' + s.id;
      var count = (pairCount[pairKey] || 0);
      pairCount[pairKey] = count + 1;
      var startGrav = 50 + (count * 25);
      var endGrav = 50 + (count * 25);
      var size = 2 + (count * 0.5);
      
      var line = new LeaderLine(s, t, {{
        path:'{path}', startSocket:'{ss}', endSocket:'{es}',
        startPlug:'behind', endPlug:'arrow3',
        color:'{color}', size:size, 
        startSocketGravity: [startGrav, startGrav], 
        endSocketGravity: [endGrav, endGrav],
        dropShadow: true,
        hide: true  // HIDDEN BY DEFAULT
      }});
      allLines.push({{ line: line, source: '{src}', target: '{tgt}' }});
    }}
  }} catch(e) {{}}""")

        lines.append("}")
        lines.append("document.addEventListener('DOMContentLoaded',()=>{")
        lines.append("  setTimeout(drawConnections,800);")
        lines.append("  window.addEventListener('resize',()=>setTimeout(drawConnections,300));")
        lines.append("});")
        return "\n".join(lines)

    # ─── Modal JavaScript ──────────────────────────────────────
    def _render_modal_js(self):
        return """
// ═══ LOGIC & INTERACTIVE ARROWS ═══
let currentNodeFocus = null;

function focusNode(nodeId) {
    if (currentNodeFocus === nodeId) {
        // Toggle off if clicking the same node
        currentNodeFocus = null;
        allLines.forEach(item => item.line.hide('fade', {duration: 200}));
        document.querySelectorAll('.node-card').forEach(card => {
            card.style.opacity = '1';
            card.style.transform = '';
            card.style.boxShadow = '';
        });
        return;
    }
    
    currentNodeFocus = nodeId;
    
    // 1. Show only lines connected to this node
    allLines.forEach(item => {
        if (item.source === nodeId || item.target === nodeId) {
            item.line.show('draw', {duration: 400, timing: 'ease-out'});
        } else {
            item.line.hide('fade', {duration: 200});
        }
    });

    // 2. Dim unrelated cards slightly
    document.querySelectorAll('.node-card').forEach(card => {
        if (card.dataset.nodeId === nodeId) {
            card.style.opacity = '1';
            card.style.transform = 'scale(1.02)';
            card.style.boxShadow = '0 12px 28px rgba(0,0,0,0.12)';
        } else {
            // Check if connected
            const isConnected = allLines.some(l => 
                (l.source === nodeId && l.target === card.dataset.nodeId) || 
                (l.target === nodeId && l.source === card.dataset.nodeId)
            );
            card.style.opacity = isConnected ? '1' : '0.4';
            card.style.transform = 'none';
            card.style.boxShadow = 'none';
        }
    });
}

function openModal(nodeId, event) {
    if (event) event.stopPropagation();
    
    // Ensure the node is focused when opening its modal
    if (currentNodeFocus !== nodeId) {
        focusNode(nodeId);
    }

    const kg = window.knowledgeGraph || {};
    const node = (kg.nodes || []).find(n => n.id === nodeId);
    if (!node) return;
    
    document.getElementById('modal-title').textContent = node.name || nodeId;
    document.getElementById('modal-subtitle').textContent = (node.type || '').replace('_',' ').toUpperCase();

    let b = '';
    // Data Elements
    const dels = node.data_elements || [];
    if (dels.length) {
        b += '<div><h4 class="text-xs font-bold text-slate-600 mb-2 flex items-center gap-1"><span class="material-icons text-blue-400" style="font-size:14px">data_usage</span>Data Elements ('+dels.length+')</h4><div class="flex flex-wrap gap-1">';
        dels.forEach(d => b += '<span class="pill" style="background:#dbeafe;color:#1d4ed8">'+d+'</span>');
        b += '</div></div>';
    }
    // Risks
    const risks = node.risks || [];
    if (risks.length) {
        b += '<div><h4 class="text-xs font-bold text-red-500 mb-2 flex items-center gap-1"><span class="material-icons" style="font-size:14px">warning</span>Risks ('+risks.length+')</h4><div class="space-y-1.5">';
        risks.forEach(r => {
            const desc = typeof r === 'string' ? r : (r.description || JSON.stringify(r));
            const sev = typeof r === 'object' ? (r.severity||'') : '';
            b += '<div class="text-[11px] bg-red-50 rounded-lg p-2.5 text-red-700 border border-red-100">';
            if (sev) b += '<span class="pill" style="background:#fecaca;color:#b91c1c;font-weight:700;margin-right:4px">'+sev.toUpperCase()+'</span>';
            b += desc + '</div>';
        });
        b += '</div></div>';
    }
    // Connected Flows
    const outE = (kg.edges||[]).filter(e => e.source === nodeId);
    const inE = (kg.edges||[]).filter(e => e.target === nodeId);
    if (outE.length || inE.length) {
        b += '<div><h4 class="text-xs font-bold text-slate-600 mb-2 flex items-center gap-1"><span class="material-icons text-green-400" style="font-size:14px">swap_horiz</span>Connected Flows</h4><div class="space-y-1">';
        outE.forEach(e => b += '<div class="text-[11px] bg-green-50 rounded px-2 py-1 border border-green-100">→ <b>'+e.target+'</b> <span class="text-slate-400">via '+( e.channel||'—')+' ('+((e.data_elements||[]).length)+' elements)</span></div>');
        inE.forEach(e => b += '<div class="text-[11px] bg-blue-50 rounded px-2 py-1 border border-blue-100">← <b>'+e.source+'</b> <span class="text-slate-400">via '+(e.channel||'—')+' ('+((e.data_elements||[]).length)+' elements)</span></div>');
        b += '</div></div>';
    }
    // Source Documents
    const srcs = node.sources || [];
    if (srcs.length) {
        b += '<div><h4 class="text-xs font-bold text-slate-600 mb-2 flex items-center gap-1"><span class="material-icons text-purple-400" style="font-size:14px">description</span>Source Documents</h4><div class="space-y-1">';
        srcs.forEach(s => b += '<div class="text-[11px] bg-purple-50 rounded px-2 py-1 border border-purple-100 flex items-center gap-1"><span class="material-icons" style="font-size:11px">insert_drive_file</span>'+s+'</div>');
        b += '</div></div>';
    }
    // Evidence Trail
    const relEdges = (kg.edges||[]).filter(e => e.source===nodeId || e.target===nodeId);
    const evs = []; relEdges.forEach(e => (e.evidence||[]).forEach(ev => { if(evs.indexOf(ev)===-1) evs.push(ev); }));
    if (evs.length) {
        b += '<div><h4 class="text-xs font-bold text-slate-600 mb-2 flex items-center gap-1"><span class="material-icons text-amber-400" style="font-size:14px">format_quote</span>Evidence Trail</h4><div class="space-y-1.5">';
        evs.slice(0,6).forEach(ev => b += '<blockquote class="text-[11px] text-slate-500 bg-amber-50/80 rounded-lg p-2.5 border-l-3 border-amber-300 italic leading-relaxed">&ldquo;'+ev+'&rdquo;</blockquote>');
        if (evs.length > 6) b += '<p class="text-[10px] text-slate-400">+'+(evs.length-6)+' more</p>';
        b += '</div></div>';
    }
    document.getElementById('modal-body').innerHTML = b;
    const ov = document.getElementById('modal-overlay'), pn = document.getElementById('modal-panel');
    ov.classList.remove('hidden');
    requestAnimationFrame(() => { ov.classList.remove('opacity-0'); pn.classList.remove('translate-x-full'); });
}
function closeModal() {
    const ov = document.getElementById('modal-overlay'), pn = document.getElementById('modal-panel');
    ov.classList.add('opacity-0'); pn.classList.add('translate-x-full');
    setTimeout(() => ov.classList.add('hidden'), 300);
}
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.node-card').forEach(c => c.addEventListener('click', () => focusNode(c.dataset.nodeId)));
});
"""
