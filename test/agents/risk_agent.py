"""
RiskAnalysisAgent — Uses Anthropic Claude to perform deep privacy risk
analysis on structured data, enriching deterministic risk detection.
"""
import json
import anthropic
from config import Config
from utils.logger import setup_logger

logger = setup_logger("RiskAgent")

SYSTEM_PROMPT = """You are a senior privacy and compliance officer. Given structured text from interview transcripts or analyst field notes, identify ALL privacy and data protection risks.

Context provided:
- Known data elements (PII, financial data)
- Known systems in use
- Pre-detected risks from deterministic analysis

For each risk, provide:
- risk_name: short descriptive name
- severity: "critical", "high", "medium", "low"
- category: one of "data_exposure", "access_control", "retention", "transfer", "consent", "security", "compliance"
- description: detailed explanation of the risk
- evidence: exact text supporting this finding
- recommendation: remediation suggestion

You MUST only identify risks supported by evidence in the text. Do NOT hallucinate.

Return ONLY a valid JSON array. No markdown, no explanation."""


class RiskAnalysisAgent:

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        self.model = Config.CLAUDE_MODEL

    def analyze(self, text_chunks, data_elements=None, systems=None, deterministic_risks=None):
        """
        Perform deep risk analysis using LLM reasoning.

        Args:
            text_chunks: list of text strings
            data_elements: list of known data elements
            systems: list of known system names
            deterministic_risks: list of pre-detected risk dicts

        Returns:
            list of enriched risk dicts
        """
        context = f"""Known data elements: {json.dumps(data_elements or [])}
Known systems: {json.dumps(systems or [])}
Pre-detected risks: {json.dumps(deterministic_risks or [])}

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
            risks = json.loads(content)
            logger.info(f"RiskAgent identified {len(risks)} risks")
            return risks
        except Exception as e:
            logger.error(f"RiskAgent failed: {e}")
            return []
