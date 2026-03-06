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

SCHEMA_ONE_PROMPT = """You are a Senior Data Protection and Systems Analyst performing a Privacy Impact Assessment. Your job is to read the provided source text AND the pre-extracted structured pipeline output to generate a comprehensive Compliance Schema (Schema-1) enriched with data privacy metadata.

## CONTEXT PROVIDED
1. SOURCE TRANSCRIPT: The raw interview or field notes.
2. PIPELINE OUTPUT: The already extracted actors, systems, data_elements, and flows.

## INSTRUCTIONS
Align your Schema-1 nodes and flows exactly with the names provided in the PIPELINE OUTPUT, but ENRICH them with exhaustive compliance metadata (retention, legal basis, classification).

### Nodes
Identify every entity in the system:
- **EXTERNAL_ENTITY**: People, departments, external systems, third parties (use the "actors" from pipeline output).
- **PROCESS**: Any action, verb, logic step.
- **DATA_STORE**: Databases, SaaS platforms (use the "systems" from pipeline output).

For each node, extract:
- **data_elements**: An array of distinct data categories this node handles. 
  - `name`: Use data element names from the pipeline output where possible.
  - `classification`: One of "Public", "Internal", "Confidential", "PII/Sensitive", "Special Category".
  - `purpose`: Why this data is collected/processed.
  - `retention_period`: How long data is kept.
  - `legal_basis`: Legal basis for processing.
  - `storage_location`: Where this data is stored.
  - `owner`: Responsible department or role.

### Flows
Map out the data flow between Nodes:
- **source** and **target**: Must reference valid node IDs.
- Follow the flows from the PIPELINE OUTPUT but add transfer_mechanism and cross_border checks.

## STRICT CONSTRAINTS
1. Node IDs must be unique strings prefixed by type: ext_, proc_, ds_.
2. `type` must be exactly one of: "EXTERNAL_ENTITY", "PROCESS", "DATA_STORE".
3. Every flow source and target must reference a valid node ID.
4. `bi_directional` must be a boolean.
5. `classification` must be strictly an enum value.
6. Use "Not specified" if details are missing. DO NOT HALLUCINATE.
"""

DATA_INVENTORY_PROMPT = """You are a Data Privacy Analyst building a Data Mapping and Inventory table from a Schema-1 JSON.
The Schema-1 already contains enriched data_elements on each node and flow. Your job is to:
1. Deduplicate and consolidate all data_elements across all nodes into a single flat table.
2. If the same data category appears on multiple nodes, merge them — pick the most specific/complete values.
3. Ensure every distinct data category gets its own row.

For each row, extract:
- **data_category**: The consolidated name.
- **description**: Detailed description. Combine from multiple nodes if needed.
- **purpose**: The primary purpose(s) for processing.
- **data_owner**: The department or role primarily responsible.
- **storage_location**: Where the data is stored.
- **data_classification**: The highest applicable classification level.
- **retention_period**: How long the data is retained.
- **legal_basis**: The legal basis for processing.

## RULES
- Generate as many rows as there are distinct data categories.
- Be thorough — DO NOT skip any data_elements found in the schema.
- When consolidating, prefer the most specific and complete values.
"""

class SchemaGeneratorAgent:
    def __init__(self):
        Config.validate()
        self.client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        self.model = Config.CLAUDE_MODEL

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
