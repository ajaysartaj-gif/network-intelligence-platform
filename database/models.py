from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True)
    hostname = Column(String, unique=True, nullable=False)
    ip_address = Column(String, nullable=False)
    vendor = Column(String, nullable=False)
    model = Column(String, nullable=True)
    role = Column(String, nullable=True)
    site = Column(String, nullable=True)
    os_version = Column(String, nullable=True)
    status = Column(String, nullable=False, default="healthy")
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    status = Column(String, nullable=False)
    assigned_to = Column(String, nullable=True)
    affected_service = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    description = Column(Text, nullable=True)


class Telemetry(Base):
    __tablename__ = "telemetry"

    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    metric_name = Column(String, nullable=False)
    value = Column(Float, nullable=False)
    unit = Column(String, nullable=False)
    tags = Column(String, nullable=True)


class ComplianceRule(Base):
    __tablename__ = "compliance_rules"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    vendor = Column(String, nullable=True)
    severity = Column(String, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    last_validated = Column(DateTime, default=datetime.utcnow, nullable=False)


<<<<<<< HEAD
class AIQuery(Base):
    __tablename__ = "ai_queries"

    id = Column(Integer, primary_key=True)
    query = Column(String, nullable=False)
    response = Column(Text, nullable=True)
    source = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


=======
>>>>>>> 5cb6d67eba2e3f48a4a6ba132b7fab89cc51e00a
class NetworkLink(Base):
    __tablename__ = "network_links"

    id = Column(Integer, primary_key=True)
    source_device = Column(String, nullable=False)
    destination_device = Column(String, nullable=False)
    link_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="up")
    bandwidth_mbps = Column(Float, nullable=True)


class ChangeRequest(Base):
    __tablename__ = "changes"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    status = Column(String, nullable=False)
    risk = Column(String, nullable=True)
    implementation_date = Column(String, nullable=True)
    engineer = Column(String, nullable=True)
