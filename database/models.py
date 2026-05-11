from sqlalchemy.orm import declarative_base
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    DateTime,
    Text,
)

from datetime import datetime

Base = declarative_base()


# =========================================================
# DEVICES
# =========================================================

class Device(Base):

    __tablename__ = "devices"

    id = Column(Integer, primary_key=True)

    hostname = Column(String, unique=True)
    ip_address = Column(String)

    vendor = Column(String)
    model = Column(String)

    role = Column(String)
    site = Column(String)

    os_version = Column(String)

    status = Column(String)

    latitude = Column(Float)
    longitude = Column(Float)


# =========================================================
# INTERFACES
# =========================================================

class Interface(Base):

    __tablename__ = "interfaces"

    id = Column(Integer, primary_key=True)

    device_id = Column(Integer, ForeignKey("devices.id"))

    interface_name = Column(String)

    admin_status = Column(String)
    oper_status = Column(String)

    bandwidth = Column(String)

    input_errors = Column(Integer)
    output_errors = Column(Integer)

    utilization = Column(Float)


# =========================================================
# BGP PEERS
# =========================================================

class BGPPeer(Base):

    __tablename__ = "bgp_peers"

    id = Column(Integer, primary_key=True)

    local_device = Column(String)

    peer_ip = Column(String)

    peer_asn = Column(String)

    state = Column(String)

    prefixes_received = Column(Integer)

    flaps = Column(Integer)


# =========================================================
# INCIDENTS
# =========================================================

class Incident(Base):

    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True)

    title = Column(String)

    severity = Column(String)

    status = Column(String)

    assigned_to = Column(String)

    affected_service = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow)

    description = Column(Text)


# =========================================================
# ALERTS
# =========================================================

class Alert(Base):

    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)

    device = Column(String)

    alert_type = Column(String)

    severity = Column(String)

    message = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)


# =========================================================
# CHANGES
# =========================================================

class ChangeRequest(Base):

    __tablename__ = "changes"

    id = Column(Integer, primary_key=True)

    title = Column(String)

    status = Column(String)

    risk = Column(String)

    implementation_date = Column(String)

    engineer = Column(String)


# =========================================================
# KNOWLEDGE BASE
# =========================================================

class KnowledgeDocument(Base):

    __tablename__ = "knowledge_documents"

    id = Column(Integer, primary_key=True)

    title = Column(String)

    vendor = Column(String)

    protocol = Column(String)

    content = Column(Text)


# =========================================================
# TOPOLOGY LINKS
# =========================================================

class TopologyLink(Base):

    __tablename__ = "topology_links"

    id = Column(Integer, primary_key=True)

    source_device = Column(String)

    destination_device = Column(String)

    link_type = Column(String)

    status = Column(String)
