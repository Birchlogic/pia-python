from utils.llm_adapter import get_llm_client
"""
DFD Extractor Agent
Extracts structured DFD JSON from transcript data using an LLM.

Implements an agentic feedback loop:
1. Call LLM with extraction prompt
2. Validate result with DFDValidator
3. If score < 75, inject feedback into next prompt and retry (max 3 times)
4. Return best-scoring result
"""

import anthropic
import json
import re
from typing import Any, Dict, List, Optional

from config import Config
from utils.logger import setup_logger
from models.extracted_data import ExtractedTranscriptData
from agent.dfd_validator import validate_dfd, format_validation_report

logger = setup_logger("DFDExtractor")

MAX_RETRIES = 3


# ─────────────────────────────────────────────
# EXTRACTION SYSTEM PROMPT
# ─────────────────────────────────────────────
SYSTEM_PROMPT = """
You are a Privacy Data Architecture Expert specializing in Data Flow Diagrams (DFDs)
for regulatory compliance (DPDPA 2023, ISO 27001, GDPR).

Your task is to extract a structured DFD JSON object from compliance assessment transcripts.
The JSON captures:

1. ACTORS (include ONLY types that are evidenced in the transcript data):
   Possible actor types (include only if mentioned or implied in the data):
   - external: outside parties (e.g. customers, regulators) who PROVIDE or RECEIVE data
   - internal: internal departments, teams, or employees who PROCESS data
   - vendor: third-party technology vendors and partners
   NOTE: Do NOT invent actors that are not mentioned in the transcript.
   If only internal and vendor actors are present, do NOT add an external/customer actor.

2. BUSINESS PROCESSES: Within each actor, the distinct operations or sub-units
   that are ACTUALLY described in the transcript

3. DATA COLLECTION: For each business process, WHAT data is collected and FROM WHOM
   (list specific data elements mentioned in the transcript)

4. CENTRAL PROCESS: The main processing unit at the department level

5. DISPERSAL SINKS: Where processed data flows OUT to
   (other departments, vendors, automated systems)

6. STORAGE SYSTEMS: All systems where data is persisted
   (CRM, cloud drives, databases, local storage)

7. DATA FLOWS: Connections between sources, central process, and sinks
   (with color codes for visual arrow rendering)

8. CITATIONS: Exact verbatim quotes from the transcript proving the existence of
   actors, processes, data elements, or flows.

CRITICAL: Only extract information that is ACTUALLY PRESENT in the transcript data.
Do NOT hallucinate or invent actors, processes, or data elements not supported by the evidence.

OUTPUT: Return ONLY a valid JSON object. No markdown, no explanation.
"""


# ─────────────────────────────────────────────
# EXTRACTION PROMPT
# ─────────────────────────────────────────────
EXTRACTION_PROMPT = """
Analyze the following compliance assessment data and extract a complete DFD JSON object
for the {department} department.

Extracted Data from Transcripts:
{extracted_data}

Historical Context:
{context}

---
ACTOR TYPES — include ONLY those evidenced in the transcript data:
  - type "external" (id: "customers") — outside parties like customers, regulators
  - type "internal" (id: "internal")  — internal departments, teams, employees
  - type "vendor"   (id: "vendors")   — third-party vendors and partners
If no customers are mentioned, do NOT include the external actor. Same for the other types.

Return a JSON object with EXACTLY this structure:

{{
  "department": "{department}",
  "version": "1.0",
  "central_process": "<name of the main processing unit of this department>",
  "actors": [
    {{
      "id": "<customers|internal|vendors>",
      "name": "<Actor Category Name>",
      "type": "<external|internal|vendor>",
      "color": "<#fffde7 for external, #fce4ec for internal, #f1f8e9 for vendor>",
      "business_processes": [
        {{
          "id": "bp_<unique_id>",
          "name": "<Business Process Name>",
          "collection_sources": [
            {{
              "name": "<Source Name>",
              "data_elements": ["<element1>", "<element2>", ...]
            }}
          ]
        }}
      ]
    }}
  ],
  "dispersal_sinks": [
    {{
      "id": "sink_<unique_id>",
      "name": "<Destination Name>",
      "actor_id": "<customers|internal|vendors>",
      "color": "<hex color for this flow arrow>"
    }}
  ],
  "storage_systems": [
    {{
      "name": "<System Name e.g. Salesforce CRM>",
      "type": "<cloud|database|local>"
    }}
  ],
  "data_flows": [
    {{
      "from_id": "<bp_id or 'central_process'>",
      "to_id": "<bp_id or 'central_process' or sink_id>",
      "color": "<hex color>",
      "label": "<optional short label>"
    }}
  ],
  "citations": [
    {{
      "element_id": "<associated_id_like_bp_id_or_actor_id>",
      "element_name": "<name of the thing being cited>",
      "source_text": "<exact verbatim quote from transcript>",
      "source_section": "Interview Transcript",
      "source_type": "inferred"
    }}
  ]
}}

RULES:
- actors array should ONLY contain actor types that are evidenced in the transcript data
- Do NOT add external/customer actors if no customers are mentioned in the transcripts
- Do NOT add vendor actors if no vendors or third-party services are mentioned
- Do NOT add internal actors if no internal teams or employees are mentioned
- Every business_process MUST have at least one collection_source with data_elements
- dispersal_sinks MUST be assigned to the correct actor_id based on who receives the data
- data_flows: use "central_process" as the to_id for inbound flows and from_id for outbound flows
- Use distinct colors for different flow types (green, blue, purple, pink, red, teal)
- citations MUST include the exact `source_text` from the transcript to prove the data
- Do NOT hallucinate. Only use information ACTUALLY PRESENT in the transcript data.
- Return ONLY the JSON object. No markdown fences, no explanation text.

{feedback_section}
"""


class DFDExtractor:
    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}
        self.client = get_llm_client(self.ai_config)
        self.model = self.ai_config.get("model") or "claude-3-5-sonnet-20241022"

    def extract(
        self,
        department: str,
        extracted_data_list: List[ExtractedTranscriptData],
        context: str,
    ) -> Dict[str, Any]:
        """
        Extract DFD JSON with automatic validation + retry feedback loop.
        Returns the best-scoring DFD JSON object.
        """
        consolidated = self._consolidate(extracted_data_list)
        extracted_data_str = consolidated.model_dump_json(indent=2)
        context_str = context or "No prior context available."

        best_result = None
        best_score = -1
        feedback_section = ""

        for attempt in range(1, MAX_RETRIES + 1):
            logger.info(f"DFD extraction attempt {attempt}/{MAX_RETRIES}")

            prompt = EXTRACTION_PROMPT.format(
                department=department,
                extracted_data=extracted_data_str,
                context=context_str,
                feedback_section=feedback_section,
            )

            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4000,
                    temperature=0,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.content[0].text
                dfd_json = self._parse_json(raw)

                if dfd_json is None:
                    logger.warning(f"Attempt {attempt}: Could not parse JSON response")
                    feedback_section = self._build_feedback_section(
                        [], ["Response was not valid JSON. Return ONLY a JSON object."]
                    )
                    continue

                validation = validate_dfd(dfd_json)
                report = format_validation_report(validation)
                logger.info(f"Attempt {attempt} validation:\n{report}")

                if validation["score"] > best_score:
                    best_score = validation["score"]
                    best_result = dfd_json

                if validation["passed"]:
                    logger.info(f"DFD extraction PASSED on attempt {attempt} with score {best_score}")
                    return best_result

                # Build feedback for next retry
                feedback_section = self._build_feedback_section(
                    validation["breakdown"], validation["feedback"]
                )

            except Exception as e:
                logger.error(f"Attempt {attempt} error: {e}")
                feedback_section = self._build_feedback_section(
                    [], [f"Previous attempt errored: {str(e)[:200]}"]
                )

        logger.warning(
            f"DFD extraction completed with best score {best_score} after {MAX_RETRIES} attempts"
        )
        return best_result or self._fallback_dfd(department)

    def _parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse JSON from LLM output, handling markdown fences."""
        # Strip markdown fences if present
        text = text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        if match:
            text = match.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find first { ... } block
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    pass
        return None

    def _build_feedback_section(self, breakdown: dict, feedback: list) -> str:
        if not feedback:
            return ""
        lines = [
            "PREVIOUS ATTEMPT FEEDBACK (fix these issues in your next response):",
        ]
        for fb in feedback:
            lines.append(f"  - {fb}")
        return "\n".join(lines)

    def _consolidate(self, data_list: List[ExtractedTranscriptData]) -> ExtractedTranscriptData:
        consolidated = ExtractedTranscriptData()
        entities = {}
        data_inventory = []
        processes = {}
        risks = {}
        compliance_gaps = []
        for data in data_list:
            for e in data.entities:
                entities[e.name] = e
            data_inventory.extend(data.data_inventory)
            for p in data.processes:
                processes[p.name] = p
            for r in data.risks:
                risks[r.title] = r
            compliance_gaps.extend(data.compliance_gaps)
        consolidated.entities = list(entities.values())
        consolidated.data_inventory = data_inventory
        consolidated.processes = list(processes.values())
        consolidated.risks = list(risks.values())
        consolidated.compliance_gaps = compliance_gaps
        return consolidated

    def _fallback_dfd(self, department: str) -> Dict[str, Any]:
        """Return a minimal valid DFD structure if all retries fail."""
        return {
            "department": department,
            "version": "1.0",
            "central_process": f"{department} Department",
            "actors": [
                {
                    "id": "internal",
                    "name": "Internal Departments",
                    "type": "internal",
                    "color": "#fce4ec",
                    "business_processes": [],
                },
            ],
            "dispersal_sinks": [],
            "storage_systems": [],
            "data_flows": [],
            "citations": [],
        }
