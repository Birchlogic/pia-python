from pydantic import BaseModel, Field
from typing import List, Optional

class ExtractedEntity(BaseModel):
    name: str
    type: str = Field(..., description="System, Department, Third Party, etc.")
    description: Optional[str] = None

class DataItem(BaseModel):
    data_type: str = Field(..., description="PII, Financial, Recording, etc.")
    source: str
    destination: str
    protection_level: str

class Process(BaseModel):
    name: str
    description: str
    involved_entities: List[str]

class Risk(BaseModel):
    title: str
    description: str
    impact: str
    likelihood: str

class ComplianceGap(BaseModel):
    requirement: str
    observation: str
    gap_description: str

class ExtractedTranscriptData(BaseModel):
    entities: List[ExtractedEntity] = []
    data_inventory: List[DataItem] = []
    processes: List[Process] = []
    risks: List[Risk] = []
    compliance_gaps: List[ComplianceGap] = []
