"""
DFDBuilderAgent — Constructs a structured DFD graph from extracted
actors, systems, data elements, and flows.
"""
import json
import anthropic
from config import Config
from utils.logger import setup_logger

logger = setup_logger("DFDBuilderAgent")

SYSTEM_PROMPT = """You are a data flow diagram (DFD) architect. Given extracted entities (actors, systems, data elements, data flows, risks), construct a complete DFD graph structure.

Build the DFD with:

1. **nodes**: Each node is an actor, system, or data store
   - id: unique string identifier (snake_case)
   - name: display name
   - type: "external_entity", "process", "data_store"

2. **edges**: Each edge is a data flow between nodes
   - source_id: source node id
   - target_id: target node id
   - label: what data flows
   - data_elements: list of specific data items

3. **risks**: Risk annotations on specific nodes or edges
   - target_id: node or edge this risk applies to
   - risk_name: short name
   - severity: critical/high/medium/low

Return ONLY valid JSON matching this structure:
{
  "nodes": [...],
  "edges": [...],
  "risk_annotations": [...]
}

Do NOT hallucinate nodes or edges. Only include items supported by the input data."""


class DFDBuilderAgent:

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        self.model = Config.CLAUDE_MODEL

    def build(self, actors, systems, data_elements, data_flows, risks):
        """
        Construct a DFD graph from extracted intelligence.

        Returns:
            dict with 'nodes', 'edges', 'risk_annotations'
        """
        context = f"""Build a DFD from the following extracted data:

ACTORS:
{json.dumps(actors, indent=2)}

SYSTEMS:
{json.dumps(systems, indent=2)}

DATA ELEMENTS:
{json.dumps(data_elements, indent=2)}

DATA FLOWS:
{json.dumps(data_flows, indent=2)}

RISKS:
{json.dumps(risks, indent=2)}"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context}]
            )
            content = response.content[0].text.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                content = content.rsplit("```", 1)[0]
            dfd = json.loads(content)
            logger.info(f"DFDBuilder created {len(dfd.get('nodes', []))} nodes, {len(dfd.get('edges', []))} edges")
            return dfd
        except Exception as e:
            logger.error(f"DFDBuilderAgent failed: {e}")
            return {"nodes": [], "edges": [], "risk_annotations": []}
