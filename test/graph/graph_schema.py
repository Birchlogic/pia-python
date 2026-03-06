"""
Graph Schema — Pydantic models for Knowledge Graph nodes and edges.
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


class NodeType(str, Enum):
    EXTERNAL_ENTITY = "external_entity"
    SYSTEM = "system"
    ACTOR = "actor"
    DATA_STORE = "data_store"
    PROCESS = "process"


class FlowType(str, Enum):
    COLLECTION = "collection"
    PROCESSING = "processing"
    STORAGE = "storage"
    TRANSFER = "transfer"
    UNKNOWN = "unknown"


class SourceReference(BaseModel):
    source_document: str
    evidence: str = ""


class GraphNode(BaseModel):
    id: str
    name: str
    type: NodeType
    aliases: List[str] = Field(default_factory=list)
    data_elements: List[str] = Field(default_factory=list)
    risks: List[dict] = Field(default_factory=list)
    sources: List[SourceReference] = Field(default_factory=list)


class GraphEdge(BaseModel):
    source: str
    target: str
    data_elements: List[str] = Field(default_factory=list)
    flow_type: FlowType = FlowType.UNKNOWN
    channel: str = ""
    inferred: bool = False
    sources: List[SourceReference] = Field(default_factory=list)


class KnowledgeGraph(BaseModel):
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class DFDRenderPlan(BaseModel):
    layout: str = "left_to_right"
    levels: List[List[str]] = Field(default_factory=list)
