import anthropic
import json
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

from config import Config
from utils.logger import setup_logger

logger = setup_logger("SchemaGenerator")

# ==========================================
# PYDANTIC MODELS: SCHEMA 1
# ==========================================

class ClassificationEnum(str, Enum):
    PUBLIC = "Public"
    INTERNAL = "Internal"
    CONFIDENTIAL = "Confidential"
    PII = "PII/Sensitive"
    SPECIAL = "Special Category"

class LegalBasisEnum(str, Enum):
    CONSENT = "Consent"
    LEGAL_OBLIGATION = "Legal obligation"
    LEGITIMATE_INTEREST = "Legitimate interest"
    CONTRACT = "Contract"
    NOT_SPECIFIED = "Not specified"
    
class IntegrationDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    BIDIRECTIONAL = "bidirectional"

class DataElement(BaseModel):
    name: str
    description: str
    classification: ClassificationEnum
    purpose: str
    retention_period: str
    legal_basis: LegalBasisEnum
    storage_location: str
    owner: str

class SubProcess(BaseModel):
    name: str
    description: str
    routing: str

class Integration(BaseModel):
    system: str
    type: str
    direction: IntegrationDirection

class SchemaNode(BaseModel):
    id: str = Field(..., description="Unique ID prefixed by ext_, proc_, or ds_")
    type: str = Field(..., description="EXTERNAL_ENTITY, PROCESS, or DATA_STORE")
    name: str
    description: str
    data_elements: List[DataElement]
    
    # Process specific fields
    sub_processes: Optional[List[SubProcess]] = None
    sla: Optional[str] = None
    
    # Data Store specific fields
    integrations: Optional[List[Integration]] = None
    
    # All nodes can have references
    reference_documents: Optional[List[str]] = None

class Flow(BaseModel):
    source: str
    target: str
    label: str
    data_elements: List[str]
    bi_directional: bool
    transfer_mechanism: str
    cross_border: Optional[bool] = None

class SchemaMeta(BaseModel):
    project_name: str
    vertical_name: str
    generated_at: str

class SchemaOneOutput(BaseModel):
    meta: SchemaMeta
    nodes: List[SchemaNode]
    flows: List[Flow]

# ==========================================
# PYDANTIC MODELS: DATA INVENTORY
# ==========================================

class DataMappingRowOutput(BaseModel):
    data_category: str
    description: str
    purpose: str
    data_owner: str
    storage_location: str
    data_classification: str
    retention_period: str
    legal_basis: str

class DataInventoryOutput(BaseModel):
    inventory: List[DataMappingRowOutput]

# ==========================================
# SYSTEM PROMPTS
# ==========================================
SCHEMA_ONE_PROMPT = """You are a Senior Data Protection and Systems Analyst performing a Privacy Impact Assessment. Your job is to read the provided interview transcript(s) and extract a comprehensive Data Flow Diagram (DFD) logic model enriched with data privacy metadata and process details.

## EXTRACTION RULES

### Nodes
Identify every entity in the system:
- **EXTERNAL_ENTITY**: People, departments, external systems, third parties, regulators, customers, employees.
- **PROCESS**: Any action, verb, logic step, workflow, automated task, or manual procedure that touches personal data.
- **DATA_STORE**: Databases, file systems, archives, cloud storage, SaaS platforms, email inboxes, spreadsheets, paper records.

For each node, extract:
- **data_elements**: An array of distinct data categories that this node handles. Each data element should include:
  - `name`: The data category name (e.g., "Employee PII", "Customer Financial Records", "Call Recordings").
  - `description`: What exactly this data contains.
  - `classification`: One of "Public", "Internal", "Confidential", "PII/Sensitive", "Special Category".
  - `purpose`: Why this data is collected/processed by this node.
  - `retention_period`: How long data is kept (e.g., "7 years", "Until account deletion", "As required by law", "Not specified").
  - `legal_basis`: Legal basis for processing (e.g., "Consent", "Legal obligation", "Legitimate interest", "Contract", "Not specified").
  - `storage_location`: Where this data is stored (e.g., "Salesforce CRM", "AWS S3", "On-premise server", "Not specified").
  - `owner`: The department or role responsible (e.g., "HR Department", "IT Security", "Operations Team", "Not specified").

For **PROCESS** nodes, additionally extract:
- **sub_processes**: An array of sub-steps, branches, or categories within this process. Each sub-process should include:
  - `name`: The sub-step or category name (e.g., "IVR - New Loan Inquiry", "Case Category: Query").
  - `description`: What happens in this sub-step.
  - `routing`: Where the flow goes after this sub-step (e.g., "Transferred to Sales Team", "Resolved on call", "Not specified").
- **sla**: Service Level Agreement or turnaround time, if mentioned (e.g., "48 hours", "2 business days", "Real-time", "Not specified").

For **DATA_STORE** nodes, additionally extract:
- **integrations**: An array of other systems this data store integrates with. Each integration should include:
  - `system`: The name of the connected system (e.g., "Salesforce", "Ameyo IVR").
  - `type`: How they connect (e.g., "API", "File sync", "Manual entry", "Real-time sync", "Not specified").
  - `direction`: "inbound", "outbound", or "bidirectional".

For **all nodes**, optionally extract:
- **reference_documents**: An array of policy documents, SOPs, or matrices mentioned in relation to this node (e.g., "V2 Customer Care SOP", "Escalation Matrix", "Data Retention Policy").

### Flows
Identify every data flow — information moving from one node to another:
- **source** and **target**: Must reference valid node IDs.
- **label**: A human-readable description of what data is moving.
- **data_elements**: An array of data category names (strings) being transmitted in this flow.
- **bi_directional**: Whether data flows both ways.
- **transfer_mechanism**: How the data moves (e.g., "API", "Manual entry", "Email", "File transfer", "Automated sync", "Not specified").
- **cross_border**: Whether this flow involves cross-border data transfer (true/false/null if unknown).

## OUTPUT FORMAT
You must output strictly valid JSON conforming to this structure:
{
  "meta": {
    "project_name": "...",
    "vertical_name": "...",
    "generated_at": "..."
  },
  "nodes": [
    {
      "id": "proc_01",
      "type": "PROCESS",
      "label": "Customer Care",
      "description": "Handles inbound customer queries via IVR",
      "data_elements": [
        {
          "name": "Customer Query Records",
          "description": "Call details, query type, resolution status",
          "classification": "PII/Sensitive",
          "purpose": "Customer service and query resolution",
          "retention_period": "Not specified",
          "legal_basis": "Contract",
          "storage_location": "CRM System",
          "owner": "Customer Service"
        }
      ],
      "sub_processes": [
        {
          "name": "Unregistered Caller - New Loan",
          "description": "Call transferred to Sales team for new loan inquiry",
          "routing": "Transferred to Sales Team"
        },
        {
          "name": "Registered Caller - EMI Queries",
          "description": "EMI related queries from registered customers",
          "routing": "Resolved on call"
        }
      ],
      "sla": "48 hours",
      "reference_documents": ["V2 Customer Care SOP"]
    },
    {
      "id": "ds_01",
      "type": "DATA_STORE",
      "label": "Salesforce CRM",
      "description": "Central CRM system for customer data",
      "data_elements": [...],
      "integrations": [
        {
          "system": "Ameyo IVR",
          "type": "Real-time sync",
          "direction": "bidirectional"
        }
      ],
      "reference_documents": []
    }
  ],
  "flows": [
    {
      "id": "flow_01",
      "source": "ext_01",
      "target": "proc_01",
      "label": "Inbound customer call data",
      "data_elements": ["Customer Query Records"],
      "bi_directional": false,
      "transfer_mechanism": "IVR System",
      "cross_border": false
    }
  ]
}

## STRICT CONSTRAINTS
1. Node IDs must be unique strings prefixed by type: ext_XX, proc_XX, ds_XX.
2. `type` must be exactly one of: "EXTERNAL_ENTITY", "PROCESS", "DATA_STORE".
3. Every flow source and target must reference a valid node ID.
4. `bi_directional` must be a boolean.
5. `classification` must be one of: "Public", "Internal", "Confidential", "PII/Sensitive", "Special Category".
6. Be EXHAUSTIVE — extract every data element, process, sub-process, and flow mentioned or implied in the transcript.
7. Capture ALL branching logic, IVR options, case categories, and routing rules as sub_processes.
8. If a detail is not explicitly stated in the transcript, use "Not specified" rather than guessing.
9. Return ONLY valid JSON, no markdown, no explanation, no code fences.
"""

DATA_INVENTORY_PROMPT = """You are a Data Privacy Analyst building a Data Mapping and Inventory table from a Schema-1 JSON.

The Schema-1 already contains enriched data_elements on each node and flow. Your job is to:
1. Deduplicate and consolidate all data_elements across all nodes and flows into a single flat table.
2. If the same data category appears on multiple nodes, merge them — pick the most specific/complete values.
3. Ensure every distinct data category gets its own row.

For each row, output:
- **data_category**: The consolidated name of the data category.
- **description**: Detailed description of what data this includes. Combine from multiple nodes if needed.
- **purpose**: The primary purpose(s) for processing this data. Combine if multiple purposes exist.
- **data_owner**: The department or role primarily responsible. If multiple owners, list the primary one.
- **storage_location**: Where the data is stored. If stored in multiple places, list all (comma-separated).
- **data_classification**: The highest applicable classification level (Public < Internal < Confidential < PII/Sensitive < Special Category).
- **retention_period**: How long the data is retained. Use the most specific value available.
- **legal_basis**: The legal basis for processing. If multiple bases, list the primary one.

## OUTPUT FORMAT
Output strictly valid JSON as an array of objects:
[
  {
    "data_category": "...",
    "description": "...",
    "purpose": "...",
    "data_owner": "...",
    "storage_location": "...",
    "data_classification": "...",
    "retention_period": "...",
    "legal_basis": "..."
  }
]

## RULES
- Generate as many rows as there are distinct data categories.
- Be thorough — DO NOT skip any data_elements found in the schema.
- When consolidating, prefer the most specific and complete values.
- Return ONLY valid JSON, no markdown, no explanation, no code fences.
"""

# ==========================================
# GENERATOR CLASS
# ==========================================

class SchemaGenerator:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        self.model = Config.CLAUDE_MODEL

    def generate_schema_one(self, combined_transcript: str) -> dict:
        """Executes Step 1: Generates the extensive JSON node/flow schema."""
        logger.info("Executing Schema-1 Generation LLM prompt...")
        
        user_prompt = f"--- BEGIN TRANSCRIPTS ---\n{combined_transcript}\n--- END TRANSCRIPTS ---"
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            temperature=0,
            system=SCHEMA_ONE_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[{
                "name": "generate_schema",
                "description": "Generates the exhaustive schema 1 node graph.",
                "input_schema": SchemaOneOutput.model_json_schema()
            }],
            tool_choice={"type": "tool", "name": "generate_schema"}
        )
        
        # Anthropic Tool Use response
        tool_call = next(c for c in response.content if c.type == "tool_use")
        return tool_call.input

    def generate_data_inventory(self, schema_one_dict: dict) -> List[dict]:
        """Executes Step 2: Flattens Schema-1 into Data Mapping Rows."""
        logger.info("Executing Data Inventory Generation LLM prompt...")
        
        schema_str = json.dumps(schema_one_dict, indent=2)
        user_prompt = f"--- BEGIN SCHEMA-1 ---\n{schema_str}\n--- END SCHEMA-1 ---"
        
        # Try up to 2 times — LLM sometimes returns empty on first attempt
        for attempt in range(1, 3):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    temperature=0,
                    system=DATA_INVENTORY_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                    tools=[{
                        "name": "generate_inventory",
                        "description": "Generates the flattened inventory array.",
                        "input_schema": DataInventoryOutput.model_json_schema()
                    }],
                    tool_choice={"type": "tool", "name": "generate_inventory"}
                )
                
                tool_call = next((c for c in response.content if c.type == "tool_use"), None)
                if tool_call is None:
                    logger.warning(f"Data inventory attempt {attempt}: LLM did not return a tool_use block")
                    continue

                rows = tool_call.input.get("inventory", [])
                if rows:
                    logger.info(f"Data inventory generated with {len(rows)} rows (attempt {attempt})")
                    return rows
                else:
                    logger.warning(f"Data inventory attempt {attempt}: LLM returned empty inventory")
            except Exception as e:
                logger.error(f"Data inventory attempt {attempt} failed: {e}")

        # Fallback: extract rows directly from Schema-1 data_elements
        logger.warning("LLM inventory generation failed — extracting from Schema-1 data_elements as fallback")
        return self._fallback_inventory(schema_one_dict)

    def _fallback_inventory(self, schema_one_dict: dict) -> List[dict]:
        """Extract data mapping rows directly from Schema-1 nodes' data_elements."""
        seen = set()
        rows = []
        for node in schema_one_dict.get("nodes", []):
            for de in node.get("data_elements", []):
                name = de.get("name", "Unknown")
                if name in seen:
                    continue
                seen.add(name)
                rows.append({
                    "data_category": name,
                    "description": de.get("description", ""),
                    "purpose": de.get("purpose", ""),
                    "data_owner": de.get("owner", ""),
                    "storage_location": de.get("storage_location", ""),
                    "data_classification": de.get("classification", ""),
                    "retention_period": de.get("retention_period", ""),
                    "legal_basis": de.get("legal_basis", ""),
                })
        logger.info(f"Fallback inventory: extracted {len(rows)} rows from Schema-1 data_elements")
        return rows
