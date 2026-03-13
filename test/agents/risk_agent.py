from utils.llm_adapter import get_llm_client
"""
RiskAnalysisAgent — Uses Anthropic Claude to perform deep privacy risk
analysis on structured data, enriching deterministic risk detection.

Enhanced with JSON prompting: requires timestamp, speaker, and
source_file evidence for every identified risk.
"""
import json
import anthropic
from config import Config
from utils.logger import setup_logger

logger = setup_logger("RiskAgent")

SYSTEM_PROMPT = """You are a senior privacy and compliance officer. Given structured transcript text with timestamps and speaker information, identify ALL privacy and data protection risks.

Context provided:
- Known data elements (PII, financial data)
- Known systems in use
- Pre-detected risks from deterministic analysis
- Structured text with [timestamp] Speaker (role) [source_file]: message format

For each risk you MUST return a JSON object with EXACTLY these fields:

```json
{
  "risk_name": "string — short descriptive name",
  "severity": "string — one of: critical, high, medium, low",
  "category": "string — one of: data_exposure, access_control, retention, transfer, consent, security, compliance",
  "description": "string — detailed explanation of the risk",
  "evidence": "string — exact quote from the text supporting this finding",
  "evidence_timestamp": "string — timestamp from the transcript e.g. 00:07:36",
  "evidence_speaker": "string — who revealed this risk (person name)",
  "evidence_speaker_role": "string — their role (interviewer/interviewee/analyst)",
  "source_file": "string — filename where this evidence was found",
  "affected_systems": ["array of system names affected by this risk"],
  "affected_data_elements": ["array of data elements at risk"],
  "recommendation": "string — remediation suggestion"
}
```

Rules:
1. You MUST only identify risks supported by evidence in the text. Do NOT hallucinate.
2. Every risk MUST have evidence_timestamp and evidence_speaker from the transcript.
3. Return ONLY a valid JSON array. No markdown fences, no explanation text."""


class RiskAnalysisAgent:

    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}
        self.client = get_llm_client(self.ai_config)
        self.model = self.ai_config.get("model") or "claude-3-5-sonnet-20241022"

    def analyze(self, text_chunks, data_elements=None, systems=None, deterministic_risks=None, structured_context=None):
        """
        Perform deep risk analysis using LLM reasoning.

        Args:
            text_chunks: list of text strings
            data_elements: list of known data elements
            systems: list of known system names
            deterministic_risks: list of pre-detected risk dicts
            structured_context: formatted string with timestamps and speakers

        Returns:
            list of enriched risk dicts with evidence provenance
        """
        # Prefer structured context with timestamps if available
        text_body = structured_context if isinstance(structured_context, str) else chr(10).join(text_chunks[:50])

        context = f"""Known data elements: {json.dumps(data_elements or [])}
Known systems: {json.dumps(systems or [])}
Pre-detected risks: {json.dumps(deterministic_risks or [])}

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
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                content = content.rsplit("```", 1)[0]
            risks = json.loads(content)
            logger.info(f"RiskAgent identified {len(risks)} risks")
            return risks
        except Exception as e:
            logger.error(f"RiskAgent failed: {e}")
            return []
