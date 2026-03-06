"""
Visual DFD Agent — An iterative HTML generation loop that renders
the output in a headless browser (Playwright), detects node/arrow
overlaps, and prompts the LLM to fix the layout until it passes.
"""
import os
import json
import asyncio
import anthropic
from pathlib import Path

from config import Config
from utils.logger import setup_logger
from test.graph.html_previewer import VisualPreviewer

logger = setup_logger("VisualDfdAgent")

SYSTEM_PROMPT = """You are a Master UI/UX Engineer and Privacy Architect. You are tasked with generating a high-level Privacy Data Flow Diagram (DFD) using HTML, Tailwind CSS v4, and Google Material Icons.

YOUR STRICT INSTRUCTIONS:

1. DEPENDENCIES IN <head>:
   - `<script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>`
   - `<link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">`
   - `<script src="https://cdn.jsdelivr.net/npm/leader-line-new@1.1.9/leader-line.min.js"></script>`

2. MATRIX LAYOUT (ENTERPRISE GRID):
   - You MUST use CSS Grid to create a strict Swimlane Matrix.
   - COLUMNS: "Data Collection", "Data Processing", "Data Dispersal", "Storage". (Gradient headers).
   - ROWS (Left Sidebar): "Customers", "Internal Departments", "Vendors/Partners". (Pastel backgrounds).
   - Use absolute crisp borders. Ensure columns are wide enough to fit nodes without overlapping.

3. NODE (CARD) STYLING:
   - Modern, realistic UI cards: `<div id="[entity_id]" class="bg-white rounded-xl shadow-lg border-l-4 border-blue-500 p-4 relative flex flex-col gap-2 z-10 w-64 min-h-32">`
   - You MUST provide a unique `id` attribute for every node card corresponding to its JSON entity ID. 
   - Show 'Data Elements' as small pill badges. Max 3, then show "+X more".
   - Risk Badges (Red corner circles) if risks > 0.

4. DRAWING ARROWS (CRITICAL FIX FOR SPAGHETTI OVERLAP):
   - You MUST configure LeaderLine properly to avoid overlapping.
   - Inside `<script>`, attach lines using `new LeaderLine(document.getElementById('source_id'), document.getElementById('target_id'), { ...options... })`.
   - Wrap line drawing in: `window.addEventListener('load', () => setTimeout(() => { ...draw... }, 800));`
   - MANDATORY options based on layout flow: `{ path: 'grid', startSocket: 'right', endSocket: 'left', color: '#94a3b8', size: 3, dropShadow: true }`. Ensure 'grid' or 'fluid' pathing to route clearly around cards.

5. INTERACTIVE SOURCE OF TRUTH (EVIDENCE MODAL/SLIDEOUT):
   - Provide a Modal/Side Panel when a node or edge is clicked, showing ALL Data Elements, Risks, Exact source files, and Evidence Text.

Return ONLY the raw HTML source code. No markdown fences."""


class VisualDfdAgent:

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        self.model = Config.CLAUDE_MODEL
        self.previewer = VisualPreviewer()

    def generate(self, graph_dir, pipeline_dir, output_path, max_visual_iterations=3):
        """
        Generates HTML iteratively, rendering via headless browser to detect layout overlap.
        """
        graph_dir = Path(graph_dir)
        pipeline_dir = Path(pipeline_dir)
        output_path = Path(output_path)
        
        # Load data bundle
        def load_json(path):
            if Path(path).exists():
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            return None

        data_bundle = {
            "knowledge_graph": load_json(graph_dir / "graph" / "knowledge_graph.json") or {},
            "privacy_dfd": load_json(graph_dir / "graph" / "privacy_dfd.json") or {},
            "dfd_render_plan": load_json(graph_dir / "graph" / "dfd_render_plan.json") or {},
            "pipeline_documents": {}
        }
        for p in pipeline_dir.glob("*_intelligence.json"):
            data_bundle["pipeline_documents"][p.name] = load_json(p)

        logger.info(f"Loaded ALL JSON files for visual generation.")

        # Initial Prompt
        prompt = f"""Generate the HTML visualization.

ALL DATA (Knowledge Graph & Source Evidence):
{json.dumps(data_bundle, indent=1)}

Ensure you assign accurate `id` attributes to node DIVs so LeaderLine can connect them! Return ONLY raw HTML."""

        messages = [{"role": "user", "content": prompt}]

        # --- Self-Correction Loop ---
        for attempt in range(1, max_visual_iterations + 1):
            logger.info(f"--- Visual Generation Attempt {attempt}/{max_visual_iterations} ---")
            
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    temperature=0.2,
                    system=SYSTEM_PROMPT,
                    messages=messages
                )
                html = response.content[0].text.strip()
                
                # Clean markdown fences
                if html.startswith("```html"): html = html[7:]
                if html.startswith("```"): html = html[3:]
                if html.endswith("```"): html = html[:-3]
                html = html.strip()
                
                # Write to temp file for previewer
                temp_html_path = output_path.parent / f"temp_preview_v{attempt}.html"
                with open(temp_html_path, "w", encoding="utf-8") as f:
                    f.write(html)
                    
                # Run headless visual preview evaluating the layout
                logger.info("Executing headless layout analysis via Playwright...")
                preview_report = asyncio.run(self.previewer.evaluate_html(str(temp_html_path)))
                
                if preview_report["valid"]:
                    logger.info("✅ Visual layout validated (no overlapping cards/lines found).")
                    # Save final output
                    with open(output_path, "w", encoding="utf-8") as f:
                        f.write(html)
                    temp_html_path.unlink(missing_ok=True)
                    return str(output_path)
                else:
                    issues = preview_report["issues"]
                    logger.warning(f"❌ Visual layout issues found on attempt {attempt}:")
                    for issue in issues:
                        logger.warning(f"  - {issue}")
                        
                    if attempt < max_visual_iterations:
                        # Append feedback to prompt to fix grid logic
                        feedback_msg = (
                            f"Your HTML output rendered with the following structural/overlap issues:\n\n"
                            f"{chr(10).join(issues)}\n\n"
                            f"Please FIX the CSS Grid structure so bounding boxes do not overlap, "
                            f"and adjust LeaderLine options (e.g., path: 'grid', startSocket: 'right') to stop lines from crossing. "
                            f"Return ONLY the corrected full HTML."
                        )
                        messages.append({"role": "assistant", "content": html})
                        messages.append({"role": "user", "content": feedback_msg})
                    else:
                        logger.warning("Max iterations reached. Saving the last attempt as final.")
                        with open(output_path, "w", encoding="utf-8") as f:
                            f.write(html)
                        temp_html_path.unlink(missing_ok=True)
                        return str(output_path)
                        
            except Exception as e:
                logger.error(f"Visual DFD Agent failed on attempt {attempt}: {e}")
                
        return ""
