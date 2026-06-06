"""SQLAlchemy ORM Models."""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean,
    Float, ForeignKey, create_engine
)
from sqlalchemy.orm import DeclarativeBase, relationship, synonym


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "devices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    hostname = Column(String(128), nullable=False, index=True)
    ip_address = Column(String(45), nullable=False)
    ip = synonym("ip_address")
    vendor = Column(String(64), default="cisco_ios")
    model = Column(String(128))
    username = Column(String(64))
    password_enc = Column(Text)
    port = Column(Integer, default=22)
    role = Column(String(64))
    site = Column(String(64))
    status = Column(String(32), default="unknown")
    cpu = Column(Integer, default=0)
    memory = Column(Integer, default=0)
    os_version = Column(String(128))
    last_seen = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(64))

    incidents = relationship("IncidentDevice", back_populates="device", lazy="dynamic")


class Incident(Base):
    __tablename__ = "incidents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(256), nullable=False)
    description = Column(Text)
    root_cause = Column(Text)
    resolution = Column(Text)
    protocols = Column(String(256))
    severity = Column(String(32), default="major")
    status = Column(String(32), default="active", index=True)
    business_impact = Column(Text)
    affected_users = Column(Integer, default=0)
    assigned_to = Column(String(64))
    affected_service = Column(String(128))
    ai_confidence = Column(Integer, default=0)
    workspace = Column(String(64))
    created_by = Column(String(64))
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    resolved_at = Column(DateTime)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    devices = relationship("IncidentDevice", back_populates="incident")


class IncidentDevice(Base):
    __tablename__ = "incident_devices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    incident = relationship("Incident", back_populates="devices")
    device = relationship("Device", back_populates="incidents")


class AIQuery(Base):
    __tablename__ = "ai_queries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    source = Column(String(64), default="user")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ChangeRequest(Base):
    __tablename__ = "change_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(256), nullable=False)
    status = Column(String(32), default="pending", index=True)
    risk = Column(String(32), default="low")
    implementation_date = Column(String(64))
    engineer = Column(String(64), default="netops")
    created_at = Column(DateTime, default=datetime.utcnow)


class ComplianceRule(Base):
    __tablename__ = "compliance_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    description = Column(Text)
    vendor = Column(String(64))
    severity = Column(String(32), default="low")
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class NetworkLink(Base):
    __tablename__ = "network_links"
    id = Column(Integer, primary_key=True, autoincrement=True)
    source_device = Column(String(128), nullable=False)
    destination_device = Column(String(128), nullable=False)
    link_type = Column(String(64))
    status = Column(String(32), default="unknown")
    bandwidth_mbps = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Telemetry(Base):
    __tablename__ = "telemetries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    metric_name = Column(String(64), nullable=False)
    value = Column(Float)
    unit = Column(String(32), default="")
    tags = Column(String(128))


class Change(Base):
    __tablename__ = "changes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(256), nullable=False)
    description = Column(Text)
    device = Column(String(128))
    change_type = Column(String(64))
    risk_level = Column(String(32), default="low")
    status = Column(String(32), default="pending", index=True)
    ai_risk_score = Column(Integer, default=0)
    ai_recommendation = Column(Text)
    rollback_plan = Column(Text)
    created_by = Column(String(64))
    approved_by = Column(String(64))
    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime)


class AutonomousAction(Base):
    __tablename__ = "autonomous_actions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(Text, nullable=False)
    device = Column(String(128))
    trigger = Column(Text)
    ai_confidence = Column(Integer, default=0)
    status = Column(String(32), default="pending", index=True)
    result = Column(Text)
    executed_by = Column(String(64), default="NetBrain AI")
    created_at = Column(DateTime, default=datetime.utcnow)
    executed_at = Column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user = Column(String(64), index=True)
    action = Column(String(128), nullable=False)
    resource = Column(String(256))
    detail = Column(Text)
    ip_address = Column(String(45))
    result = Column(String(32), default="success")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class KnowledgeDoc(Base):
    __tablename__ = "knowledge_docs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(256), nullable=False)
    vendor = Column(String(64), default="general")
    doc_type = Column(String(64), default="manual")
    content = Column(Text)
    chunk_hash = Column(String(64), unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class QueryLog(Base):
    __tablename__ = "query_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(Text)
    device_count = Column(Integer, default=0)
    ai_result = Column(Text)
    persona = Column(String(32))
    created_at = Column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(128))
    password_hash = Column(String(256))
    role = Column(String(32), default="readonly")
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
