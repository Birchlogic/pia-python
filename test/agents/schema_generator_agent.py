from utils.llm_adapter import get_llm_client
import json
from typing import List, Optional
from enum import Enum
from pydantic import BaseModel, Field
import anthropic

from config import Config
from utils.logger import setup_logger

logger = setup_logger("SchemaGeneratorAgent")

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
    name: str = Field(..., description="The name of the data element.")
    description: str = Field(..., description="Description of the data element.")
    classification: ClassificationEnum = Field(..., description="Data classification level.")
    purpose: str = Field(..., description="Purpose of processing.")
    retention_period: str = Field(..., description="Retention period.")
    legal_basis: LegalBasisEnum = Field(..., description="Legal basis for processing.")
    storage_location: str = Field(..., description="Storage location.")
    owner: str = Field(..., description="Data owner role or department.")

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
You must output strictly valid JSON.

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
Output strictly valid JSON as an array of objects.

## RULES
- Generate as many rows as there are distinct data categories.
- Be thorough — DO NOT skip any data_elements found in the schema.
- When consolidating, prefer the most specific and complete values.
- Return ONLY valid JSON, no markdown, no explanation, no code fences.
"""

class SchemaGeneratorAgent:
    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {}
        self.client = get_llm_client(self.ai_config)
        self.model = self.ai_config.get("model") or "claude-3-5-sonnet-20241022"

    def run(self, raw_text: str, pipeline_output: dict):
        """Runs both Schema-1 and Data Inventory generation dynamically."""
        logger.info("  [9a] Generating Compliance Schema-1...")
        schema_one = self.generate_schema_one(raw_text, pipeline_output)
        
        logger.info("  [9b] Generating Flattened Data Inventory...")
        if schema_one:
            inventory = self.generate_data_inventory(schema_one)
            return {"schema": schema_one, "inventory": inventory}
        return {"schema": None, "inventory": []}

    def generate_schema_one(self, raw_text: str, pipeline_output: dict) -> dict:
        user_prompt = (
            f"--- BEGIN TRANSCRIPTS ---\n{raw_text}\n--- END TRANSCRIPTS ---\n\n"
            f"--- BEGIN PIPELINE OUTPUT (Use as reference for entities/flows) ---\n"
            f"{json.dumps(pipeline_output, indent=2)}\n--- END PIPELINE OUTPUT ---"
        )
        
        try:
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
            tool_call = next(c for c in response.content if c.type == "tool_use")
            return tool_call.input
        except Exception as e:
            logger.error(f"Error generating Schema-1: {e}")
            return {}

    def generate_data_inventory(self, schema_one_dict: dict) -> List[dict]:
        schema_str = json.dumps(schema_one_dict, indent=2)
        user_prompt = f"--- BEGIN SCHEMA-1 ---\n{schema_str}\n--- END SCHEMA-1 ---"
        
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
            tool_call = next(c for c in response.content if c.type == "tool_use")
            return tool_call.input.get("inventory", [])
        except Exception as e:
            logger.error(f"Error generating Data Inventory: {e}")
            return []
