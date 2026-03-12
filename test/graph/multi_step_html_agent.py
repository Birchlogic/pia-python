from utils.llm_adapter import get_llm_client
"""
Multi-Step HTML Agent — A robust generator that builds the
dashboard incrementally in chunks to avoid LLM token limits.
"""
import os
import re
import json
import asyncio
import anthropic
from pathlib import Path

from config import Config
from utils.logger import setup_logger
"""
Token-Safe Client-Side HTML Agent — Generates a Javascript-powered
Dashboard template that dynamically renders injected JSON data.
"""
import os
import json
import asyncio
import anthropic
from pathlib import Path

from config import Config
from utils.logger import setup_logger
from test.graph.html_previewer import VisualPreviewer

logger = setup_logger("SingleShotTemplateAgent")

SYSTEM_PROMPT = """You are a Senior Frontend Architect. Generate a COMPLETE, self-contained HTML file for a Privacy Data Flow Diagram (DFD).

THE TRICK: To avoid LLM token limits, you must NOT hardcode the HTML for the nodes, edges, or evidence!
The exact JSON data has already been injected into the page globally at:
 - `window.knowledgeGraph` (Contains `.nodes` and `.edges`)
 - `window.pipelineDocs`

YOUR JOB is to generate an HTML skeleton and a `<script>` block that DYNAMICALLY RENDERS the dashboard.

1. HTML SKELETON:
   - Include Tailwind CSS v4 CDN. Include Material Icons. Include LeaderLine CDN.
   - Build a CSS Grid layout (Matrix) with Cols (Collection, Processing, Dispersal, Storage) and Rows (Customers, Internal, Vendors).
   - Provide empty container `<div id="customers-collection"></div>` etc.

2. JAVASCRIPT RENDERING LOOP:
   - Iterate over `window.knowledgeGraph.nodes`. Check their `.type` (internal/external/vendor) and create an HTML string or `document.createElement` for an interactive Tailwind Card.
   - Card MUST have an exact ID: `id="${node.id}"`.
   - Insert it into the correct grid container based on node type.

3. DRAWMING ARROWS (LeaderLine):
   - Wait for DOM, then iterate over `window.knowledgeGraph.edges`.
   - `new LeaderLine(document.getElementById(edge.source), document.getElementById(edge.target), {path: 'grid', startSocket: 'right', endSocket: 'left', color: '#94a3b8'})`

4. MODALS & EVIDENCE:
   - Provide ONE generic Modal HTML block hidden on the page.
   - Attach a click listener to the `.node-card`s.
   - When clicked, find the node in `knowledgeGraph` and `pipelineDocs`, and dynamically set the Modal's `innerHTML` to show Data Elements, Risks, and Source Evidence.

Return ONLY raw HTML. No markdown code formatting."""

class SingleShotTemplateAgent:
    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}
        self.client = get_llm_client(self.ai_config)
        self.model = self.ai_config.get("model") or "claude-3-5-sonnet-20241022"
        self.previewer = VisualPreviewer()

    def generate(self, graph_dir, pipeline_dir, output_path, max_visual_iterations=2):
        graph_dir = Path(graph_dir)
        pipeline_dir = Path(pipeline_dir)
        output_path = Path(output_path)
        
        # Load Data
        def load_json(path):
            if Path(path).exists():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return None

        kg = load_json(graph_dir / "graph" / "knowledge_graph.json") or {}
        pipeline_docs = {}
        for p in pipeline_dir.glob("*_intelligence.json"):
            pipeline_docs[p.name] = load_json(p)

        logger.info(f"Loaded Data. Generating dynamic JS Template...")

        # Inject Data at the top of the prompt logic
        injected_script = f"""
<script>
window.knowledgeGraph = {json.dumps(kg)};
window.pipelineDocs = {json.dumps(pipeline_docs)};
</script>
"""

        prompt = "Generate the DFD Dashboard HTML and Javascript Template."

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                temperature=0.2,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )
            html = response.content[0].text.strip()
            if html.startswith("```html"): html = html[7:]
            if html.startswith("```"): html = html[3:]
            if html.endswith("```"): html = html[:-3]
            html = html.strip()

            # Insert the literal JSON script at the end of the <head> segment
            if "</head>" in html:
                html = html.replace("</head>", injected_script + "\n</head>")
            else:
                html = injected_script + "\n" + html

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html)
            
            # Simple visual preview
            preview_report = asyncio.run(self.previewer.evaluate_html(str(output_path)))
            if not preview_report["valid"]:
                logger.warning(f"Previewer reported minor issues: {preview_report['issues']}")

            return str(output_path)
        except Exception as e:
            logger.error(f"Generation failed: {e}")
            return ""
