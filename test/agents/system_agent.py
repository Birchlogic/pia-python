from utils.llm_adapter import get_llm_client
"""
SystemExtractionAgent — Uses Anthropic Claude to identify software systems
from structured NLP chunks, enriching deterministic extraction.
"""
import json
import anthropic
from config import Config
from utils.logger import setup_logger

logger = setup_logger("SystemAgent")

SYSTEM_PROMPT = """You are an expert systems analyst. Given structured text from interview transcripts or analyst field notes about a department's operations, identify ALL software systems, platforms, tools, and technology mentioned or implied.

For each system found, provide:
- name: The system name
- type: One of "CRM", "telephony", "communication", "storage", "analytics", "security", "database", "other"
- evidence: The exact text that mentions or implies this system

Return ONLY valid JSON array. No markdown, no explanation.

Example:
[
  {"name": "Salesforce", "type": "CRM", "evidence": "we log everything in Salesforce"},
  {"name": "Ameyo", "type": "telephony", "evidence": "calls come through Ameyo"}
]"""


class SystemExtractionAgent:

    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}
        self.client = get_llm_client(self.ai_config)
        self.model = self.ai_config.get("model") or "claude-3-5-sonnet-20241022"

    def extract(self, text_chunks):
        """
        Extract systems from text chunks using LLM reasoning.

        Args:
            text_chunks: list of text strings (dialogue lines, section contents, etc.)

        Returns:
            list of system dicts with name, type, evidence
        """
        combined = "\n".join(text_chunks[:50])  # Limit to avoid token overflow

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": combined}]
            )
            content = response.content[0].text.strip()
            # Clean any markdown fencing
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                content = content.rsplit("```", 1)[0]
            systems = json.loads(content)
            logger.info(f"SystemAgent extracted {len(systems)} systems")
            return systems
        except Exception as e:
            logger.error(f"SystemAgent failed: {e}")
            return []
