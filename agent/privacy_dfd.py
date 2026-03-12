from utils.llm_adapter import get_llm_client
"""
Privacy DFD Agent
Generates Privacy-focused Data Flow Diagrams per department
and a Master cross-department Privacy DFD.

Style reference:
- Rows = Actors (HR, Employees, Vendors/Partners, etc.)
- Columns = Data Lifecycle Phases (Collection, Processing, Storage, Sharing, External Transfer)
- Cells = Personal data elements flowing at each stage
- Separate swimlanes highlight privacy risks in red/amber
"""

import anthropic
import json
from typing import List, Dict, Any
from config import Config
from utils.logger import setup_logger
from models.extracted_data import ExtractedTranscriptData

logger = setup_logger("PrivacyDFDAgent")

PRIVACY_DFD_SYSTEM_PROMPT = """
You are a Senior Privacy Consultant and Data Protection Officer (DPO) with deep expertise in
DPDPA 2023, GDPR, and ISO 27001. You specialize in creating Privacy Data Flow Diagrams (Privacy DFDs)
for compliance audits.

A Privacy DFD is NOT a technical system architecture diagram. It maps PERSONAL DATA flows
organized by DATA LIFECYCLE PHASE (Collection, Processing, Storage, Sharing, External Transfer).

You must identify:
1. All actors (internal roles, external entities, third parties)
2. Personal data categories at each lifecycle phase
3. Legal basis for processing (Consent / Contract / Legitimate Interest / Legal Obligation)
4. Retention periods
5. Data classification (PII / Sensitive PII / Non-PII / Restricted)
6. Risk level (High / Medium / Low) — expressed ONLY via classDef styling, not text

Output: Mermaid 8.8.0 diagram + privacy data mapping table + risk summary.
"""

DEPARTMENT_DFD_PROMPT = """
Generate a Privacy DFD for the {department} department.

Extracted Data:
{extracted_data}

Historical Context:
{context}

---
## Section 1: Mermaid Privacy DFD

STRICT MERMAID 8.8.0 RULES — FOLLOW EXACTLY OR THE DIAGRAM WILL FAIL:

RULE 1 - Graph type: Use `graph LR` ONLY. NEVER use `flowchart`.
RULE 2 - Subgraphs: NEVER put `direction` inside a subgraph. It is not supported.
RULE 3 - Node shape: ALL nodes MUST use plain rectangle ONLY: `NodeID["Label"]`
         - BANNED shapes: [(...)  [/text/]  ([text])  ((text))  {{text}}
         - ONLY `["text"]` is allowed
RULE 4 - Label characters: The text inside "..." MUST NOT contain ANY of:
         - Square brackets `[` or `]`  — CAUSES PARSER FAILURE
         - Colon `:`  → use ` - ` dash instead
         - Plus sign `+` → use `and` instead
         - Parentheses `(` or `)` → remove or rephrase
         - Arrow chars → use `to` instead
         - Ampersand `&` → use `and` instead
         - Slash `/` in text → use `or` instead
RULE 5 - No emojis anywhere.
RULE 6 - Node type prefix: Use period-suffix notation WITHOUT brackets:
         - External actors: start label with "EXT. "
         - Internal teams:  start label with "INT. "
         - Data stores:     start label with "DS. "
         - Third-party:     start label with "TP. "
         Example: C1["EXT. Customers - Voice calls via IVR"]
RULE 7 - Risk is shown ONLY via classDef color, never in label text.
RULE 8 - Node IDs: short alphanumeric only: C1, P2, S3, SH1, T1 etc.
RULE 9 - Connections: Connect INDIVIDUAL NODES across subgraphs ONLY.
         NEVER connect subgraph IDs to each other.
         BAD:  COLLECTION --> PROCESSING
         GOOD: C2 --> P1
RULE 10 - classDef class names (copy verbatim):
          highRisk, medRisk, lowRisk, dataStore, extTransfer, collection

CORRECT EXAMPLE (follow this structure exactly):

```mermaid
graph LR

    subgraph COLLECTION["DATA COLLECTION"]
        C1["EXT. Customers - Voice calls via IVR"]
        C2["EXT. Customers - WhatsApp messages with PAN images"]
        C3["INT. Compliance Team - Outbound call responses"]
    end

    subgraph PROCESSING["DATA PROCESSING"]
        P1["INT. Customer Care Agents - Identity verification - Contract"]
        P2["INT. Salesforce CRM - Case management - Contract"]
        P3["INT. Quality Team - Call auditing - Legitimate Interest"]
    end

    subgraph STORAGE["DATA STORAGE"]
        S1["DS. Salesforce - Unmasked PII and Financial Data - Indefinite"]
        S2["DS. Ameyo Cloud - Call recordings - 2 or more years"]
        S3["DS. OneDrive Personal - Compliance data - 1.5 or more years"]
    end

    subgraph SHARING["INTERNAL SHARING"]
        SH1["INT. Customer Care to Sales - New loan inquiries"]
        SH2["INT. Compliance to Field Audit - Monthly reports"]
    end

    subgraph TRANSFER["EXTERNAL TRANSFER"]
        T1["TP. Ameyo Vendor - Call recordings - Unverified India hosting"]
        T2["TP. Meta WhatsApp - Customer messages - Global infrastructure"]
    end

    C1 --> P1
    C2 --> P1
    C3 --> P3
    P1 --> S1
    P2 --> S1
    P3 --> S2
    P1 --> SH1
    P3 --> SH2
    SH1 --> T1
    SH2 --> T2

    classDef highRisk fill:#ffebee,stroke:#c62828,stroke-width:2px,color:#b71c1c
    classDef medRisk fill:#fff8e1,stroke:#f57c00,stroke-width:2px,color:#e65100
    classDef lowRisk fill:#e8f5e9,stroke:#388e3c,stroke-width:2px,color:#1b5e20
    classDef dataStore fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px,color:#4a148c
    classDef extTransfer fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1
    classDef collection fill:#e0f7fa,stroke:#006064,stroke-width:2px,color:#004d40

    class C1,C2 collection
    class C3 medRisk
    class P1,P3 highRisk
    class P2 medRisk
    class S1,S2 highRisk
    class S3 dataStore
    class SH1 lowRisk
    class SH2 medRisk
    class T1,T2 extTransfer
```

Now replace placeholder data above with REAL data from the {department} department transcripts.
Ensure EVERY node label strictly follows Rules 4 and 6.

---
## Section 2: Privacy Data Mapping and Inventory Table

| S.No | Data Category | Description | Purpose | Legal Basis | Data Owner | Storage Location | Data Classification | Retention Period | Legal Obligation | Risk Level |
|------|--------------|-------------|---------|-------------|-----------|-----------------|--------------------|-----------------|--------------------|------------|

Classification: PII / Sensitive PII / Non-PII / Restricted
Legal Basis: Consent / Contract / Legitimate Interest / Legal Obligation
Risk Level: HIGH / MEDIUM / LOW (no emojis)

---
## Section 3: Privacy Risk Summary

For each top risk:
- Risk title
- Affected data subjects
- Risk description
- Applicable regulation (DPDPA / Aadhaar Act / IT Act)
- Recommended control

---
DO NOT hallucinate data. Base all findings on the transcript data only.
"""



MASTER_DFD_PROMPT = """
Generate a MASTER Privacy Data Flow Diagram: a cross-departmental view of personal data
flows across the ENTIRE organization.

All Department Privacy DFD Data:
{all_dept_data}

---
## Master Privacy DFD

Apply ALL same rules as department DFDs:
- `graph TD` ONLY
- ALL nodes use plain rectangles ["Label"]
- NO cylinder [(...)], NO emojis, NO special chars in labels
- Label text: use ` - ` instead of `:`, `and` instead of `+` or `&`, `to` instead of arrows
- Prefix tags: [EXT] [INT] [DS] [TP]
- Risk via classDef only

Each subgraph = one DEPARTMENT. Within it show key collection, processing, storage, sharing nodes.

```mermaid
graph TD

    subgraph CC["Customer Care Department"]
        CC1["[EXT] Customers - Voice and WhatsApp"]
        CC2["[INT] Agents - Identity verification - Contract"]
        CC3["[DS] Salesforce - PII and Financial - Indefinite"]
        CC1 --> CC2
        CC2 --> CC3
    end

    subgraph HR["HR Department"]
        HR1["[INT] HR Team - Employee onboarding"]
        HR2["[DS] HRMS - Employee records - As per policy"]
        HR1 --> HR2
    end

    CC3 -->|"shared records"| HR2

    classDef highRisk fill:#ffebee,stroke:#c62828,stroke-width:2px,color:#b71c1c
    classDef medRisk fill:#fff8e1,stroke:#f57c00,stroke-width:2px,color:#e65100
    classDef lowRisk fill:#e8f5e9,stroke:#388e3c,stroke-width:2px,color:#1b5e20
    classDef dataStore fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px,color:#4a148c
    classDef extTransfer fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1
    classDef collection fill:#e0f7fa,stroke:#006064,stroke-width:2px,color:#004d40

    class CC1 collection
    class CC2 medRisk
    class CC3,HR2 dataStore
    class HR1 lowRisk
```

Replace with REAL department data from the extracted summaries above.

## Master Data Mapping Summary

| Data Category | Departments Involved | Legal Basis | Classification | DPDPA Obligation | Risk Level |
|--------------|---------------------|-------------|----------------|-----------------|------------|

Risk Level: HIGH / MEDIUM / LOW (no emojis)

## Organization-Wide Privacy Risk Register

Top 10 enterprise-level privacy risks across all departments.
"""


class PrivacyDFDAgent:
    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}
        self.client = get_llm_client(self.ai_config)
        self.model = self.ai_config.get("model") or "claude-3-5-sonnet-20241022"

    def generate_department_dfd(
        self,
        department: str,
        extracted_data_list: List[ExtractedTranscriptData],
        context: str,
    ) -> str:
        logger.info(f"Generating Privacy DFD for department: {department}")

        # Consolidate all extracted data
        consolidated_data = self._consolidate_data(extracted_data_list)

        prompt = DEPARTMENT_DFD_PROMPT.format(
            department=department,
            extracted_data=consolidated_data.model_dump_json(indent=2),
            context=context or "No prior context available.",
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8000,
                temperature=0,
                system=PRIVACY_DFD_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text

        except Exception as e:
            logger.error(f"Error generating department Privacy DFD: {e}")
            raise

    def generate_master_dfd(self, all_dept_data: Dict[str, str]) -> str:
        logger.info("Generating Master Organization-Level Privacy DFD")

        # Summarize all department DFD data for the master view
        dept_summaries = "\n\n".join(
            [f"=== {dept} ===\n{dfd}" for dept, dfd in all_dept_data.items()]
        )

        prompt = MASTER_DFD_PROMPT.format(all_dept_data=dept_summaries)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8000,
                temperature=0,
                system=PRIVACY_DFD_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text

        except Exception as e:
            logger.error(f"Error generating Master Privacy DFD: {e}")
            raise

    def _consolidate_data(
        self, data_list: List[ExtractedTranscriptData]
    ) -> ExtractedTranscriptData:
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
