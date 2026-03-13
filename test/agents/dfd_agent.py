from utils.llm_adapter import get_llm_client
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

1. **nodes**: Each node is an actor, system, or data store. Return JSON:
   ```json
   {"id": "snake_case_id", "name": "Display Name", "type": "external_entity|process|data_store|system|actor"}
   ```

2. **edges**: Each edge is a data flow between nodes. PRESERVE the evidence_trail from the input flows. Return JSON:
   ```json
   {
     "source_id": "source_node_id",
     "target_id": "target_node_id",
     "label": "what data flows",
     "data_elements": ["specific data items"],
     "evidence_trail": [
       {"evidence": "quote", "timestamp": "00:02:31", "speaker": "name", "speaker_role": "role", "source_file": "file.json"}
     ]
   }
   ```

3. **risk_annotations**: Risk annotations on specific nodes or edges. Return JSON:
   ```json
   {"target_id": "node_or_edge_id", "risk_name": "short name", "severity": "critical|high|medium|low", "description": "details"}
   ```

Return ONLY valid JSON:
{"nodes": [...], "edges": [...], "risk_annotations": [...]}

Rules:
1. Do NOT hallucinate nodes or edges. Only include items supported by the input data.
2. Use role names for actors, NOT person names (e.g. "Customer Care Agent" not "Nikhil Joshi").
3. COPY evidence_trail from input data_flows to the corresponding edges — do not drop it."""


class DFDBuilderAgent:

    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}
        self.client = get_llm_client(self.ai_config)
        self.model = self.ai_config.get("model") or "claude-3-5-sonnet-20241022"

    def build(self, actors, systems, data_elements, data_flows, risks, structured_context=None):
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

DATA FLOWS (preserve evidence_trail on each edge):
{json.dumps(data_flows, indent=2)}

RISKS:
{json.dumps(risks, indent=2)}"""

        if structured_context:
            context += f"\n\nSTRUCTURED TRANSCRIPT CONTEXT (for reference):\n{structured_context[:3000]}"

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

            # Safety net: re-attach evidence_trail from input flows if LLM dropped it
            flow_trail_map = {}
            for f in data_flows:
                src = f.get("source", "").lower()
                dst = f.get("destination", "").lower()
                if f.get("evidence_trail"):
                    flow_trail_map[(src, dst)] = f["evidence_trail"]

            for edge in dfd.get("edges", []):
                if not edge.get("evidence_trail"):
                    src = edge.get("source_id", "").lower().replace("_", " ")
                    tgt = edge.get("target_id", "").lower().replace("_", " ")
                    # Try direct match, then fuzzy
                    edge["evidence_trail"] = flow_trail_map.get((src, tgt), [])

            logger.info(f"DFDBuilder created {len(dfd.get('nodes', []))} nodes, {len(dfd.get('edges', []))} edges")
            return dfd
        except Exception as e:
            logger.error(f"DFDBuilderAgent failed: {e}")
            return {"nodes": [], "edges": [], "risk_annotations": []}
