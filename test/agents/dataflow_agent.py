from utils.llm_adapter import get_llm_client
"""
DataFlowAgent — Uses Anthropic Claude to infer data flows between
actors, systems, and data stores from structured NLP chunks.

Enhanced with JSON prompting: requires timestamp, speaker, and
source_file evidence for every extracted flow.
"""
import json
import anthropic
from config import Config
from utils.logger import setup_logger

logger = setup_logger("DataFlowAgent")

SYSTEM_PROMPT = """You are a senior data privacy analyst. Given structured transcript text with timestamps and speaker information, infer ALL data flows between actors, systems, and data stores.

Context provided:
- Known actors (people/roles involved)
- Known systems (software platforms)
- Known data elements (PII, financial data, identifiers)
- Structured text with [timestamp] Speaker (role) [source_file]: message format

For each data flow you MUST return a JSON object with EXACTLY these fields:

```json
{
  "source": "string — who/what sends the data (use role name, not person name)",
  "destination": "string — who/what receives the data (use system/role name)",
  "data": "string — what data is transferred",
  "data_elements": ["array of specific data items e.g. PAN, Mobile Number"],
  "channel": "string — how it moves (API, manual, email, phone, etc.)",
  "evidence": "string — exact quote from the text that supports this flow",
  "evidence_timestamp": "string — timestamp from the transcript e.g. 00:02:31",
  "evidence_speaker": "string — who said it (person name)",
  "evidence_speaker_role": "string — their role (interviewer/interviewee/analyst)",
  "source_file": "string — filename where this evidence was found"
}
```

Rules:
1. You MUST only infer flows supported by evidence in the text. Do NOT hallucinate.
2. Every flow MUST have evidence_timestamp and evidence_speaker from the transcript.
3. Use role/title names for source/destination, NOT person names (e.g. "Customer Care Agent" not "Nikhil Joshi").
4. Return ONLY a valid JSON array. No markdown fences, no explanation text."""


class DataFlowAgent:

    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}
        self.client = get_llm_client(self.ai_config)
        self.model = self.ai_config.get("model") or "claude-3-5-sonnet-20241022"

    def extract(self, text_chunks, actors=None, systems=None, data_elements=None, structured_context=None):
        """
        Infer data flows from text using LLM reasoning.

        Args:
            text_chunks: list of text strings
            actors: list of known actor names
            systems: list of known system names
            data_elements: list of known data elements
            structured_context: formatted string with timestamps and speakers

        Returns:
            list of flow dicts with evidence provenance
        """
        # Prefer structured context with timestamps if available
        text_body = structured_context if isinstance(structured_context, str) else chr(10).join(text_chunks[:50])

        context = f"""Known actors: {json.dumps(actors or [])}
Known systems: {json.dumps(systems or [])}
Known data elements: {json.dumps(data_elements or [])}

--- STRUCTURED TRANSCRIPT (with timestamps) ---
{text_body}"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context}]
            )
            content = response.content[0].text.strip()
            
            # Clean up the response
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                content = content.rsplit("```", 1)[0]
            
            # Try to parse JSON directly first
            try:
                flows = json.loads(content)
            except json.JSONDecodeError as je:
                # If that fails, try to repair truncated JSON
                from utils.llm_adapter import _repair_truncated_json
                repaired = _repair_truncated_json(content)
                logger.warning(f"DataFlowAgent JSON error, attempting repair: {je}")
                flows = json.loads(repaired)
            
            # Validate we got a list
            if not isinstance(flows, list):
                logger.error(f"DataFlowAgent expected list, got {type(flows)}")
                return []
                
            logger.info(f"DataFlowAgent extracted {len(flows)} flows")
            return flows
            
        except json.JSONDecodeError as je:
            logger.error(f"DataFlowAgent JSON parsing failed: {je}")
            logger.error(f"Content preview: {content[:500]}...")
            return []
        except Exception as e:
            logger.error(f"DataFlowAgent failed: {e}")
            return []
