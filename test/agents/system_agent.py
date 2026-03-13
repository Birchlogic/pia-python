from utils.llm_adapter import get_llm_client
"""
SystemExtractionAgent — Uses Anthropic Claude to identify software systems
from structured NLP chunks, enriching deterministic extraction.

Enhanced with JSON prompting: requires timestamp, speaker, and
source_file evidence for every extracted system.
"""
import json
import anthropic
from config import Config
from utils.logger import setup_logger

logger = setup_logger("SystemAgent")

SYSTEM_PROMPT = """You are an expert systems analyst. Given structured transcript text with timestamps and speaker information, identify ALL software systems, platforms, tools, and technology mentioned or implied.

For each system you MUST return a JSON object with EXACTLY these fields:

```json
{
  "name": "string — the system name (e.g. Salesforce, Ameyo)",
  "type": "string — one of: CRM, telephony, communication, storage, analytics, security, database, other",
  "evidence": "string — exact quote from the text that mentions this system",
  "evidence_timestamp": "string — timestamp from the transcript e.g. 00:02:31",
  "evidence_speaker": "string — who mentioned it (person name)",
  "evidence_speaker_role": "string — their role (interviewer/interviewee/analyst)",
  "source_file": "string — filename where this evidence was found"
}
```

Rules:
1. You MUST only identify systems supported by evidence in the text. Do NOT hallucinate.
2. Every system MUST have evidence_timestamp and evidence_speaker from the transcript.
3. Return ONLY a valid JSON array. No markdown fences, no explanation text."""


class SystemExtractionAgent:

    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}
        self.client = get_llm_client(self.ai_config)
        self.model = self.ai_config.get("model") or "claude-3-5-sonnet-20241022"

    def extract(self, text_chunks, structured_context=None):
        """
        Extract systems from text chunks using LLM reasoning.

        Args:
            text_chunks: list of text strings (dialogue lines, section contents, etc.)
            structured_context: formatted string with timestamps and speakers

        Returns:
            list of system dicts with name, type, evidence, and provenance
        """
        # Prefer structured context with timestamps if available
        combined = structured_context if isinstance(structured_context, str) else "\n".join(text_chunks[:50])

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
