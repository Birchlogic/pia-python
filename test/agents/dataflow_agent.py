from utils.llm_adapter import get_llm_client
"""
DataFlowAgent — Uses Anthropic Claude to infer data flows between
actors, systems, and data stores from structured NLP chunks.
"""
import json
import anthropic
from config import Config
from utils.logger import setup_logger

logger = setup_logger("DataFlowAgent")

SYSTEM_PROMPT = """You are a senior data privacy analyst. Given structured text from interview transcripts or analyst field notes, infer ALL data flows between actors, systems, and data stores.

Context provided:
- Known actors (people/roles involved)
- Known systems (software platforms)
- Known data elements (PII, financial data, identifiers)

For each data flow, provide:
- source: who/what sends the data
- destination: who/what receives the data
- data: what data is transferred
- channel: how it moves (API, manual, email, phone, etc.)
- evidence: exact text that supports this flow

You MUST only infer flows that are supported by evidence in the text. Do NOT hallucinate flows.

Return ONLY a valid JSON array. No markdown, no explanation.

Example:
[
  {"source": "Customer", "destination": "WhatsApp", "data": "PAN image", "channel": "messaging", "evidence": "customer sends PAN photo on WhatsApp"},
  {"source": "Agent", "destination": "Salesforce", "data": "call notes", "channel": "manual entry", "evidence": "agent logs the call in Salesforce"}
]"""


class DataFlowAgent:

    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}
        self.client = get_llm_client(self.ai_config)
        self.model = self.ai_config.get("model") or Config.CLAUDE_MODEL

    def extract(self, text_chunks, actors=None, systems=None, data_elements=None):
        """
        Infer data flows from text using LLM reasoning.

        Args:
            text_chunks: list of text strings
            actors: list of known actor names
            systems: list of known system names
            data_elements: list of known data elements

        Returns:
            list of flow dicts
        """
        context = f"""Known actors: {json.dumps(actors or [])}
Known systems: {json.dumps(systems or [])}
Known data elements: {json.dumps(data_elements or [])}

--- TEXT TO ANALYZE ---
{chr(10).join(text_chunks[:50])}"""

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
            flows = json.loads(content)
            logger.info(f"DataFlowAgent extracted {len(flows)} flows")
            return flows
        except Exception as e:
            logger.error(f"DataFlowAgent failed: {e}")
            return []
