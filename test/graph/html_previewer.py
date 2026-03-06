"""
HTML Previewer — Uses Playwright to render the DFD headless and
extract layout metrics (bounding boxes) to detect overlaps.
"""
import json
import asyncio
from playwright.async_api import async_playwright
from utils.logger import setup_logger

logger = setup_logger("VisualPreviewer")


class VisualPreviewer:

    async def evaluate_html(self, html_path):
        """
        Load the HTML file headless, wait for LeaderLine to draw,
        and extract all bounding boxes to compute a collision report.
        """
        issues = []
        try:
            async with async_playwright() as p:
                # Use Desktop viewport to simulate a full dashboard render
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": 1920, "height": 1080})
                
                # Load the local HTML file
                await page.goto(f"file://{html_path}")
                
                # Wait for leader-line to render (prompt instructed a 800ms delay)
                await asyncio.sleep(2)
                
                # Execute JS to get bounding boxes of all nodes and SVG arrows
                layout_data = await page.evaluate('''() => {
                    const data = { nodes: [], lines: [], viewport: { width: window.innerWidth, height: window.innerHeight } };
                    
                    // Extract Nodes (assume they have an ID and typical classes for cards)
                    document.querySelectorAll('div[id]').forEach(el => {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0 && !el.className.includes('modal') && !el.className.includes('hidden')) {
                            data.nodes.push({
                                id: el.id,
                                text: el.innerText.substring(0, 30).replace(/\\n/g, ' '),
                                x: rect.x, y: rect.y,
                                width: rect.width, height: rect.height
                            });
                        }
                    });

                    // Extract LeaderLine SVG paths
                    document.querySelectorAll('svg.leader-line').forEach((svg, idx) => {
                        const rect = svg.getBoundingClientRect();
                        data.lines.push({
                            id: `line_${idx}`,
                            x: rect.x, y: rect.y,
                            width: rect.width, height: rect.height
                        });
                    });

                    return data;
                }''')

                await browser.close()
                
                nodes = layout_data.get("nodes", [])
                lines = layout_data.get("lines", [])
                
                logger.info(f"Previewer extracted {len(nodes)} nodes, {len(lines)} lines")
                
                if not lines:
                    issues.append("ERROR: No leader-line SVG elements found on the screen. The script failed to execute or draw arrows.")
                
                if len(nodes) < 5:
                    issues.append("ERROR: Less than 5 UI nodes found. The grid structure might be broken.")

                # Simplistic Overlap Detection (Bounding Box collision)
                # O(N^2) checking for overlapping nodes
                overlaps = 0
                for i in range(len(nodes)):
                    for j in range(i + 1, len(nodes)):
                        n1, n2 = nodes[i], nodes[j]
                        # Don't flag overlap if one is inside the other (e.g. wrapper divs),
                        # but flag if they collide horizontally/vertically.
                        if (n1['x'] < n2['x'] + n2['width'] and
                            n1['x'] + n1['width'] > n2['x'] and
                            n1['y'] < n2['y'] + n2['height'] and
                            n1['y'] + n1['height'] > n2['y']):
                            overlaps += 1
                            issues.append(f"OVERLAP ERROR: Node '{n1['text']}' overlaps physically with Node '{n2['text']}'. Update CSS Grid bounds.")

                if overlaps > 0:
                    logger.warning(f"Previewer found {overlaps} node overlaps")
                
                return {
                    "valid": len(issues) == 0,
                    "issues": issues,
                    "metrics": layout_data
                }
                
        except Exception as e:
            logger.error(f"Playwright evaluation failed: {e}")
            return {"valid": False, "issues": [f"Playwright crashed: {str(e)}"]}
