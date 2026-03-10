from sqlalchemy import Column, String, DateTime, JSON, Text, Integer
from datetime import datetime
from api.database import Base

class DFDSession(Base):
    __tablename__ = "dfd_sessions"

    session_id = Column(String, primary_key=True, index=True)
    department = Column(String, nullable=True)
    status = Column(String, default="pending", index=True)
    error_message = Column(Text, nullable=True)

    # Schema Generation outputs
    schema_one_json = Column(JSON, nullable=True)

    # DFD Generation outputs
    dfd_json = Column(JSON, nullable=True)
    privacy_dfd_md = Column(Text, nullable=True)
    
    # New processing meta
    processing_mode = Column(String, default="normal") # "normal", "rlm", or "aggressive_processing"
    
    # Enhanced Pipeline outputs
    actors_json = Column(JSON, nullable=True)
    systems_json = Column(JSON, nullable=True)
    data_elements_json = Column(JSON, nullable=True)
    flows_json = Column(JSON, nullable=True)
    risks_json = Column(JSON, nullable=True)
    compliance_schema_json = Column(JSON, nullable=True)
    verification_report_json = Column(JSON, nullable=True)
    interactive_html = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class DataMappingRow(Base):
    __tablename__ = "data_mapping_rows"

    id = Column(String, primary_key=True)
    session_id = Column(String, index=True, nullable=False)
    s_no = Column(Integer, nullable=False)
    data_category = Column(String, nullable=False)
    description = Column(String, nullable=False)
    purpose = Column(String, nullable=False)
    data_owner = Column(String, nullable=False)
    storage_location = Column(String, nullable=False)
    data_classification = Column(String, nullable=False)
    retention_period = Column(String, nullable=False)
    legal_basis = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class KnowledgeGraphNode(Base):
    __tablename__ = "kg_nodes"

    id = Column(String, primary_key=True)
    session_id = Column(String, index=True, nullable=False)
    node_id = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    aliases = Column(JSON, nullable=True)
    data_elements = Column(JSON, nullable=True)
    risks = Column(JSON, nullable=True)
    sources = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class KnowledgeGraphEdge(Base):
    __tablename__ = "kg_edges"

    id = Column(String, primary_key=True)
    session_id = Column(String, index=True, nullable=False)
    source_node = Column(String, index=True, nullable=False)
    target_node = Column(String, index=True, nullable=False)
    data_elements = Column(JSON, nullable=True)
    flow_type = Column(String, nullable=True)
    channel = Column(String, nullable=True)
    inferred = Column(Integer, default=0) # boolean via integer
    sources = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class InteractiveDFD(Base):
    __tablename__ = "interactive_dfds"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, default="Untitled DFD")
    nodes = Column(JSON, nullable=False, default=list)
    edges = Column(JSON, nullable=False, default=list)
    levels = Column(JSON, nullable=False, default=list)
    pipeline_docs = Column(JSON, nullable=True, default=dict)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)