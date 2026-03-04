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
    
