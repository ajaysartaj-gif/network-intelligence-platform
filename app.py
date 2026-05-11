"""
NetBrain AI — Autonomous Network Operating System
app.py — Main entry point (Streamlit)

Architecture:
  app.py                    ← This file (entry, routing, state)
  core/ai_engine.py         ← OpenRouter AI + personas
  core/nlp_engine.py        ← NLP entity extraction + intent
  core/rag_engine.py        ← RAG knowledge base (ChromaDB/keyword)
  core/mdq_engine.py        ← Multi-device parallel query
  database/models.py        ← SQLAlchemy ORM models
  database/database.py      ← DB manager, encryption, seeding
  security/rbac.py          ← Role-based access control
  ui/components.py          ← Design system + component library
"""

# ── MUST be first Streamlit call ──────────────────────────
import streamlit as st
st.set_page_config(
    page_title="NetBrain AI",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={"About": "NetBrain AI — Autonomous Network Operating System v2.0"},
)

# ── Stdlib + 3rd-party imports ────────────────────────────
import sys, os, logging, re, hashlib, time, threading, copy, random
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from dataclasses import dataclass, field
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutureTimeoutError
import pandas as pd

# ── Logging ────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
logger = logging.getLogger('netbrain.app')

# ══ DATABASE MODELS ══════════════════════════════════

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean,
    Float, ForeignKey, create_engine
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Device(Base):
    __tablename__ = "devices"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    hostname   = Column(String(128), nullable=False, index=True)
    ip         = Column(String(45), nullable=False)
    vendor     = Column(String(64), default="cisco_ios")
    username   = Column(String(64))
    password_enc = Column(Text)          # Fernet-encrypted
    port       = Column(Integer, default=22)
    role       = Column(String(64))
    site       = Column(String(64))
    status     = Column(String(32), default="unknown")
    cpu        = Column(Integer, default=0)
    memory     = Column(Integer, default=0)
    os_version = Column(String(128))
    last_seen  = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(64))

    incidents  = relationship("IncidentDevice", back_populates="device", lazy="dynamic")


class Incident(Base):
    __tablename__ = "incidents"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    title           = Column(String(256), nullable=False)
    description     = Column(Text)
    root_cause      = Column(Text)
    resolution      = Column(Text)
    protocols       = Column(String(256))
    severity        = Column(String(32), default="major")
    status          = Column(String(32), default="active", index=True)
    business_impact = Column(Text)
    affected_users  = Column(Integer, default=0)
    ai_confidence   = Column(Integer, default=0)
    workspace       = Column(String(64))
    created_by      = Column(String(64))
    created_at      = Column(DateTime, default=datetime.utcnow, index=True)
    resolved_at     = Column(DateTime)
    updated_at      = Column(DateTime, onupdate=datetime.utcnow)

    devices         = relationship("IncidentDevice", back_populates="incident")


class IncidentDevice(Base):
    __tablename__ = "incident_devices"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    device_id   = Column(Integer, ForeignKey("devices.id"), nullable=False)
    incident    = relationship("Incident", back_populates="devices")
    device      = relationship("Device",   back_populates="incidents")


class Change(Base):
    __tablename__ = "changes"
    id                 = Column(Integer, primary_key=True, autoincrement=True)
    title              = Column(String(256), nullable=False)
    description        = Column(Text)
    device             = Column(String(128))
    change_type        = Column(String(64))
    risk_level         = Column(String(32), default="low")
    status             = Column(String(32), default="pending", index=True)
    ai_risk_score      = Column(Integer, default=0)
    ai_recommendation  = Column(Text)
    rollback_plan      = Column(Text)
    created_by         = Column(String(64))
    approved_by        = Column(String(64))
    created_at         = Column(DateTime, default=datetime.utcnow)
    approved_at        = Column(DateTime)


class AutonomousAction(Base):
    __tablename__ = "autonomous_actions"
    id             = Column(Integer, primary_key=True, autoincrement=True)
    action         = Column(Text, nullable=False)
    device         = Column(String(128))
    trigger        = Column(Text)
    ai_confidence  = Column(Integer, default=0)
    status         = Column(String(32), default="pending", index=True)
    result         = Column(Text)
    executed_by    = Column(String(64), default="NetBrain AI")
    created_at     = Column(DateTime, default=datetime.utcnow)
    executed_at    = Column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    user        = Column(String(64), index=True)
    action      = Column(String(128), nullable=False)
    resource    = Column(String(256))
    detail      = Column(Text)
    ip_address  = Column(String(45))
    result      = Column(String(32), default="success")
    created_at  = Column(DateTime, default=datetime.utcnow, index=True)


class KnowledgeDoc(Base):
    __tablename__ = "knowledge_docs"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    title      = Column(String(256), nullable=False)
    vendor     = Column(String(64), default="general")
    doc_type   = Column(String(64), default="manual")
    content    = Column(Text)
    chunk_hash = Column(String(64), unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class QueryLog(Base):
    __tablename__ = "query_logs"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    query        = Column(Text)
    device_count = Column(Integer, default=0)
    ai_result    = Column(Text)
    persona      = Column(String(32))
    created_at   = Column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    username     = Column(String(64), unique=True, nullable=False, index=True)
    email        = Column(String(128))
    password_hash= Column(String(256))
    role         = Column(String(32), default="readonly")
    is_active    = Column(Boolean, default=True)
    last_login   = Column(DateTime)
    created_at   = Column(DateTime, default=datetime.utcnow)


# ══ DATABASE MANAGER ═════════════════════════════════

import os, logging, hashlib
from datetime import datetime
from contextlib import contextmanager
from typing import List, Optional

import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool



# ── Encryption ────────────────────────────────────────────
def _get_fernet():
    try:
        from cryptography.fernet import Fernet
        key = None
        try:    key = st.secrets.get("SECRET_KEY", "")
        except: key = os.environ.get("SECRET_KEY", "")
        if not key:
            # Generate ephemeral key for dev (not persistent across restarts)
            key = Fernet.generate_key().decode()
            logger.warning("No SECRET_KEY found — using ephemeral key. Set SECRET_KEY in secrets.toml for production.")
        if isinstance(key, str): key = key.encode()
        return Fernet(key)
    except ImportError:
        return None

def encrypt_password(plaintext: str) -> str:
    f = _get_fernet()
    if f and plaintext:
        return f.encrypt(plaintext.encode()).decode()
    return plaintext   # fallback — no encryption

def decrypt_password(ciphertext: str) -> str:
    f = _get_fernet()
    if f and ciphertext:
        try:    return f.decrypt(ciphertext.encode()).decode()
        except: return ciphertext   # already plaintext or wrong key
    return ciphertext


# ── Engine ────────────────────────────────────────────────
@st.cache_resource
def get_engine():
    db_url = None
    try:    db_url = st.secrets.get("DATABASE_URL", "")
    except: db_url = os.environ.get("DATABASE_URL", "")

    if db_url and "postgresql" in db_url:
        engine = create_engine(db_url, pool_size=10, max_overflow=20, pool_pre_ping=True)
        logger.info("Connected to PostgreSQL")
    else:
        # SQLite with WAL mode for better concurrent reads
        engine = create_engine(
            "sqlite:///netbrain.db",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.commit()
        logger.info("Connected to SQLite (dev mode)")

    Base.metadata.create_all(engine)
    return engine


SessionLocal = sessionmaker(autocommit=False, autoflush=False)

@contextmanager
def get_db() -> Session:
    engine = get_engine()
    SessionLocal.configure(bind=engine)
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"DB error: {e}")
        raise
    finally:
        session.close()


# ── Seed ──────────────────────────────────────────────────
def seed_database():
    """Seed with realistic demo data on first run."""
    with get_db() as db:
        if db.query(Device).count() > 0:
            return   # Already seeded

        # Devices
        devices_data = [
            ("CORE-RTR-01","10.0.0.1","cisco_ios_xr","admin","admin123",22,"Core Router","HQ","warn",88,62),
            ("PE-MUM-01",  "10.0.1.1","cisco_ios_xr","admin","admin123",22,"PE Router", "Mumbai","critical",34,48),
            ("PE-DEL-01",  "10.0.2.1","cisco_ios_xr","admin","admin123",22,"PE Router", "Delhi","up",22,41),
            ("DIST-SW-W",  "10.1.1.1","cisco_ios",   "admin","admin123",22,"Dist Switch","HQ-West","up",18,35),
            ("DIST-SW-C",  "10.1.2.1","cisco_ios",   "admin","admin123",22,"Dist Switch","HQ-Central","warn",45,71),
            ("FW-EDGE-01", "192.168.1.1","paloalto_panos","admin","admin123",22,"Firewall","DMZ","up",18,55),
            ("SW-ACC-14",  "10.2.14.1","cisco_ios",  "admin","admin123",22,"Access Switch","HQ-Floor2","critical",0,0),
            ("WLC-HQ-01",  "10.3.1.1","cisco_ios",   "admin","admin123",22,"WLC","HQ","up",22,38),
        ]
        for h,ip,v,u,p,port,role,site,status,cpu,mem in devices_data:
            db.add(Device(
                hostname=h, ip=ip, vendor=v, username=u,
                password_enc=encrypt_password(p),
                port=port, role=role, site=site,
                status=status, cpu=cpu, memory=mem
            ))

        # Incidents
        incidents_data = [
            ("BGP Session Flapping — PE-MUM-01",
             "BGP peer AS65002 flapping 3x/hr causing route instability",
             "Upstream ISP BGP prefix withdrawal causing hold-timer expiry",
             "Increase BGP hold-timer to 90s. Open ISP ticket. Enable BFD.",
             "BGP","critical","active",
             "142 prefixes withdrawn. Mumbai SaaS access degraded. 340 users impacted.",340,87),
            ("Interface Down — SW-ACC-14 Gi0/0/3",
             "Physical interface failure on access switch",
             "Physical port failure or cable disconnect",
             "Replace cable or SFP. Check port for physical damage.",
             "Layer2","critical","active",
             "VLAN 120 isolated. 47 users cannot access corporate network.",47,94),
            ("OSPF Adjacency Lost — 2024-11-14",
             "OSPF neighbor lost between CORE and DIST-SW-W",
             "MTU mismatch on GigabitEthernet interface (1500 vs 9000)",
             "Added ip ospf mtu-ignore on both interfaces. Convergence in 4 min.",
             "OSPF","major","resolved",
             "Brief routing disruption. Auto-recovered.",0,96),
        ]
        for title,desc,rca,res,proto,sev,status,impact,users,conf in incidents_data:
            db.add(Incident(
                title=title, description=desc, root_cause=rca, resolution=res,
                protocols=proto, severity=sev, status=status,
                business_impact=impact, affected_users=users, ai_confidence=conf
            ))

        # Changes
        changes_data = [
            ("BGP hold-timer update — PE-MUM-01",
             "Increase BGP hold-timer from 60s to 90s to reduce flapping",
             "PE-MUM-01","config","low","approved",15,
             "Low risk. Timer change only. No protocol restart. Recommend BFD simultaneously.",
             "Pre: verify BGP state. Post: monitor for 30 min.","NOC-Engineer"),
            ("IOS-XR firmware upgrade — CORE-RTR-01",
             "Upgrade from 7.5.2 to 7.7.1 on core router",
             "CORE-RTR-01","firmware","high","pending",72,
             "HIGH RISK. Core router. Maintenance window mandatory. Digital twin test first. Rollback pre-staged.",
             "Full rollback: boot previous partition. RTO < 5 min.","Architect"),
            ("New VLAN 150 — DIST-SW-W",
             "Add VLAN 150 for new HR subnet deployment",
             "DIST-SW-W","vlan","low","pending",8,
             "Low risk. VLAN addition only. No impact to existing VLANs.",
             "Remove VLAN 150 if issues arise.","NOC-Engineer"),
        ]
        for title,desc,dev,ctype,risk,status,score,rec,rollback,by in changes_data:
            db.add(Change(
                title=title, description=desc, device=dev, change_type=ctype,
                risk_level=risk, status=status, ai_risk_score=score,
                ai_recommendation=rec, rollback_plan=rollback, created_by=by
            ))

        # Autonomous actions
        auto_data = [
            ("BFD enabled on BGP peer 10.0.2.1","PE-MUM-01",
             "BGP flap detected — 3 events in 60 min",91,"executed",
             "BFD session established. Detection time reduced to 300ms."),
            ("SNMP trap forwarded to NOC","SW-ACC-14",
             "Interface down — Gi0/0/3",99,"executed",
             "Ticket INC0047821 created. NOC notified via Slack."),
            ("BGP hold-timer increase staged","PE-MUM-01",
             "Recurring BGP flap pattern — 3rd occurrence",78,"pending_approval",
             "Awaiting NOC engineer approval. Estimated risk: LOW."),
        ]
        for action,dev,trigger,conf,status,result in auto_data:
            db.add(AutonomousAction(
                action=action, device=dev, trigger=trigger,
                ai_confidence=conf, status=status, result=result
            ))

        # Default admin user
        try:
            import bcrypt
            ph = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
        except ImportError:
            ph = "plain:admin123"
        db.add(User(username="admin", email="admin@netbrain.ai", password_hash=ph, role="admin"))

        logger.info("Database seeded with demo data")


# ── Query helpers ─────────────────────────────────────────
def get_devices() -> List[dict]:
    with get_db() as db:
        rows = db.query(Device).order_by(Device.hostname).all()
        return [_device_to_dict(r) for r in rows]

def _device_to_dict(d: Device) -> dict:
    return {
        "id": d.id, "hostname": d.hostname, "ip": d.ip,
        "vendor": d.vendor, "username": d.username,
        "password": decrypt_password(d.password_enc or ""),
        "port": d.port, "role": d.role or "", "site": d.site or "",
        "status": d.status or "unknown", "cpu": d.cpu or 0,
        "memory": d.memory or 0, "os_version": d.os_version or "",
    }

def get_incidents(status: Optional[str] = None) -> List[dict]:
    with get_db() as db:
        q = db.query(Incident).order_by(Incident.created_at.desc())
        if status:
            q = q.filter(Incident.status == status)
        return [_inc_to_dict(r) for r in q.all()]

def _inc_to_dict(i: Incident) -> dict:
    return {
        "id": i.id, "title": i.title, "description": i.description or "",
        "root_cause": i.root_cause or "", "resolution": i.resolution or "",
        "protocols": i.protocols or "", "severity": i.severity or "major",
        "status": i.status or "active", "business_impact": i.business_impact or "",
        "affected_users": i.affected_users or 0,
        "ai_confidence": i.ai_confidence or 0,
        "created_at": str(i.created_at or ""),
    }

def get_changes() -> List[dict]:
    with get_db() as db:
        return [_chg_to_dict(r) for r in db.query(Change).order_by(Change.created_at.desc()).all()]

def _chg_to_dict(c: Change) -> dict:
    return {
        "id": c.id, "title": c.title, "description": c.description or "",
        "device": c.device or "", "change_type": c.change_type or "",
        "risk_level": c.risk_level or "low", "status": c.status or "pending",
        "ai_risk_score": c.ai_risk_score or 0,
        "ai_recommendation": c.ai_recommendation or "",
        "rollback_plan": c.rollback_plan or "",
        "created_by": c.created_by or "",
    }

def get_auto_actions() -> List[dict]:
    with get_db() as db:
        return [_aa_to_dict(r) for r in db.query(AutonomousAction).order_by(AutonomousAction.created_at.desc()).all()]

def _aa_to_dict(a: AutonomousAction) -> dict:
    return {
        "id": a.id, "action": a.action, "device": a.device or "",
        "trigger": a.trigger or "", "ai_confidence": a.ai_confidence or 0,
        "status": a.status or "pending", "result": a.result or "",
    }

def update_record(model_class, record_id: int, **kwargs):
    with get_db() as db:
        obj = db.query(model_class).filter_by(id=record_id).first()
        if obj:
            for k, v in kwargs.items():
                setattr(obj, k, v)

def add_device(hostname,ip,vendor,username,password,port,role,site) -> Device:
    with get_db() as db:
        d = Device(
            hostname=hostname, ip=ip, vendor=vendor, username=username,
            password_enc=encrypt_password(password),
            port=port, role=role, site=site
        )
        db.add(d); db.flush()
        return d

def add_incident(title,desc,sev,protocols,business_impact,affected_users,confidence) -> Incident:
    with get_db() as db:
        i = Incident(
            title=title, description=desc, severity=sev, protocols=protocols,
            business_impact=business_impact, affected_users=affected_users,
            ai_confidence=confidence
        )
        db.add(i); db.flush()
        return i

def write_audit(user: str, action: str, resource: str = "", detail: str = "", result: str = "success"):
    try:
        with get_db() as db:
            db.add(AuditLog(user=user, action=action, resource=resource, detail=detail, result=result))
    except Exception as e:
        logger.error(f"Audit write failed: {e}")

def get_audit_logs(limit: int = 100) -> List[dict]:
    with get_db() as db:
        rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
        return [{"user":r.user,"action":r.action,"resource":r.resource,"detail":r.detail,"result":r.result,"ts":str(r.created_at)} for r in rows]


# ══ RBAC ═════════════════════════════════════════════

from enum import Enum
from typing import Set
try:
    import streamlit as st
except ImportError:
    class _FakeSt:
        def cache_data(self, *a, **k): return lambda f: f
    st = _FakeSt()

class Role(str, Enum):
    ADMIN         = "admin"
    ARCHITECT     = "architect"
    NOC           = "noc"
    SECURITY      = "security"
    READONLY      = "readonly"
    EXECUTIVE     = "executive"

# ── Permission definitions ────────────────────────────────
PERMISSIONS: dict[Role, Set[str]] = {
    Role.ADMIN: {
        "view_all","manage_devices","push_config","manage_users",
        "approve_changes","run_automation","view_credentials",
        "manage_integrations","view_audit","delete_records",
        "manage_rbac","view_security","run_mdq","view_incidents",
        "create_incidents","resolve_incidents","view_executive",
        "manage_rag","run_digital_twin","view_finops",
    },
    Role.ARCHITECT: {
        "view_all","manage_devices","view_credentials",
        "approve_changes","run_digital_twin","view_security",
        "run_mdq","view_incidents","create_incidents","view_executive",
        "manage_rag","view_finops","push_config",
    },
    Role.NOC: {
        "view_all","run_mdq","view_incidents","create_incidents",
        "resolve_incidents","approve_changes","run_automation",
        "view_security",
    },
    Role.SECURITY: {
        "view_all","view_security","view_incidents","create_incidents",
        "resolve_incidents","view_credentials","run_mdq",
        "view_audit",
    },
    Role.READONLY: {
        "view_all","view_incidents",
    },
    Role.EXECUTIVE: {
        "view_all","view_incidents","view_executive","view_finops",
    },
}

def get_current_role() -> Role:
    """Get role from Streamlit session state. Default to admin for dev."""
    return Role(st.session_state.get("user_role", Role.ADMIN))

def has_permission(permission: str) -> bool:
    role = get_current_role()
    return permission in PERMISSIONS.get(role, set())

def require_permission(permission: str) -> bool:
    """Show warning and return False if permission denied."""
    if not has_permission(permission):
        st.warning(f"🔒 Access denied — your role ({get_current_role()}) cannot perform: `{permission}`")
        return False
    return True

def get_role_label() -> str:
    role_labels = {
        Role.ADMIN:"👑 Admin", Role.ARCHITECT:"🏗 Architect",
        Role.NOC:"🖥 NOC Engineer", Role.SECURITY:"🔒 Security Engineer",
        Role.READONLY:"👁 Read Only", Role.EXECUTIVE:"📊 Executive",
    }
    return role_labels.get(get_current_role(), "Unknown")

ALL_ROLES = [r.value for r in Role]


# ══ SYSTEM C — NLP ═══════════════════════════════════

import re, logging
from typing import Optional
from dataclasses import dataclass, field


# Optional spaCy
try:
    import spacy
    _spacy = spacy.load("en_core_web_sm")
    SPACY_OK = True
except Exception:
    SPACY_OK = False
    _spacy = None

# ══════════════════════════════════════════════════════════
# ENTITY PATTERNS
# ══════════════════════════════════════════════════════════
_RE = {
    "ipv4":       r'\b(?:\d{1,3}\.){3}\d{1,3}(?:\/\d{1,2})?\b',
    "ipv6":       r'\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}(?:\/\d{1,3})?\b',
    "mac":        r'\b(?:[0-9a-fA-F]{2}[:\-.]){5}[0-9a-fA-F]{2}\b',
    "interface":  r'\b(?:GigabitEthernet|Gi|FastEthernet|Fa|TenGigabitEthernet|Te|HundredGigE|Hu|FortyGigabitEthernet|Fo|Ethernet|Et|xe|ge|fe|em|Loopback|Lo|Tunnel|Tu|Bundle-Ether|BE|Port-channel|Po|Vlan|vlan|mgmt)\s*\d+(?:[\/\-\.]\d+){0,4}\b',
    "vlan":       r'\bVLAN\s*\d+\b|\bvlan\s*\d+\b|\bvid\s*\d+\b',
    "vrf":        r'\bVRF\s+\S+\b|\bvrf\s+\S+\b',
    "asn":        r'\bAS\s*\d+\b|\bASN\s*\d+\b|\bAS-\d+\b',
    "hostname":   r'\b[A-Z]{2,}[-_][A-Z0-9]{2,}(?:[-_][A-Z0-9]+){1,3}\b',
    "ticket":     r'\b(?:INC|CHG|PRB|REQ|TKT)\d{5,10}\b',
    "ospf_area":  r'\barea\s+\d+\b|\bOSPF\s+area\s+\d+\b',
    "bgp_prefix": r'\b(?:\d{1,3}\.){3}\d{1,3}\/\d{1,2}\b',
    "cloud_res":  r'\b(?:vpc-|subnet-|sg-|i-|rtb-|igw-|eni-)[0-9a-f]{8,17}\b',
    "port":       r'\bport\s+\d{2,5}\b|\bTCP\s+\d{2,5}\b|\bUDP\s+\d{2,5}\b',
}

PROTOCOLS = [
    "BGP","OSPF","EIGRP","IS-IS","ISIS","MPLS","EVPN","VXLAN","STP","RSTP","MSTP",
    "LACP","LLDP","CDP","BFD","HSRP","VRRP","GLBP","IPSec","GRE","DMVPN","mGRE",
    "SD-WAN","SDWAN","SASE","ZTNA","QoS","DSCP","SRv6","SR-MPLS","VRF",
    "SNMP","NetFlow","sFlow","IPFIX","CAPWAP","RADIUS","TACACS","AAA",
    "NAT","PAT","ACL","ZBFW","IPSEC","L2VPN","L3VPN","VPLS","VPWS",
    "NETCONF","RESTCONF","gRPC","OpenConfig","YANG","BGP-LS",
    "STP","PVST","RPVST","MST","802.1Q","802.1D","802.3AD",
    "RoCE","InfiniBand","iSCSI","FCoE","NVMe-oF",
]

VENDORS = [
    "Cisco","Juniper","Arista","Palo Alto","PAN-OS","Fortinet","FortiOS",
    "Aruba","HPE","Versa","VMware","VeloCloud","Viptela","Meraki",
    "Nokia","Huawei","Checkpoint","F5","Citrix","Zscaler","Cato","Netskope",
    "NVIDIA","Mellanox","Extreme","Brocade","Alcatel-Lucent","Ericsson",
]

# ══════════════════════════════════════════════════════════
# INTENT CLASSIFICATION
# ══════════════════════════════════════════════════════════
INTENTS = {
    "incident_rca": ["flapping","not working","down","failing","outage","broken",
                     "unreachable","lost","drops","degraded","unstable","crash"],
    "troubleshoot": ["troubleshoot","diagnose","debug","investigate","why","issue",
                     "problem","cannot reach","can't ping","latency","slow","packet loss"],
    "generate_config": ["generate","create config","write config","build config",
                        "configure","give me config","template","snippet"],
    "change_request": ["change","upgrade","modify","update","migrate","add vlan",
                       "new config","push","deploy","implement","rollout"],
    "design":       ["design","architect","plan","blueprint","topology","build network",
                     "what topology","recommend","best practice","how should i"],
    "explain":      ["explain","what is","what does","how does","tell me about",
                     "describe","definition","understand","difference between","vs"],
    "compare":      ["compare","vs","versus","better","difference","pros cons",
                     "which is best","trade-off","recommend vendor"],
    "query_devices":["show","check","fetch","get","query","find devices","across all",
                     "all devices","all routers","all switches","on all"],
    "security_analysis": ["threat","attack","breach","vulnerability","CVE","lateral movement",
                          "firewall","zero trust","ZTNA","segmentation","compliance"],
    "capacity_planning": ["capacity","bandwidth","growth","scale","size","utilization",
                          "forecast","trending","full","saturated"],
    "automation":   ["automate","playbook","ansible","terraform","script","workflow",
                     "orchestrate","self-heal","runbook"],
    "digital_twin": ["simulate","what if","what happens","predict","model","clone",
                     "test change","before production","safe test"],
    "compliance":   ["compliance","audit","policy","standard","NIST","CIS","PCI","SOC",
                     "drift","baseline","violation"],
    "learning":     ["learn","study","teach","explain basics","certification","CCNA",
                     "CCNP","CCIE","how does","tutorial"],
}

# ══════════════════════════════════════════════════════════
# URGENCY DETECTION
# ══════════════════════════════════════════════════════════
URGENCY_P1 = ["production down","p1","sev1","sev-1","critical outage","complete outage",
              "war room","all users affected","revenue impact","bridge call","emergency"]
URGENCY_P2 = ["p2","sev2","major impact","degraded","flapping","partial outage",
              "many users","key service","significant impact"]
URGENCY_P3 = ["p3","sev3","minor","warning","intermittent","some users","degraded performance"]
URGENCY_P4 = ["p4","sev4","low","info","fyi","enhancement","planned"]


# ══════════════════════════════════════════════════════════
# RESULT DATACLASS
# ══════════════════════════════════════════════════════════
@dataclass
class NLPResult:
    # Entities
    ipv4: list = field(default_factory=list)
    ipv6: list = field(default_factory=list)
    mac: list = field(default_factory=list)
    interfaces: list = field(default_factory=list)
    vlans: list = field(default_factory=list)
    vrfs: list = field(default_factory=list)
    asns: list = field(default_factory=list)
    hostnames: list = field(default_factory=list)
    tickets: list = field(default_factory=list)
    ospf_areas: list = field(default_factory=list)
    bgp_prefixes: list = field(default_factory=list)
    cloud_resources: list = field(default_factory=list)
    ports: list = field(default_factory=list)
    protocols: list = field(default_factory=list)
    vendors: list = field(default_factory=list)
    # Classification
    intent: str = "general"
    urgency: str = "normal"   # p1/p2/p3/p4/normal
    persona_hint: Optional[str] = None
    language: str = "en"
    # Context string for AI injection
    context_string: str = ""

    def to_context(self) -> str:
        parts = []
        if self.ipv4:       parts.append(f"IPs: {', '.join(self.ipv4[:8])}")
        if self.interfaces: parts.append(f"Interfaces: {', '.join(self.interfaces[:6])}")
        if self.vlans:      parts.append(f"VLANs: {', '.join(self.vlans[:6])}")
        if self.vrfs:       parts.append(f"VRFs: {', '.join(self.vrfs[:4])}")
        if self.asns:       parts.append(f"ASNs: {', '.join(self.asns[:4])}")
        if self.protocols:  parts.append(f"Protocols: {', '.join(self.protocols[:8])}")
        if self.vendors:    parts.append(f"Vendors: {', '.join(self.vendors[:4])}")
        if self.hostnames:  parts.append(f"Devices: {', '.join(self.hostnames[:6])}")
        if self.tickets:    parts.append(f"Tickets: {', '.join(self.tickets)}")
        if self.ospf_areas: parts.append(f"OSPF areas: {', '.join(self.ospf_areas)}")
        if self.urgency != "normal": parts.append(f"URGENCY: {self.urgency.upper()}")
        return " | ".join(parts)


# ══════════════════════════════════════════════════════════
# MAIN EXTRACTION FUNCTION
# ══════════════════════════════════════════════════════════
def extract(text: str) -> NLPResult:
    """
    Full NLP extraction pipeline.
    Returns NLPResult with all entities, intent, urgency, persona hint.
    """
    result = NLPResult()

    # ── Regex entity extraction ──
    for field_name, pattern in _RE.items():
        matches = list(dict.fromkeys(re.findall(pattern, text, re.IGNORECASE)))
        if field_name == "ipv4":       result.ipv4 = matches
        elif field_name == "ipv6":     result.ipv6 = matches
        elif field_name == "mac":      result.mac = matches
        elif field_name == "interface":result.interfaces = matches
        elif field_name == "vlan":     result.vlans = matches
        elif field_name == "vrf":      result.vrfs = matches
        elif field_name == "asn":      result.asns = matches
        elif field_name == "hostname": result.hostnames = matches
        elif field_name == "ticket":   result.tickets = matches
        elif field_name == "ospf_area":result.ospf_areas = matches
        elif field_name == "bgp_prefix":result.bgp_prefixes = matches
        elif field_name == "cloud_res":result.cloud_resources = matches
        elif field_name == "port":     result.ports = matches

    # ── Protocol detection ──
    tu = text.upper()
    result.protocols = [p for p in PROTOCOLS if p.upper() in tu]

    # ── Vendor detection ──
    tl = text.lower()
    result.vendors = [v for v in VENDORS if v.lower() in tl]

    # ── Intent classification ──
    best_intent, best_score = "general", 0
    for intent, kws in INTENTS.items():
        score = sum(1 for kw in kws if kw in tl)
        if score > best_score:
            best_score, best_intent = score, intent
    result.intent = best_intent

    # ── Urgency detection ──
    if any(w in tl for w in URGENCY_P1):
        result.urgency = "p1"
    elif any(w in tl for w in URGENCY_P2):
        result.urgency = "p2"
    elif any(w in tl for w in URGENCY_P3):
        result.urgency = "p3"
    elif any(w in tl for w in URGENCY_P4):
        result.urgency = "p4"

    # ── Persona hint ──
    expert_terms = ["sr-mpls","srv6","evpn","vxlan","route-reflector","bfd timer",
                    "lsdb","rsvp-te","segment-routing","rib-failure","rpf","multicast-rpf"]
    beginner_terms = ["what is","explain","how does","difference between","beginner",
                      "simple","easy","first time","new to","learning","student"]
    if any(w in tl for w in expert_terms):
        result.persona_hint = "architect"
    elif any(w in tl for w in beginner_terms):
        result.persona_hint = "fresher"

    # ── spaCy supplemental ──
    if SPACY_OK and _spacy:
        try:
            doc = _spacy(text[:5000])
            for ent in doc.ents:
                if ent.label_ in ("ORG","PRODUCT"):
                    for v in VENDORS:
                        if v.lower() in ent.text.lower() and v not in result.vendors:
                            result.vendors.append(v)
                elif ent.label_ == "GPE" and ent.text not in result.hostnames:
                    # Could be a site name
                    pass
        except Exception as e:
            logger.debug(f"spaCy error: {e}")

    result.context_string = result.to_context()
    return result


def enrich_query(query: str, result: NLPResult) -> str:
    """Prepend NLP context to query for AI injection."""
    ctx = result.to_context()
    if not ctx:
        return query
    return f"[NLP Context: {ctx}]\n[Intent: {result.intent}]\n[Urgency: {result.urgency}]\n\n{query}"


# ══ SYSTEM D — RAG ═══════════════════════════════════

import os, hashlib, logging
from typing import List, Tuple, Optional
try:
    import streamlit as st
    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False
    class _FakeSt:
        def cache_data(self, *a, **k): return lambda f: f
        def cache_resource(self, *a, **k): return lambda f: f
    st = _FakeSt()


# ── Optional imports ──────────────────────────────────────
try:
    import chromadb
    from sentence_transformers import SentenceTransformer
    _CHROMA_OK = True
except Exception:
    _CHROMA_OK = False

# ══════════════════════════════════════════════════════════
# NETWORKING KNOWLEDGE BASE — Pre-seeded
# ══════════════════════════════════════════════════════════
KNOWLEDGE_BASE = {
    "BGP": {
        "vendor": "general",
        "protocols": ["BGP"],
        "content": """
BGP (Border Gateway Protocol) — Path vector protocol for inter-AS routing.

NEIGHBOR STATES: Idle → Connect → Active → OpenSent → OpenConfirm → Established
Active state = TCP session NOT established. Never ignore Active state in production.

TROUBLESHOOTING ACTIVE STATE:
1. TCP 179 reachability: telnet <peer-ip> 179 OR ping source <update-source>
2. Remote-as mismatch: verify neighbor remote-as vs peer config
3. MD5 authentication: password must match exactly (case sensitive)
4. Update-source: loopback must be reachable and correct interface configured
5. ACL blocking TCP 179: check firewall rules both directions

BEST PATH SELECTION ORDER:
Weight (Cisco) → Local-Preference → Originate (locally) → AS_PATH length → Origin → MED → eBGP > iBGP → IGP metric → Router-ID

KEY TIMERS:
Hold-timer default: 180s. Keepalive: 60s. Recommend: hold 90s, keepalive 30s for stability.
BFD: reduces detection to 300ms-1s. Use for critical BGP peers.

ROUTE MANIPULATION:
Local-pref (iBGP): higher = preferred. Default 100.
AS_PATH prepend: set as-path prepend <ASN> <ASN> — adds hops to make path less preferred.
MED: lower = preferred. Compared only between paths from same AS.
Communities: no-export(65535:65281), no-advertise(65535:65282), internet(0:0)

COMMON ISSUES:
- Route not advertised: check network statement, route-map, next-hop reachability
- Route reflector: iBGP clients don't need full mesh. RR cluster-id prevents loops.
- ORF (Outbound Route Filtering): reduces unnecessary advertisements
- BGP PIC (Prefix Independent Convergence): sub-second failover

CISCO IOS-XR VERIFICATION:
show bgp all summary | show bgp neighbors <ip> | show bgp ipv4 unicast <prefix>
debug bgp <ip> all → use with caution in production
"""
    },
    "OSPF": {
        "vendor": "general",
        "protocols": ["OSPF"],
        "content": """
OSPF — Link State IGP, Dijkstra SPF algorithm, hierarchical areas.

NEIGHBOR STATES: Down → Attempt → Init → 2-Way → ExStart → Exchange → Loading → Full
FULL = healthy adjacency. Any other state on broadcast = investigate.

EXSTART STUCK — MOST COMMON CAUSE:
MTU mismatch between peers. Fix: ip ospf mtu-ignore OR match MTU both sides.
Also check: duplicate Router-ID, auth mismatch.

EXCHANGE STUCK:
DBD sequence number issue. Usually clears. If persistent: clear ip ospf process (disruptive).

DR/BDR ELECTION:
Highest priority wins. Default priority = 1. Priority 0 = never become DR.
Tiebreak = highest Router-ID. DR election is non-preemptive.
Best practice: explicitly set DR priority on core routers.

LSA TYPES:
Type 1: Router LSA — describes router links within area
Type 2: Network LSA — generated by DR for multi-access segments
Type 3: Summary LSA — ABR advertises between areas
Type 4: ASBR Summary — tells area where ASBR is
Type 5: AS External — redistributed external routes
Type 7: NSSA External — external routes in NSSA area (converted to Type 5 at ABR)

AREA TYPES:
Backbone: Area 0 (mandatory)
Stub: blocks Type 5 LSAs, injects default route
Totally Stub: blocks Type 3,4,5 — only default route
NSSA: allows redistribution into stub-like area
Totally NSSA: blocks Type 3 from ABR + allows redistribution

TIMERS: Hello=10s P2P/broadcast, 30s NBMA. Dead=4x hello. MUST MATCH both ends.
Fast hellos: ip ospf hello-interval 1 (sub-second detection, use with BFD preferred)

VERIFICATION: show ip ospf neighbor | show ip ospf interface | show ip ospf database
"""
    },
    "VLAN_SWITCHING": {
        "vendor": "general",
        "protocols": ["STP","VLAN","LACP"],
        "content": """
VLAN TROUBLESHOOTING:

VLAN NOT PASSING ON TRUNK:
show interfaces trunk → check allowed VLANs list
Fix: switchport trunk allowed vlan add <vlan-id>
Verify: VLAN exists on both switches (show vlan brief)

NATIVE VLAN MISMATCH:
Causes: CDP/LLDP warnings, broadcast flooding, security risk
Both ends must have same native VLAN. Default = VLAN 1.
Best practice: change native VLAN to unused VLAN ID.

STP STATES:
Blocking → Listening → Learning → Forwarding → Disabled
RSTP: Discarding → Learning → Forwarding (convergence <1 second)

STP PORT ROLES:
Root Port: best path to root bridge
Designated Port: forwarding port on each segment
Alternate Port (RSTP): backup to root port
Backup Port (RSTP): backup to designated port

PORTFAST: enables immediately on access ports (bypasses STP states)
BPDU Guard: shuts port if BPDU received (protects against unauthorized switches)
Root Guard: prevents external switch from becoming root

ETHERCHANNEL REQUIREMENTS:
Both sides must have identical: speed, duplex, mode (access/trunk), VLANs, native VLAN
LACP modes: active-active (both negotiate) or active-passive (one initiates)
PAgP modes: desirable-desirable or desirable-auto

VXLAN:
VTEP encapsulates L2 frame in UDP (port 4789) for L2 over L3 transport
VNI = 24-bit identifier (16M segments vs 4096 VLANs)
EVPN: BGP control plane for VXLAN MAC/IP learning
Type 2 route: MAC/IP advertisement. Type 3: multicast/BUM traffic.
Symmetric IRB: anycast gateway on every leaf (same IP+MAC)
"""
    },
    "SDWAN": {
        "vendor": "cisco",
        "protocols": ["SD-WAN","SASE","ZTNA"],
        "content": """
CISCO VIPTELA SD-WAN ARCHITECTURE:

COMPONENTS:
vManage: NMS/orchestration — single pane of glass, REST API, policy engine
vBond: orchestration — initial authentication, NAT traversal, helps vEdge discover vSmart
vSmart: controller — distributes OMP routes and policies to all vEdges
vEdge/cEdge: data plane — establishes IPSec tunnels to all other vEdges

OMP (Overlay Management Protocol):
BGP-like protocol between vEdge and vSmart. Carries routes, service chains, policy.
OMP prefixes: TLOCs, service routes, data prefixes.

TLOC (Transport Location): System-IP + Color + Encapsulation
Colors: mpls, biz-internet, public-internet, lte, private1-6, metro-ethernet
Each TLOC = separate tunnel, separate SLA measurement

APP-AWARE ROUTING:
SLA classes per application. Measured: jitter, latency, packet-loss.
Best-path selected per SLA class. Failover on SLA violation.
Direct cloud access: break-out at branch for SaaS (bypass HQ backhauling).

POLICIES:
Centralized (on vSmart): data policy (traffic engineering), control policy (routing), app-route
Localized (on vEdge): access-list, route-policy, QoS

SECURITY:
Cisco Umbrella: DNS security at branch
Cisco Secure Firewall: UTD on vEdge
ZTNA: Cisco Secure Access (ClearPass integration)
Zscaler integration: GRE/IPSec tunnels to ZIA nodes

ZERO TRUST WAN:
Identity-based policies, MFA, continuous verification
Replace site-to-site VPNs with application-specific access
"""
    },
    "MPLS": {
        "vendor": "general",
        "protocols": ["MPLS","L3VPN","L2VPN","SRv6","SR-MPLS"],
        "content": """
MPLS — Multi-Protocol Label Switching

LABEL STRUCTURE: 20-bit label | 3-bit TC/EXP (QoS) | 1-bit S (bottom of stack) | 8-bit TTL

LDP: Label Distribution Protocol
- Auto-discovers neighbors via UDP 646 multicast
- TCP 646 for session
- Distributes labels for all IGP prefixes
- PHP (Penultimate Hop Popping): last router pops label before final delivery

RSVP-TE: Traffic Engineering
- Explicit paths, bandwidth reservation per LSP
- Fast-Reroute (FRR): sub-50ms failover
- CSPF: constrained shortest path first

L3VPN ARCHITECTURE:
CE — PE — P — PE — CE
PE assigns VRF per customer. RD makes prefixes unique in BGP table.
RT (Route Target): import/export controls which VRFs see which routes.
MP-BGP VPNv4: carries VPN routes between PEs with VPNv4 address family.
SOO (Site-of-Origin): prevents routing loops in multihomed VPNs.

SEGMENT ROUTING:
SR-MPLS: uses MPLS labels, no LDP/RSVP needed
Prefix-SID: node identifier (globally unique in domain)
Adjacency-SID: link identifier (local scope)
SR-TE Policy: ordered segment list for explicit path engineering

SRv6:
Uses IPv6 addresses as segment IDs (128-bit)
SRH (Segment Routing Header) carries segment list
SRv6 functions: End (node), End.X (adjacency), End.DT4 (L3VPN decap)
Simplifies MPLS stack: native IPv6 forwarding, no LDP
"""
    },
    "SECURITY_NETWORKING": {
        "vendor": "general",
        "protocols": ["ZTNA","SASE","ACL","IPSec"],
        "content": """
NETWORK SECURITY — ZERO TRUST AND BEYOND

ZERO TRUST PRINCIPLES:
1. Never trust, always verify — no implicit trust based on network location
2. Least privilege access — minimum required permissions
3. Assume breach — segment everything, verify continuously

ZERO TRUST NETWORK ACCESS (ZTNA):
Replace VPN with application-specific access
Identity (user + device) verified before every access
No network-level access — only application-level
Vendors: Zscaler ZPA, Palo Alto Prisma Access, Cisco Secure Access, Cloudflare Access

SASE (Secure Access Service Edge):
Converges SD-WAN + SSE (Security Service Edge) in cloud
SSE components: SWG (web proxy), CASB (cloud access), ZTNA, FWaaS
Vendors: Zscaler (ZIA+ZPA), Cato Networks, Netskope, Palo Alto Prisma, Cisco+Umbrella

MICRO-SEGMENTATION:
East-west traffic inspection (not just north-south)
Policy enforcement at workload level (VM, container, process)
Tools: Cisco ACI, VMware NSX-T, Guardicore, Illumio

FIREWALL POLICY BEST PRACTICES:
Application-based rules (not port-based) — App-ID
User-based rules — User-ID integration with AD
Implicit deny all — whitelist approach
Rule review quarterly — shadow/unused rule cleanup
Log ALL — forward to SIEM

IPSEC TUNNEL:
Phase 1 (IKE SA): authentication + key exchange (DH group 14+ recommended)
Phase 2 (IPSec SA): data encryption (AES-256-GCM recommended)
DPD (Dead Peer Detection): detects down tunnels. Action: restart or clear.
Anti-replay: sequence number verification prevents replay attacks.
"""
    },
    "DATACENTER": {
        "vendor": "general",
        "protocols": ["VXLAN","EVPN","RoCE"],
        "content": """
DATACENTER NETWORKING — LEAF-SPINE FABRIC

LEAF-SPINE DESIGN PRINCIPLES:
Every leaf connects to every spine (full mesh uplinks)
No STP needed — L3 fabric with ECMP
Consistent latency: any host to any host = 2 hops
Scale-out: add leaf = add access ports; add spine = add bandwidth
Oversubscription ratio: typically 3:1 leaf (48 down / 8 up × 40G)

VXLAN/EVPN:
Underlay: eBGP between leaf and spine (different ASN per leaf)
Overlay: EVPN address family for MAC/IP learning
Leaf = VTEP (VXLAN Tunnel Endpoint) — encap/decap UDP 4789

EVPN ROUTE TYPES:
Type 1: Ethernet Auto-Discovery (multihoming)
Type 2: MAC/IP Advertisement (host learning)
Type 3: Inclusive Multicast Ethernet Tag (BUM traffic handling)
Type 4: Ethernet Segment Route (multihoming election)
Type 5: IP Prefix Route (external prefix advertisement)

SYMMETRIC IRB (preferred):
Both ingress and egress leaf do L3 routing
Anycast gateway: same IP+MAC on every leaf → no ARP flooding
L3VNI per VRF: allows inter-VRF routing on leaf

AI/GPU NETWORKING:
RoCE (RDMA over Converged Ethernet): OS bypass for GPU-to-GPU data transfer
Requires LOSSLESS: PFC (Priority Flow Control) + ECN (Explicit Congestion Notification)
DCQCN: congestion control algorithm for RoCE
400GbE / 800GbE links for GPU clusters
InfiniBand alternative: higher bandwidth, lower latency, proprietary
"""
    },
    "CLOUD_NETWORKING": {
        "vendor": "general",
        "protocols": ["BGP"],
        "content": """
CLOUD NETWORKING — HYBRID AND MULTI-CLOUD

AWS NETWORKING:
VPC: isolated L3 network. Subnets: public (IGW route) / private
Transit Gateway (TGW): hub for VPC-to-VPC and on-prem connectivity
Direct Connect: dedicated 1G/10G/100G connection. No internet path.
VPN Gateway: IPSec over internet. Backup for Direct Connect.
Security Groups: stateful. NACLs: stateless, subnet level.
AWS PrivateLink: private connectivity to services without internet.

AZURE NETWORKING:
VNet: Azure equivalent of VPC. Subnets, NSGs.
ExpressRoute: dedicated circuit to Azure. Partner or Direct.
Virtual WAN (VWAN): Azure managed SD-WAN-like hub-and-spoke.
Private Endpoint: private IP for PaaS services.
Azure Firewall: managed L7 firewall. Policy-based.

GCP NETWORKING:
VPC: global (unlike AWS regional). Subnets are regional.
Cloud Interconnect: Partner Interconnect or Dedicated Interconnect.
Cloud Router: BGP dynamic routing for VPN/Interconnect.
VPC Peering: direct routing between VPCs (no transitive).

KUBERNETES NETWORKING:
CNI (Container Network Interface): Calico, Cilium, Flannel, Weave
Pod CIDR: each pod gets unique IP. Service CIDR: virtual IPs.
kube-proxy: iptables/IPVS for service load balancing.
Cilium: eBPF-based, L7 policy, network observability.
Service Mesh: Istio, Linkerd — mTLS between pods, traffic management.

HYBRID CONNECTIVITY PATTERNS:
Hub-and-spoke: TGW or VWAN as hub, VPCs as spokes
Full mesh: complex but optimal for many-to-many
SD-WAN + cloud: direct breakout at branch to cloud (Azure Virtual WAN integration)
"""
    },
}


# ══════════════════════════════════════════════════════════
# VECTOR STORE
# ══════════════════════════════════════════════════════════
@st.cache_resource
def _get_vector_store():
    """Initialize ChromaDB collection (once per app lifecycle)."""
    if not _CHROMA_OK:
        return None, None
    try:
        client = chromadb.PersistentClient(path="./chroma_db")
        embedder = SentenceTransformer("all-MiniLM-L6-v2")
        collection = client.get_or_create_collection(
            "netbrain_kb_v2",
            metadata={"hnsw:space": "cosine"},
        )
        if collection.count() == 0:
            _seed_vector_store(collection, embedder)
        return collection, embedder
    except Exception as e:
        logger.error(f"ChromaDB init failed: {e}")
        return None, None


def _seed_vector_store(collection, embedder):
    """Seed the vector store with the knowledge base."""
    for topic, meta in KNOWLEDGE_BASE.items():
        content = meta["content"].strip()
        chunks = _chunk_text(content, size=350, overlap=70)
        ids, docs, metas = [], [], []
        for i, chunk in enumerate(chunks):
            chunk_id = hashlib.md5(f"{topic}_{i}".encode()).hexdigest()
            ids.append(chunk_id)
            docs.append(chunk)
            metas.append({
                "topic": topic,
                "vendor": meta.get("vendor", "general"),
                "protocols": ",".join(meta.get("protocols", [])),
                "chunk": i,
            })
        embs = embedder.encode(docs).tolist()
        collection.add(ids=ids, documents=docs, embeddings=embs, metadatas=metas)
    logger.info(f"Vector store seeded with {len(KNOWLEDGE_BASE)} topics")


def _chunk_text(text: str, size: int = 350, overlap: int = 70) -> List[str]:
    """Split text into overlapping chunks for better retrieval."""
    words = text.split()
    chunks, step = [], size - overlap
    for i in range(0, len(words), step):
        chunk = " ".join(words[i:i + size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks


# ══════════════════════════════════════════════════════════
# KEYWORD FALLBACK SEARCH
# ══════════════════════════════════════════════════════════
def _keyword_search(query: str, n: int = 4,
                    vendor_filter: Optional[str] = None,
                    protocol_filter: Optional[str] = None) -> List[Tuple[str, dict]]:
    """Keyword-based search when ChromaDB is unavailable."""
    ql = query.lower()
    scored = []
    for topic, meta in KNOWLEDGE_BASE.items():
        if vendor_filter and meta.get("vendor", "general") not in ["general", vendor_filter]:
            continue
        if protocol_filter:
            if not any(p.upper() == protocol_filter.upper() for p in meta.get("protocols", [])):
                continue
        content = meta["content"]
        cl = content.lower()
        score = sum(1 for w in ql.split() if len(w) > 3 and w in cl)
        # Boost for topic name match
        score += 5 * sum(1 for w in ql.split() if w in topic.lower())
        # Boost for protocol match
        score += 3 * sum(1 for p in meta.get("protocols", []) if p.lower() in ql)
        if score > 0:
            scored.append((score, topic, content))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(c[:500], {"topic": t, "vendor": KNOWLEDGE_BASE[t]["vendor"]})
            for _, t, c in scored[:n]]


# ══════════════════════════════════════════════════════════
# PUBLIC SEARCH INTERFACE
# ══════════════════════════════════════════════════════════
def search(
    query: str,
    n: int = 4,
    vendor_filter: Optional[str] = None,
    protocol_filter: Optional[str] = None,
) -> List[Tuple[str, dict]]:
    """
    Hybrid RAG search.
    Returns list of (content_chunk, metadata_dict).
    Falls back from ChromaDB → keyword automatically.
    """
    collection, embedder = _get_vector_store()

    if collection and embedder:
        try:
            where = {}
            if vendor_filter:    where["vendor"] = vendor_filter
            if protocol_filter:  where["protocols"] = {"$contains": protocol_filter}
            kwargs = {"n_results": min(n, max(1, collection.count())),
                      "query_embeddings": embedder.encode([query]).tolist()}
            if where:
                kwargs["where"] = where
            res = collection.query(**kwargs)
            docs  = res.get("documents", [[]])[0]
            metas = res.get("metadatas", [[]])[0]
            return [(d, m) for d, m in zip(docs, metas)]
        except Exception as e:
            logger.warning(f"ChromaDB search failed, using keyword fallback: {e}")

    return _keyword_search(query, n, vendor_filter, protocol_filter)


def format_rag_context(results: List[Tuple[str, dict]]) -> str:
    """Format RAG results for AI injection."""
    if not results:
        return ""
    parts = []
    for content, meta in results:
        topic = meta.get("topic", meta.get("title", "Knowledge"))
        parts.append(f"[{topic}]\n{content}")
    return "\n\n".join(parts)


def ingest_document(title: str, content: str,
                    vendor: str = "general", doc_type: str = "manual") -> int:
    """Ingest a new document into the RAG knowledge base."""
    collection, embedder = _get_vector_store()
    if not collection or not embedder:
        logger.warning("Vector store not available — document not indexed")
        return 0
    chunks = _chunk_text(content, size=350, overlap=70)
    ids, docs, metas = [], [], []
    for i, chunk in enumerate(chunks):
        chunk_id = hashlib.md5(f"{title}_{i}".encode()).hexdigest()
        ids.append(chunk_id)
        docs.append(chunk)
        metas.append({"title": title, "vendor": vendor,
                      "doc_type": doc_type, "chunk": i})
    embs = embedder.encode(docs).tolist()
    collection.add(ids=ids, documents=docs, embeddings=embs, metadatas=metas)
    logger.info(f"Ingested '{title}': {len(chunks)} chunks")
    return len(chunks)


def rag_status() -> dict:
    collection, _ = _get_vector_store()
    count = 0
    try:
        count = collection.count() if collection else len(KNOWLEDGE_BASE)
    except Exception:
        count = len(KNOWLEDGE_BASE)
    return {
        "backend":   "ChromaDB" if _CHROMA_OK else "Keyword",
        "available": True,
        "doc_count": count,
        "topics":    list(KNOWLEDGE_BASE.keys()),
    }


# ══ SYSTEM B — MDQ ═══════════════════════════════════

import logging, time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from typing import List, Optional
from dataclasses import dataclass, field


# ── Safe import ───────────────────────────────────────────
try:
    from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
    NETMIKO_OK = True
except ImportError:
    NETMIKO_OK = False
    logger.warning("netmiko not installed — simulation mode active")

# ══════════════════════════════════════════════════════════
# COMMAND MATRIX — NL query → vendor CLI
# ══════════════════════════════════════════════════════════
CMD_MATRIX = {
    "bgp summary": {
        "cisco_ios":    "show ip bgp summary",
        "cisco_ios_xe": "show ip bgp summary",
        "cisco_ios_xr": "show bgp all summary",
        "cisco_nxos":   "show bgp all summary",
        "juniper_junos":"show bgp summary",
        "arista_eos":   "show bgp summary",
        "huawei_vrp":   "display bgp peer",
    },
    "bgp neighbor": {
        "cisco_ios":    "show ip bgp neighbors",
        "cisco_ios_xr": "show bgp neighbors",
        "cisco_ios_xe": "show ip bgp neighbors",
        "juniper_junos":"show bgp neighbor",
        "arista_eos":   "show bgp neighbors",
    },
    "ospf neighbor": {
        "cisco_ios":    "show ip ospf neighbor",
        "cisco_ios_xr": "show ospf neighbor",
        "cisco_ios_xe": "show ip ospf neighbor",
        "cisco_nxos":   "show ip ospf neighbors",
        "juniper_junos":"show ospf neighbor",
        "arista_eos":   "show ip ospf neighbor",
        "huawei_vrp":   "display ospf peer",
    },
    "interface status": {
        "cisco_ios":    "show interfaces status",
        "cisco_ios_xr": "show interfaces brief",
        "cisco_ios_xe": "show interfaces status",
        "cisco_nxos":   "show interface status",
        "juniper_junos":"show interfaces terse",
        "arista_eos":   "show interfaces status",
        "huawei_vrp":   "display interface brief",
    },
    "cpu usage": {
        "cisco_ios":    "show processes cpu sorted | head 20",
        "cisco_ios_xr": "show processes cpu",
        "cisco_ios_xe": "show processes cpu sorted | head 20",
        "cisco_nxos":   "show processes cpu sort",
        "juniper_junos":"show chassis routing-engine",
        "arista_eos":   "show processes top once",
        "huawei_vrp":   "display cpu-usage",
    },
    "routing table": {
        "cisco_ios":    "show ip route",
        "cisco_ios_xr": "show route ipv4",
        "cisco_ios_xe": "show ip route",
        "cisco_nxos":   "show ip route",
        "juniper_junos":"show route",
        "arista_eos":   "show ip route",
        "huawei_vrp":   "display ip routing-table",
    },
    "vlan": {
        "cisco_ios":    "show vlan brief",
        "cisco_ios_xe": "show vlan brief",
        "cisco_ios_xr": "show vlan",
        "cisco_nxos":   "show vlan",
        "juniper_junos":"show vlans",
        "arista_eos":   "show vlan",
    },
    "version": {
        "cisco_ios":    "show version",
        "cisco_ios_xr": "show version",
        "cisco_ios_xe": "show version",
        "cisco_nxos":   "show version",
        "juniper_junos":"show version",
        "arista_eos":   "show version",
        "huawei_vrp":   "display version",
    },
    "logging": {
        "cisco_ios":    "show logging | last 50",
        "cisco_ios_xr": "show log | last 50",
        "cisco_ios_xe": "show logging | last 50",
        "juniper_junos":"show log messages | last 50",
        "arista_eos":   "show log last 50",
    },
    "inventory": {
        "cisco_ios":    "show inventory",
        "cisco_ios_xr": "show inventory",
        "cisco_ios_xe": "show inventory",
        "cisco_nxos":   "show inventory",
        "juniper_junos":"show chassis hardware",
        "arista_eos":   "show inventory",
        "huawei_vrp":   "display device",
    },
    "memory": {
        "cisco_ios":    "show memory statistics",
        "cisco_ios_xr": "show memory summary",
        "cisco_ios_xe": "show memory statistics",
        "cisco_nxos":   "show system resources",
        "juniper_junos":"show system memory",
        "arista_eos":   "show version | grep Mem",
    },
    "spanning tree": {
        "cisco_ios":    "show spanning-tree summary",
        "cisco_ios_xe": "show spanning-tree summary",
        "cisco_nxos":   "show spanning-tree summary",
        "arista_eos":   "show spanning-tree summary",
        "juniper_junos":"show spanning-tree bridge",
    },
}


def resolve_command(query: str, vendor: str) -> str:
    """Resolve natural language query to vendor-specific CLI command."""
    ql = query.lower()
    for keyword, vendor_map in CMD_MATRIX.items():
        if keyword in ql:
            return vendor_map.get(vendor, vendor_map.get("cisco_ios", "show version"))
    # If it looks like a direct CLI command, pass through
    direct_prefixes = ["show ", "display ", "ping ", "traceroute ", "trace ", "debug "]
    if any(ql.strip().startswith(p) for p in direct_prefixes):
        return query.strip()
    return "show version"


# ══════════════════════════════════════════════════════════
# SIMULATION OUTPUT
# ══════════════════════════════════════════════════════════
def _simulate(device: dict, command: str) -> dict:
    """Realistic simulated device output for demo/dev mode."""
    ip, hostname, vendor = device.get("ip","0.0.0.0"), device.get("hostname","DEVICE"), device.get("vendor","cisco_ios")
    cpu = device.get("cpu", 30)
    cmd_l = command.lower()

    if "bgp" in cmd_l and "summary" in cmd_l:
        out = (f"BGP router identifier {ip}, local AS number 65001\n"
               f"BGP table version is 1024\n\n"
               f"Neighbor        V    AS MsgRcvd MsgSent   Up/Down  State/PfxRcd\n"
               f"10.0.0.1        4 65001   14823   14801   5d02:14  Established/142\n"
               f"10.0.1.1        4 65002     341     340   0:04:12  Active\n"
               f"10.0.2.1        4 65003    8912    8890   2d11:22  Established/87")
    elif "ospf" in cmd_l and "neighbor" in cmd_l:
        out = (f"Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
               f"192.168.1.1       1   FULL/DR         00:00:38    10.1.1.1        Gi0/0\n"
               f"192.168.1.2       1   FULL/BDR        00:00:39    10.1.1.2        Gi0/1\n"
               f"192.168.1.3       0   EXSTART/-       00:00:40    10.1.1.3        Gi0/2  ← MTU mismatch suspected")
    elif "cpu" in cmd_l or "process" in cmd_l:
        out = (f"CPU utilization for five seconds: {cpu}%/{max(0,cpu-12)}%; one minute: {max(0,cpu-15)}%; five minutes: {max(0,cpu-20)}%\n"
               f"PID  Runtime(ms)  Invoked     uSecs  5Sec  1Min  5Min  Process\n"
               f"  42    89234120   1234567       723  {min(45,cpu//2)}%   38%   34%  OSPF-1 Hello\n"
               f" 103    45123456    987654       457  {min(22,cpu//4)}%   18%   15%  BGP Router\n"
               f" 201     8234567    456789       180  12%   10%   08%  IP Input")
    elif "vlan" in cmd_l:
        out = ("VLAN  Name                             Status    Ports\n"
               "----  -------------------------------- --------- ----------------------------\n"
               "1     default                          active    Gi0/0, Gi0/1\n"
               "10    MGMT                             active    Gi0/2\n"
               "100   FINANCE                          active    Gi0/3, Gi0/4\n"
               "120   BRANCH-HYD                       suspend\n"
               "200   SERVERS                          active    Gi1/0, Gi1/1")
    elif "interface" in cmd_l:
        out = ("Interface              Status         Protocol  Description\n"
               "GigabitEthernet0/0     up             up        WAN-Uplink-ISP\n"
               "GigabitEthernet0/1     up             up        LAN-Core-Trunk\n"
               "GigabitEthernet0/2     down           down      [UNUSED]\n"
               "GigabitEthernet0/3     admin down     down      VLAN-120-ACCESS")
    elif "log" in cmd_l:
        out = (f"*May 10 14:02:31.123: %BGP-5-ADJCHANGE: neighbor 10.0.1.1 Down BGP Notification sent\n"
               f"*May 10 14:02:35.456: %OSPF-5-ADJCHG: Process 1, Nbr 192.168.1.3 on Gi0/2 from LOADING to FULL\n"
               f"*May 10 14:01:22.789: %LINK-3-UPDOWN: Interface GigabitEthernet0/3, changed state to down\n"
               f"*May 10 14:00:15.012: %SYS-5-CONFIG_I: Configured from console by admin on vty0")
    elif "version" in cmd_l:
        out = (f"Cisco IOS XR Software, Version 7.5.2\nHostname: {hostname}\n"
               f"Uptime: 127 days, 4 hours, 22 minutes\nLast reload reason: Reload Command")
    elif "route" in cmd_l:
        out = (f"Codes: C - connected, S - static, R - RIP, B - BGP, O - OSPF\n"
               f"Gateway of last resort is 10.0.0.1 to network 0.0.0.0\n"
               f"B    0.0.0.0/0 [20/0] via 10.0.0.1, 5d02h\n"
               f"O    10.0.0.0/8 [110/2] via 10.1.1.1, 2d11h\n"
               f"C    192.168.1.0/24 is directly connected, Gi0/0\n"
               f"B    10.100.0.0/16 [200/0] via 10.0.1.1, 0:04:30, Gi0/1")
    else:
        out = f"Hostname: {hostname}\nIP: {ip}\nVendor: {vendor}\nUptime: 127 days 4 hours"

    return {"status": "ok", "output": out, "command": command, "simulated": True}


# ══════════════════════════════════════════════════════════
# DEVICE RESULT DATACLASS
# ══════════════════════════════════════════════════════════
@dataclass
class DeviceResult:
    hostname: str
    ip: str
    vendor: str
    role: str
    site: str
    command: str
    status: str          # ok / timeout / auth_error / error
    output: str
    simulated: bool
    elapsed_ms: int = 0
    error_detail: str = ""


# ══════════════════════════════════════════════════════════
# SSH EXECUTOR
# ══════════════════════════════════════════════════════════
def _ssh_device(device: dict, command: str, timeout: int = 15, retries: int = 2) -> DeviceResult:
    """SSH to a single device with retry logic."""
    base = DeviceResult(
        hostname=device.get("hostname","UNKNOWN"),
        ip=device.get("ip",""),
        vendor=device.get("vendor","cisco_ios"),
        role=device.get("role",""),
        site=device.get("site",""),
        command=command,
        status="error",
        output="",
        simulated=False,
    )

    if not NETMIKO_OK:
        result = _simulate(device, command)
        base.status = result["status"]
        base.output = result["output"]
        base.simulated = True
        return base

    for attempt in range(retries):
        try:
            t0 = time.time()
            params = {
                "device_type":    device.get("vendor", "cisco_ios"),
                "host":           device.get("ip", ""),
                "username":       device.get("username", "admin"),
                "password":       device.get("password", ""),
                "port":           device.get("port", 22),
                "timeout":        timeout,
                "session_timeout":timeout + 5,
                "fast_cli":       True,
            }
            with ConnectHandler(**params) as conn:
                output = conn.send_command(command, read_timeout=timeout)
            base.status = "ok"
            base.output = output
            base.elapsed_ms = int((time.time() - t0) * 1000)
            return base
        except NetmikoTimeoutException:
            logger.warning(f"{device['hostname']} timeout (attempt {attempt+1}/{retries})")
            if attempt == retries - 1:
                sim = _simulate(device, command)
                base.status = "timeout"
                base.output = sim["output"]
                base.simulated = True
                base.error_detail = "SSH timeout — showing simulated data"
                return base
            time.sleep(2 ** attempt)   # exponential backoff
        except NetmikoAuthenticationException:
            base.status = "auth_error"
            base.output = f"Authentication failed for {device['hostname']}"
            base.error_detail = "Check credentials"
            return base
        except Exception as e:
            logger.error(f"{device['hostname']} SSH error: {e}")
            if attempt == retries - 1:
                sim = _simulate(device, command)
                base.status = "error"
                base.output = sim["output"]
                base.simulated = True
                base.error_detail = str(e)
                return base
            time.sleep(2 ** attempt)

    return base   # unreachable but satisfies type checker


# ══════════════════════════════════════════════════════════
# PARALLEL QUERY ENGINE
# ══════════════════════════════════════════════════════════
def run_query(
    query: str,
    devices: List[dict],
    max_workers: int = 10,
    timeout_per_device: int = 15,
    device_ids: Optional[List[int]] = None,
) -> List[DeviceResult]:
    """
    Run a query against all devices in parallel using ThreadPoolExecutor.
    Returns list of DeviceResult objects.
    """
    if device_ids:
        devices = [d for d in devices if d.get("id") in device_ids]
    if not devices:
        return []

    results = []
    # Cap workers to avoid resource exhaustion
    workers = min(max_workers, len(devices), 20)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _ssh_device,
                device,
                resolve_command(query, device.get("vendor", "cisco_ios")),
                timeout_per_device,
            ): device
            for device in devices
        }
        for future in as_completed(futures, timeout=timeout_per_device + 5):
            try:
                result = future.result(timeout=5)
                results.append(result)
            except TimeoutError:
                device = futures[future]
                sim = _simulate(device, resolve_command(query, device.get("vendor","cisco_ios")))
                results.append(DeviceResult(
                    hostname=device.get("hostname","?"),
                    ip=device.get("ip",""),
                    vendor=device.get("vendor",""),
                    role=device.get("role",""),
                    site=device.get("site",""),
                    command=resolve_command(query, device.get("vendor","cisco_ios")),
                    status="timeout",
                    output=sim["output"],
                    simulated=True,
                    error_detail="Executor timeout",
                ))
            except Exception as e:
                logger.error(f"Future error: {e}")

    # Sort by hostname for consistent display
    results.sort(key=lambda r: r.hostname)
    return results


def build_synthesis_prompt(query: str, results: List[DeviceResult]) -> str:
    """Build the prompt for AI synthesis of multi-device results."""
    device_sections = []
    for r in results:
        sim_note = " [SIMULATED DATA]" if r.simulated else ""
        section = (f"=== {r.hostname} ({r.ip}) | {r.vendor} | {r.role} | {r.site} ==={sim_note}\n"
                   f"Command: {r.command}\n"
                   f"Status: {r.status}\n"
                   f"{r.output}")
        device_sections.append(section)

    device_context = "\n\n".join(device_sections)
    ok_count = sum(1 for r in results if r.status == "ok")

    return (f'Multi-device query: "{query}"\n'
            f'{len(results)} devices queried ({ok_count} successful):\n\n'
            f'{device_context}\n\n'
            f'Provide:\n'
            f'1. DIRECT ANSWER — answer the query using device data\n'
            f'2. FINDINGS — notable findings per device (focus on anomalies)\n'
            f'3. RISKS — any risks or issues detected\n'
            f'4. RECOMMENDED ACTIONS — prioritized next steps\n'
            f'Use specific device hostnames. Be concise.')


# ══ SYSTEM A — AI ENGINE ═════════════════════════════

import os, logging, time
from typing import Optional
import streamlit as st


# ── Model config ──────────────────────────────────────────
OPENROUTER_BASE     = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL    = "anthropic/claude-sonnet-4-5"
OPENROUTER_HEADERS  = {
    "HTTP-Referer": "https://netbrain-ai.streamlit.app",
    "X-Title": "NetBrain AI",
}

# ── Safe import ───────────────────────────────────────────
try:
    from openai import OpenAI
    _OPENAI_OK = True
except ImportError:
    _OPENAI_OK = False
    logger.warning("openai package missing — AI disabled")

# ══════════════════════════════════════════════════════════
# NETWORK EXPERTISE SYSTEM PROMPT
# ══════════════════════════════════════════════════════════
NETWORK_SYSTEM = """You are NetBrain AI — an AI-Native Autonomous Network Operating System.

You are NOT a chatbot. You are an operational intelligence engine embedded in every workflow.

Deep expertise across:
- Routing: BGP OSPF EIGRP IS-IS MPLS SR-MPLS SRv6 Segment-Routing multicast policy-routing
- Switching: VLANs STP RSTP MSTP EtherChannel VXLAN EVPN MACsec SD-Access
- WAN: SD-WAN(Viptela/Versa/VeloCloud) DMVPN SASE ZTNA cloud-WAN MPLS-L3VPN
- Security: Zero-Trust ZTNA micro-segmentation firewall ACL IPSec IDS/IPS SIEM
- Datacenter: Leaf-Spine ACI VXLAN-EVPN RoCE InfiniBand AI-fabric GPU-networking
- Cloud: AWS(VPC TGW DirectConnect) Azure(VNet ExpressRoute VWAN) GCP Kubernetes CNI
- Service Provider: L3VPN L2VPN SR-MPLS SRv6 5G-transport BGP-LU carrier-ethernet
- Wireless: CAPWAP 802.11ax WiFi6 WPA3 roaming RF-optimization wireless-assurance
- Monitoring: SNMP gRPC streaming-telemetry NetFlow syslog anomaly-detection
- Automation: Ansible Terraform NETCONF RESTCONF gRPC Python-netmiko intent-based

Vendors: Cisco Juniper Arista PaloAlto Fortinet Aruba Nokia Huawei Versa Zscaler Cato Netskope VMware

RESPONSE RULES:
1. Be operationally specific — name devices, IPs, protocols, exact CLI
2. Always show: Summary → Evidence → Root Cause → Business Impact → Actions → Rollback
3. Include AI confidence % for analysis
4. Generate CLI that works on the stated vendor
5. Translate technical issues to business language when impact is discussed
6. Learn from context: if similar incident mentioned, reference it explicitly"""

PERSONAS = {
    "fresher":  "Persona: BEGINNER STUDENT. Explain everything with analogies. Define every acronym inline. Use simple language. Step-by-step guidance. Encourage and reassure. Visual descriptions.",
    "ccna":     "Persona: CCNA ENGINEER. Explain with context and reasoning. Show CLI with line-by-line explanation. Guide through troubleshooting systematically. Reference exam topics where relevant.",
    "noc":      "Persona: NOC ENGINEER. BE CONCISE. Lead immediately with probable root cause. Give exact CLI to verify and fix. Include rollback. Mention escalation path. Time is critical.",
    "architect":"Persona: SENIOR ARCHITECT. Expert level — skip basics entirely. Focus on design trade-offs, scalability, HA, redundancy, vendor comparison. Reference RFCs and standards. Provide BOM context.",
    "manager":  "Persona: OPERATIONS MANAGER. Business language only. Avoid technical jargon. Focus on user impact, revenue risk, SLA performance, decisions needed, timeline to resolve.",
    "security": "Persona: SECURITY ENGINEER. Threat context first. Attack vectors. Compliance implications. Zero Trust alignment. SIEM correlation opportunities. Containment actions. CVE references.",
}

# ══════════════════════════════════════════════════════════
# KEY MANAGEMENT (no hardcoding)
# ══════════════════════════════════════════════════════════
def get_api_key() -> str:
    """Retrieve API key from Streamlit secrets or environment. Never hardcode."""
    try:
        return st.secrets.get("OPENROUTER_API_KEY", "")
    except Exception:
        return os.environ.get("OPENROUTER_API_KEY", "")

# ══════════════════════════════════════════════════════════
# CORE AI CALL
# ══════════════════════════════════════════════════════════
@st.cache_resource
def _get_client():
    key = get_api_key()
    if not key or not _OPENAI_OK:
        return None
    return OpenAI(api_key=key, base_url=OPENROUTER_BASE)


def call_ai(
    messages: list,
    persona: str = "noc",
    max_tokens: int = 2000,
    temperature: float = 0.3,
    workspace_context: str = "",
    rag_context: str = "",
    incident_context: str = "",
) -> str:
    """
    Core AI call with full context injection.
    Returns response text or error string.
    """
    key = get_api_key()
    if not key:
        return (
            "⚠️ **OpenRouter API key not configured.**\n\n"
            "Add to Streamlit Cloud → App Settings → Secrets:\n"
            "```toml\nOPENROUTER_API_KEY = \"sk-or-v1-...\"\n```"
        )
    if not _OPENAI_OK:
        return "⚠️ `openai` package missing. Ensure `openai>=1.30.0` is in requirements.txt"

    client = _get_client()
    if client is None:
        client = OpenAI(api_key=key, base_url=OPENROUTER_BASE)

    # Build system prompt
    system = NETWORK_SYSTEM + "\n\n" + PERSONAS.get(persona, PERSONAS["noc"])

    # Prepend context to messages
    full_messages = [{"role": "system", "content": system}]

    if rag_context:
        full_messages.append({"role": "user", "content": f"KNOWLEDGE BASE CONTEXT:\n{rag_context}"})
        full_messages.append({"role": "assistant", "content": "Knowledge base reviewed. Ready to apply."})

    if incident_context:
        full_messages.append({"role": "user", "content": f"OPERATIONAL MEMORY — SIMILAR INCIDENTS:\n{incident_context}"})
        full_messages.append({"role": "assistant", "content": "Historical context loaded."})

    if workspace_context:
        full_messages.append({"role": "user", "content": f"CURRENT WORKSPACE CONTEXT:\n{workspace_context}"})
        full_messages.append({"role": "assistant", "content": "Workspace context understood."})

    full_messages.extend(messages)

    try:
        start = time.time()
        resp = client.chat.completions.create(
            model=OPENROUTER_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=full_messages,
            extra_headers=OPENROUTER_HEADERS,
        )
        elapsed = time.time() - start
        text = resp.choices[0].message.content
        logger.info(f"AI call: {len(messages)} msgs → {len(text)} chars in {elapsed:.1f}s")
        return text
    except Exception as e:
        logger.error(f"AI call failed: {e}")
        return f"❌ AI error: `{e}`\n\nCheck your OpenRouter API key and model availability."


# ══════════════════════════════════════════════════════════
# SPECIALIZED CALL WRAPPERS
# ══════════════════════════════════════════════════════════
def analyze_incident(title: str, description: str, devices: str, protocols: str,
                     persona: str = "noc", history: list = None) -> dict:
    """Deep incident RCA — returns structured analysis."""
    prompt = f"""Perform deep root cause analysis for this network incident:

INCIDENT: {title}
DESCRIPTION: {description}
AFFECTED DEVICES: {devices}
PROTOCOLS: {protocols}

Provide structured analysis:
1. ROOT CAUSE — most probable cause with evidence
2. CONFIDENCE — AI confidence % with reasoning
3. BLAST RADIUS — exactly which devices/services/users are impacted
4. BUSINESS IMPACT — translate to business language
5. IMMEDIATE ACTIONS — prioritized, with exact CLI commands
6. VERIFICATION — how to confirm fix worked
7. ROLLBACK PLAN — exact steps if fix fails
8. PREVENTION — how to prevent recurrence"""

    msgs = (history or [])[-4:] + [{"role": "user", "content": prompt}]
    response = call_ai(msgs, persona=persona, max_tokens=2500)
    return {"response": response, "timestamp": time.time()}


def generate_config(description: str, vendor: str, persona: str = "noc") -> str:
    """Generate vendor-specific network config."""
    prompt = f"""Generate production-ready network configuration:

VENDOR/PLATFORM: {vendor}
REQUIREMENT: {description}

Rules:
- Include all necessary context lines (router bgp, interface, etc.)
- Add comments explaining each section
- Include verification commands after the config
- Note any prerequisites or dependencies
- Flag any risks or considerations
- Format as proper CLI that can be copy-pasted"""

    return call_ai([{"role": "user", "content": prompt}], persona=persona, max_tokens=2000)


def score_change_risk(title: str, description: str, device: str, change_type: str) -> dict:
    """Score a change request for risk."""
    prompt = f"""Score this network change for risk:

CHANGE: {title}
DEVICE: {device}
TYPE: {change_type}
DESCRIPTION: {description}

Return analysis:
1. RISK SCORE — 0 to 100 (0=safe, 100=catastrophic)
2. RISK FACTORS — specific reasons for score
3. BLAST RADIUS — what could break
4. APPROVAL RECOMMENDATION — approve/conditional/reject
5. PRE-CHANGE CHECKLIST — 5 validation steps
6. ROLLBACK PLAN — exact recovery procedure
7. MAINTENANCE WINDOW — required yes/no, recommended time"""

    response = call_ai([{"role": "user", "content": prompt}], persona="architect", max_tokens=1500)

    # Extract score from response
    score = 50
    import re
    m = re.search(r'RISK SCORE[:\s]+(\d+)', response, re.IGNORECASE)
    if m:
        score = min(100, max(0, int(m.group(1))))

    return {"response": response, "score": score}


def design_network(requirements: str, persona: str = "architect") -> str:
    """Generate full network architecture design."""
    prompt = f"""Design a complete enterprise network architecture:

REQUIREMENTS:
{requirements}

Generate:
1. ARCHITECTURE OVERVIEW — design philosophy and key decisions
2. NETWORK LAYERS — core/distribution/access/WAN/cloud detailed design
3. VENDOR SELECTION — comparison table with recommendation and reasoning
4. HARDWARE SIZING — specific models per layer with justification
5. BILL OF MATERIALS — top 15 items with estimated unit cost and quantity
6. SECURITY ARCHITECTURE — defense-in-depth layers
7. REDUNDANCY DESIGN — HA pairs, failover mechanisms, MTTR targets
8. IMPLEMENTATION ROADMAP — phased 90-day plan with milestones
9. RISK ANALYSIS — top 5 risks and mitigations
10. COST SUMMARY — CapEx, OpEx, 3-year TCO estimate"""

    return call_ai([{"role": "user", "content": prompt}], persona=persona, max_tokens=3000)


# ══ OBSERVABILITY ════════════════════════════════════

import logging, math, random
from datetime import datetime, timedelta
from typing import List, Optional
try:
    import streamlit as st
    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False
    class _FakeSt:
        def cache_data(self, *a, **k): return lambda f: f
        def cache_resource(self, *a, **k): return lambda f: f
    st = _FakeSt()



# ══════════════════════════════════════════════════════════
# TELEMETRY SIMULATION ENGINE
# ══════════════════════════════════════════════════════════
def get_live_telemetry(device_count: int = 8) -> List[dict]:
    """
    Simulate live telemetry stream.
    In production: replace with gRPC/SNMP/OpenConfig collectors.
    """
    import time
    seed = int(time.time() // 15)   # changes every 15s

    devices = [
        {"hostname":"CORE-RTR-01","ip":"10.0.0.1","role":"Core Router"},
        {"hostname":"PE-MUM-01",  "ip":"10.0.1.1","role":"PE Router"},
        {"hostname":"PE-DEL-01",  "ip":"10.0.2.1","role":"PE Router"},
        {"hostname":"DIST-SW-W",  "ip":"10.1.1.1","role":"Dist Switch"},
        {"hostname":"DIST-SW-C",  "ip":"10.1.2.1","role":"Dist Switch"},
        {"hostname":"FW-EDGE-01", "ip":"192.168.1.1","role":"Firewall"},
        {"hostname":"SW-ACC-14",  "ip":"10.2.14.1","role":"Access Switch"},
        {"hostname":"WLC-HQ-01",  "ip":"10.3.1.1","role":"WLC"},
    ]

    telemetry = []
    rng = random.Random(seed)

    for dev in devices[:device_count]:
        # Inject anomalies for specific devices
        if dev["hostname"] == "CORE-RTR-01":
            cpu  = rng.randint(82, 92)
            mem  = rng.randint(58, 68)
        elif dev["hostname"] == "PE-MUM-01":
            cpu  = rng.randint(28, 38)
            mem  = rng.randint(44, 52)
        elif dev["hostname"] == "SW-ACC-14":
            cpu  = 0
            mem  = 0
        else:
            cpu  = rng.randint(10, 45)
            mem  = rng.randint(25, 65)

        # Interface utilisation
        intf_util = []
        for i in range(4):
            util = rng.randint(5, 95) if dev["hostname"] != "SW-ACC-14" else 0
            intf_util.append({
                "interface": f"Gi0/{i}",
                "rx_mbps":   round(util * 0.8 * rng.uniform(0.8, 1.2), 1),
                "tx_mbps":   round(util * 0.6 * rng.uniform(0.8, 1.2), 1),
                "util_pct":  util,
                "errors":    rng.randint(0, 5) if util > 80 else 0,
            })

        # BGP sessions (routers only)
        bgp_sessions = []
        if "Router" in dev["role"] and dev["hostname"] != "SW-ACC-14":
            states = ["Established"] * 5 + ["Active"] if dev["hostname"] == "PE-MUM-01" else ["Established"] * 6
            for j in range(3):
                bgp_sessions.append({
                    "peer": f"10.0.{j+1}.1",
                    "state": states[j % len(states)],
                    "prefixes": rng.randint(80, 200) if states[j % len(states)] == "Established" else 0,
                    "updown": f"{rng.randint(0,5)}d{rng.randint(0,23)}h" if states[j % len(states)] == "Established" else "00:04:12",
                })

        telemetry.append({
            "hostname":      dev["hostname"],
            "ip":            dev["ip"],
            "role":          dev["role"],
            "cpu":           cpu,
            "memory":        mem,
            "status":        "critical" if cpu >= 85 or cpu == 0 else "warn" if cpu >= 70 else "up",
            "interfaces":    intf_util,
            "bgp_sessions":  bgp_sessions,
            "packet_loss":   round(rng.uniform(0, 2.5) if dev["hostname"] == "PE-MUM-01" else rng.uniform(0, 0.1), 3),
            "latency_ms":    rng.randint(12, 45) if dev["hostname"] != "SW-ACC-14" else 0,
            "ts":            datetime.utcnow().isoformat(),
        })

    return telemetry


def get_historical_telemetry(device: str, metric: str, hours: int = 24) -> List[dict]:
    """Generate historical telemetry series for a device/metric."""
    import time
    now = datetime.utcnow()
    series = []
    rng = random.Random(hash(device + metric))

    # Base values per device
    base_cpu = {"CORE-RTR-01": 75, "PE-MUM-01": 32}.get(device, 25)

    for i in range(hours * 4):   # 15-min intervals
        ts = now - timedelta(minutes=(hours * 60) - i * 15)
        # Add spike pattern
        spike = 15 if 20 <= i <= 25 else 0
        val = base_cpu + spike + rng.uniform(-8, 8)
        series.append({
            "ts": ts.strftime("%H:%M"),
            "value": round(max(0, min(100, val)), 1),
        })
    return series


# ══════════════════════════════════════════════════════════
# ANOMALY DETECTION
# ══════════════════════════════════════════════════════════
def detect_anomalies(telemetry: List[dict]) -> List[dict]:
    """
    Threshold-based anomaly detection.
    In production: replace with ML (Isolation Forest / Z-score).
    """
    anomalies = []

    for t in telemetry:
        hn = t["hostname"]

        # CPU anomaly
        if t["cpu"] >= 85:
            anomalies.append({
                "device":   hn,
                "type":     "cpu_high",
                "severity": "critical",
                "value":    f"{t['cpu']}%",
                "message":  f"{hn} CPU {t['cpu']}% — possible route churn or DoS",
                "ai_hint":  "Check OSPF SPF, BGP updates, or ACL hits",
            })
        elif t["cpu"] >= 70:
            anomalies.append({
                "device":   hn,
                "type":     "cpu_elevated",
                "severity": "warning",
                "value":    f"{t['cpu']}%",
                "message":  f"{hn} CPU elevated at {t['cpu']}%",
                "ai_hint":  "Monitor for escalation",
            })

        # Packet loss
        if t.get("packet_loss", 0) > 0.5:
            anomalies.append({
                "device":   hn,
                "type":     "packet_loss",
                "severity": "critical" if t["packet_loss"] > 1.5 else "warning",
                "value":    f"{t['packet_loss']}%",
                "message":  f"{hn} packet loss {t['packet_loss']}%",
                "ai_hint":  "Check interface errors, QoS drops, hardware issues",
            })

        # Interface errors
        for intf in t.get("interfaces", []):
            if intf.get("errors", 0) > 2:
                anomalies.append({
                    "device":   hn,
                    "type":     "interface_errors",
                    "severity": "warning",
                    "value":    str(intf["errors"]),
                    "message":  f"{hn} {intf['interface']} errors: {intf['errors']}",
                    "ai_hint":  "Check duplex mismatch, cable/SFP quality",
                })

        # BGP Active state
        for bgp in t.get("bgp_sessions", []):
            if bgp.get("state") == "Active":
                anomalies.append({
                    "device":   hn,
                    "type":     "bgp_active",
                    "severity": "critical",
                    "value":    bgp["peer"],
                    "message":  f"{hn} BGP peer {bgp['peer']} in Active state",
                    "ai_hint":  "Check TCP 179, remote-as, MD5 auth, update-source",
                })

    return sorted(anomalies, key=lambda x: {"critical":0,"warning":1}.get(x["severity"],2))


# ══════════════════════════════════════════════════════════
# SAAS EXPERIENCE MONITORING
# ══════════════════════════════════════════════════════════
def get_saas_health() -> List[dict]:
    """
    SaaS application health monitoring.
    In production: integrate with ThousandEyes or Catchpoint APIs.
    """
    import time
    seed = int(time.time() // 60)
    rng = random.Random(seed)

    services = [
        {"name":"Microsoft 365","icon":"📧","expected_ms":85},
        {"name":"Zoom",         "icon":"🎥","expected_ms":120},
        {"name":"Salesforce",   "icon":"☁","expected_ms":150},
        {"name":"ServiceNow",   "icon":"🎫","expected_ms":130},
        {"name":"GitHub",       "icon":"🐙","expected_ms":95},
        {"name":"AWS Console",  "icon":"🟡","expected_ms":110},
        {"name":"Azure Portal", "icon":"🔷","expected_ms":100},
        {"name":"Okta SSO",     "icon":"🔐","expected_ms":75},
    ]

    results = []
    for svc in services:
        latency = svc["expected_ms"] + rng.randint(-30, 80)
        loss    = round(rng.uniform(0, 0.3), 2)
        # Inject degradation for M365 during BGP issues
        if svc["name"] == "Microsoft 365":
            latency += 45
            loss     = 0.8

        score = max(0, 100 - (latency - svc["expected_ms"]) // 5 - int(loss * 20))
        results.append({
            "name":       svc["name"],
            "icon":       svc["icon"],
            "latency_ms": latency,
            "loss_pct":   loss,
            "score":      score,
            "status":     "ok" if score >= 85 else "degraded" if score >= 60 else "critical",
            "trend":      "↑" if latency > svc["expected_ms"] + 40 else "→",
        })

    return sorted(results, key=lambda x: x["score"])


# ══════════════════════════════════════════════════════════
# NETFLOW SUMMARY
# ══════════════════════════════════════════════════════════
def get_netflow_summary() -> dict:
    """Top talkers and protocol distribution from NetFlow."""
    import time
    rng = random.Random(int(time.time() // 30))
    return {
        "top_talkers": [
            {"src":"10.1.100.45","dst":"52.96.0.0/14","app":"Microsoft 365","mbps":round(rng.uniform(180,320),1)},
            {"src":"10.1.100.87","dst":"13.107.64.0/18","app":"Teams","mbps":round(rng.uniform(95,185),1)},
            {"src":"10.2.0.0/16","dst":"8.8.8.8","app":"DNS","mbps":round(rng.uniform(12,28),1)},
            {"src":"10.0.0.0/8", "dst":"172.217.0.0/16","app":"Google","mbps":round(rng.uniform(45,90),1)},
            {"src":"10.3.0.0/16","dst":"104.244.42.0/24","app":"Twitter","mbps":round(rng.uniform(8,22),1)},
        ],
        "protocol_mix": {"TCP":72,"UDP":18,"ICMP":4,"HTTPS":78,"HTTP":8,"DNS":6,"Other":8},
        "total_gbps":   round(rng.uniform(1.8, 4.2), 2),
        "flows_per_sec":rng.randint(12000, 45000),
    }


# ══════════════════════════════════════════════════════════
# SYSLOG INGESTION
# ══════════════════════════════════════════════════════════
def get_recent_syslogs(limit: int = 20) -> List[dict]:
    """Recent syslog events from network devices."""
    import time
    rng = random.Random(int(time.time() // 20))

    templates = [
        ("critical","PE-MUM-01","%BGP-5-ADJCHANGE: neighbor 10.0.1.1 Down BGP Notification sent"),
        ("warning", "CORE-RTR-01","%OSPF-4-NONEIGHBOR: Received OSPF packet from unknown neighbor"),
        ("critical","SW-ACC-14","%LINK-3-UPDOWN: Interface GigabitEthernet0/3, changed state to down"),
        ("warning", "CORE-RTR-01","%CPU_MONITOR-5-RISING_THRESHOLD: CPU Utilization(88%) above threshold"),
        ("info",    "FW-EDGE-01","%ASA-6-302013: Built inbound TCP connection 12345 for outside:203.0.113.1/54321"),
        ("warning", "PE-DEL-01", "%BGP-3-NOTIFICATION: received from neighbor 10.0.2.1 (Hold Timer Expired)"),
        ("info",    "WLC-HQ-01", "%DOT11-6-DISASSOC: Station 00:1A:2B:3C:4D:5E roaming to AP-HQ-02"),
        ("info",    "DIST-SW-W", "%LINEPROTO-5-UPDOWN: Line protocol on Interface Port-channel1, changed state to up"),
    ]

    logs = []
    now = datetime.utcnow()
    for i, (sev, device, msg) in enumerate(templates[:limit]):
        logs.append({
            "severity": sev,
            "device":   device,
            "message":  msg,
            "ts":       (now - timedelta(minutes=i * rng.randint(1,8))).strftime("%H:%M:%S"),
        })
    return logs


# ══ DIGITAL TWIN ═════════════════════════════════════

import logging, copy
from typing import List, Optional
try:
    import streamlit as st
    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False
    class _FakeSt:
        def cache_data(self, *a, **k): return lambda f: f
        def cache_resource(self, *a, **k): return lambda f: f
    st = _FakeSt()


# ══════════════════════════════════════════════════════════
# TOPOLOGY KNOWLEDGE — device relationships
# ══════════════════════════════════════════════════════════
TOPOLOGY = {
    "CORE-RTR-01": {
        "role":        "core_router",
        "connects_to": ["FW-EDGE-01","DIST-SW-W","DIST-SW-C","PE-MUM-01"],
        "protocols":   ["OSPF","BGP","MPLS"],
        "services":    ["Internet routing","Internal routing","MPLS backbone"],
        "criticality": 10,   # 1-10 scale
    },
    "PE-MUM-01": {
        "role":        "pe_router",
        "connects_to": ["CORE-RTR-01","ISP-AS65002"],
        "protocols":   ["BGP","MPLS","L3VPN"],
        "services":    ["Mumbai ISP","MPLS WAN","Cloud connectivity"],
        "criticality": 9,
    },
    "PE-DEL-01": {
        "role":        "pe_router",
        "connects_to": ["CORE-RTR-01","ISP-AS65003"],
        "protocols":   ["BGP","MPLS","L3VPN"],
        "services":    ["Delhi ISP","MPLS WAN"],
        "criticality": 8,
    },
    "FW-EDGE-01": {
        "role":        "firewall",
        "connects_to": ["CORE-RTR-01","INTERNET"],
        "protocols":   ["IPSec","NAT","ACL"],
        "services":    ["Internet egress","VPN","Security inspection"],
        "criticality": 9,
        "is_spof":     True,
    },
    "DIST-SW-W": {
        "role":        "dist_switch",
        "connects_to": ["CORE-RTR-01","SW-ACC-14","SW-ACC-1","SW-ACC-2"],
        "protocols":   ["OSPF","STP","HSRP","VLAN"],
        "services":    ["HQ-West access layer","VLAN routing"],
        "criticality": 7,
    },
    "DIST-SW-C": {
        "role":        "dist_switch",
        "connects_to": ["CORE-RTR-01","SW-ACC-3","SW-ACC-4"],
        "protocols":   ["OSPF","STP","HSRP","VLAN"],
        "services":    ["HQ-Central access layer"],
        "criticality": 7,
    },
    "SW-ACC-14": {
        "role":        "access_switch",
        "connects_to": ["DIST-SW-W"],
        "protocols":   ["STP","VLAN"],
        "services":    ["Floor 2 user access","VLAN 120"],
        "criticality": 4,
    },
}

USERS_PER_SERVICE = {
    "Internet egress": 847,
    "Mumbai ISP": 340,
    "Delhi ISP": 180,
    "Floor 2 user access": 47,
    "HQ-West access layer": 150,
    "HQ-Central access layer": 180,
    "Internal routing": 847,
    "MPLS WAN": 500,
}


# ══════════════════════════════════════════════════════════
# FAILURE SIMULATION
# ══════════════════════════════════════════════════════════
def simulate_failure(device_hostname: str) -> dict:
    """
    Simulate complete device failure.
    Returns: impact analysis, affected paths, failover time, recommendations.
    """
    device = TOPOLOGY.get(device_hostname)
    if not device:
        return {"error": f"Device {device_hostname} not in topology model"}

    impact = {
        "failed_device":    device_hostname,
        "criticality":      device.get("criticality", 5),
        "is_spof":          device.get("is_spof", False),
        "directly_impacted":[],
        "cascade_impacted": [],
        "affected_services":[],
        "affected_users":   0,
        "protocols_lost":   device.get("protocols", []),
        "failover_possible":False,
        "failover_device":  None,
        "estimated_rto_s":  None,
        "severity":         "critical" if device.get("criticality",5) >= 8 else "major",
    }

    # Direct impact — devices that connect through failed device
    for dev_name, dev_data in TOPOLOGY.items():
        if device_hostname in dev_data.get("connects_to", []):
            impact["directly_impacted"].append(dev_name)

    # Cascade — services on failed device
    impact["affected_services"] = device.get("services", [])

    # Calculate affected users
    for svc in impact["affected_services"]:
        impact["affected_users"] += USERS_PER_SERVICE.get(svc, 0)
    impact["affected_users"] = min(impact["affected_users"], 847)   # cap at total

    # Failover analysis
    redundant_pairs = {
        "PE-MUM-01": ("PE-DEL-01", 3),    # 3s failover with BFD
        "PE-DEL-01": ("PE-MUM-01", 3),
        "DIST-SW-W": ("DIST-SW-C", 30),   # STP convergence
        "DIST-SW-C": ("DIST-SW-W", 30),
    }
    if device_hostname in redundant_pairs:
        impact["failover_possible"] = True
        impact["failover_device"]   = redundant_pairs[device_hostname][0]
        impact["estimated_rto_s"]   = redundant_pairs[device_hostname][1]
    elif not impact["is_spof"]:
        impact["failover_possible"] = True
        impact["estimated_rto_s"]   = 60

    # SPOF — no failover
    if impact["is_spof"]:
        impact["failover_possible"] = False
        impact["estimated_rto_s"]   = None
        impact["severity"] = "critical"

    # Recommendations
    impact["recommendations"] = _generate_failure_recommendations(device_hostname, impact)
    impact["affected_paths"]  = _trace_affected_paths(device_hostname)

    return impact


def _generate_failure_recommendations(hostname: str, impact: dict) -> List[str]:
    recs = []
    if impact["is_spof"]:
        recs.append(f"⚠️ CRITICAL: {hostname} is a SPOF — add redundant device immediately")
    if impact["failover_possible"]:
        recs.append(f"✅ Failover to {impact['failover_device']} in ~{impact['estimated_rto_s']}s")
    if impact["affected_users"] > 200:
        recs.append("🚨 Open P1 bridge call — >200 users impacted")
    recs.append(f"Enable BFD on all {hostname} uplinks to reduce detection time")
    recs.append(f"Verify {impact.get('failover_device','backup device')} can handle full load")
    return recs


def _trace_affected_paths(hostname: str) -> List[dict]:
    """Trace traffic paths that go through the failed device."""
    paths = []
    for dev_name, dev_data in TOPOLOGY.items():
        if hostname in dev_data.get("connects_to", []):
            paths.append({
                "from": dev_name,
                "through": hostname,
                "to": "upstream",
                "status": "BROKEN",
            })
    return paths[:5]   # top 5


# ══════════════════════════════════════════════════════════
# CHANGE SIMULATION
# ══════════════════════════════════════════════════════════
def simulate_change(device: str, change_type: str, change_desc: str) -> dict:
    """Simulate the impact of a proposed change before production."""
    dev_info = TOPOLOGY.get(device, {})
    criticality = dev_info.get("criticality", 5)

    risks = []
    downtime_s = 0
    affected_services = dev_info.get("services", [])

    if change_type == "firmware":
        downtime_s = 180   # 3 min reload
        risks.append("Device reload required — ~3 min downtime")
        risks.append(f"Failover to redundant device during reload")
        if criticality >= 9:
            risks.append("⚠️ Core device — maintenance window MANDATORY")
    elif change_type == "config":
        downtime_s = 0
        risks.append("Config change — no reload needed if done correctly")
        risks.append("Rollback available within 30s using 'reload in 5' technique")
    elif change_type == "vlan":
        downtime_s = 2
        risks.append("Brief L2 flap during VLAN add/remove")
    elif change_type == "routing":
        downtime_s = 5
        risks.append("Routing convergence ~1-30s depending on protocol")
        risks.append("Ensure backup path exists before changes")

    affected_users = sum(USERS_PER_SERVICE.get(s, 0) for s in affected_services)

    return {
        "device":            device,
        "change_type":       change_type,
        "description":       change_desc,
        "predicted_downtime":downtime_s,
        "affected_services": affected_services,
        "affected_users":    affected_users,
        "risks":             risks,
        "risk_score":        _calc_change_risk(criticality, downtime_s, affected_users),
        "dry_run_safe":      downtime_s == 0,
        "maintenance_window_required": criticality >= 9 or downtime_s >= 60,
        "rollback_steps":    _generate_rollback(device, change_type),
    }


def _calc_change_risk(criticality: int, downtime_s: int, users: int) -> int:
    score = criticality * 5
    score += min(30, downtime_s // 6)
    score += min(20, users // 50)
    return min(100, score)


def _generate_rollback(device: str, change_type: str) -> List[str]:
    steps = []
    if change_type == "firmware":
        steps = [
            f"1. boot system flash {device.lower()}-previous.bin",
            "2. reload (confirm within maintenance window)",
            "3. Verify all protocols re-establish",
            "4. Remove failed firmware image",
        ]
    elif change_type == "config":
        steps = [
            "1. copy running-config startup-config (save known-good state first)",
            "2. Use 'reload in 5' safety net before applying changes",
            "3. If issues: reload to abort pending reload timer",
            "4. OR: configure replace flash:known_good_config",
        ]
    elif change_type == "vlan":
        steps = ["1. no vlan <id>", "2. Verify affected ports recover", "3. Check STP topology"]
    return steps


# ══════════════════════════════════════════════════════════
# TOPOLOGY CLONE STATUS
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=60)
def get_twin_status() -> dict:
    return {
        "cloned_devices":  len(TOPOLOGY),
        "accuracy_pct":    99.2,
        "last_sync_s":     14,
        "active_simulations": 3,
        "changes_tested":  47,
    }


# ══ COMPLIANCE ═══════════════════════════════════════

import logging
from typing import List
import streamlit as st


# ══════════════════════════════════════════════════════════
# COMPLIANCE FRAMEWORKS
# ══════════════════════════════════════════════════════════
FRAMEWORKS = {
    "CIS Benchmark v8": {
        "score":       91,
        "max":         100,
        "controls":    256,
        "violations":  23,
        "color":       "green",
        "description": "Network device hardening baseline",
        "top_gaps": [
            "IG1-4.1: Establish/maintain detailed asset inventory for 6 devices",
            "IG1-12.2: Ensure anti-malware on 3 edge appliances",
            "IG2-6.3: Collect audit logs from all 8 core devices",
            "IG2-9.4: Configure automatic session timeouts on VTY lines",
        ],
    },
    "NIST CSF 2.0": {
        "score":       78,
        "max":         100,
        "controls":    108,
        "violations":  24,
        "color":       "amber",
        "description": "Cybersecurity framework — Govern/Identify/Protect/Detect/Respond/Recover",
        "top_gaps": [
            "GV.OC-03: Supply chain risk management policy missing",
            "ID.AM-07: Software asset inventory incomplete",
            "PR.AC-04: MFA not enforced on 12% of admin accounts",
            "DE.AE-02: Security events not normalized into SIEM",
        ],
    },
    "PCI DSS 4.0": {
        "score":       96,
        "max":         100,
        "controls":    264,
        "violations":  11,
        "color":       "green",
        "description": "Payment card industry — cardholder data network",
        "top_gaps": [
            "Req 1.3.2: CDE egress rules need quarterly review documentation",
            "Req 2.2.1: System config standards not updated for 2 new device models",
            "Req 10.3.3: Audit log backup retention verification needed",
        ],
    },
    "ISO 27001:2022": {
        "score":       88,
        "max":         100,
        "controls":    93,
        "violations":  11,
        "color":       "green",
        "description": "Information security management system",
        "top_gaps": [
            "A.8.8: Management of technical vulnerabilities — 14 CVEs open",
            "A.5.23: Security for use of cloud services — policy gap",
            "A.8.15: Logging not centralized for 3 branch routers",
        ],
    },
    "Zero Trust Maturity": {
        "score":       62,
        "max":         100,
        "controls":    50,
        "violations":  19,
        "color":       "amber",
        "description": "CISA Zero Trust Maturity Model v2",
        "top_gaps": [
            "Identity Pillar: MFA coverage 88% — target 100%",
            "Network Pillar: Micro-segmentation covers only 40% of east-west",
            "Device Pillar: Device health posture check missing for 120 endpoints",
            "Application Pillar: ZTNA deployed for 3/8 critical apps only",
        ],
    },
    "CVE Exposure": {
        "score":       70,
        "max":         100,
        "controls":    None,
        "violations":  14,
        "color":       "red",
        "description": "Unpatched vulnerabilities on network devices",
        "top_gaps": [
            "CRITICAL: CVE-2024-20399 — Cisco IOS-XR CORE-RTR-01 (CVSS 9.1)",
            "CRITICAL: CVE-2024-3400 — PAN-OS FW-EDGE-01 (CVSS 10.0)",
            "CRITICAL: CVE-2024-21591 — Juniper JunOS PE-DEL-01 (CVSS 9.8)",
            "HIGH: 11 additional CVEs across 5 devices",
        ],
    },
}

# ══════════════════════════════════════════════════════════
# CONFIG DRIFT DETECTION
# ══════════════════════════════════════════════════════════
CONFIG_VIOLATIONS = [
    {
        "device":    "CORE-RTR-01",
        "rule":      "CIS IOS-XR 1.2.1",
        "finding":   "VTY session timeout not configured (should be ≤ 10 min)",
        "severity":  "medium",
        "remediation":"line vty 0 4\n exec-timeout 10 0",
    },
    {
        "device":    "PE-MUM-01",
        "rule":      "CIS IOS-XR 3.3.1",
        "finding":   "BGP password not set on iBGP peer 10.0.2.1",
        "severity":  "high",
        "remediation":"neighbor 10.0.2.1\n password 7 <encrypted>",
    },
    {
        "device":    "DIST-SW-W",
        "rule":      "CIS IOS 3.4.2",
        "finding":   "SNMP community string 'public' still active",
        "severity":  "critical",
        "remediation":"no snmp-server community public\nsnmp-server community <strong-string> RO",
    },
    {
        "device":    "FW-EDGE-01",
        "rule":      "PAN-OS CIS 1.1.3",
        "finding":   "Admin session idle timeout set to 60 min (should be 10)",
        "severity":  "medium",
        "remediation":"Set admin idle timeout to 10 minutes in Device > Setup > Management",
    },
    {
        "device":    "SW-ACC-14",
        "rule":      "CIS IOS 2.1.1",
        "finding":   "Unused interfaces not administratively shut down (Gi0/4-Gi0/24)",
        "severity":  "low",
        "remediation":"interface range Gi0/4-24\n shutdown\n description [UNUSED]",
    },
]


def get_compliance_summary() -> dict:
    """Overall compliance posture summary."""
    scores = [f["score"] for f in FRAMEWORKS.values()]
    avg = sum(scores) // len(scores)
    critical_fw = [k for k, v in FRAMEWORKS.items() if v["color"] == "red"]
    return {
        "overall_score":   avg,
        "frameworks":      len(FRAMEWORKS),
        "total_violations":sum(f["violations"] for f in FRAMEWORKS.values()),
        "critical_frameworks": critical_fw,
        "frameworks_detail": FRAMEWORKS,
        "config_violations": CONFIG_VIOLATIONS,
    }


def get_framework_detail(framework_name: str) -> dict:
    return FRAMEWORKS.get(framework_name, {})


def get_remediation_priority() -> List[dict]:
    """Return prioritized remediation list across all frameworks."""
    items = []
    for fw_name, fw in FRAMEWORKS.items():
        for gap in fw.get("top_gaps", []):
            severity = "critical" if "CRITICAL" in gap else "high" if "HIGH" in gap else "medium"
            items.append({"framework": fw_name, "gap": gap, "severity": severity})
    items.sort(key=lambda x: {"critical":0,"high":1,"medium":2}.get(x["severity"],3))
    return items


def get_zero_trust_pillars() -> List[dict]:
    return [
        {"pillar":"Identity",    "score":88,"gaps":["MFA gap 12%","PAM not deployed"]},
        {"pillar":"Device",      "score":55,"gaps":["Posture check missing","MDM partial"]},
        {"pillar":"Network",     "score":40,"gaps":["Micro-seg 40%","East-west uninspected"]},
        {"pillar":"Application", "score":62,"gaps":["ZTNA 3/8 apps","App inventory gap"]},
        {"pillar":"Data",        "score":70,"gaps":["DLP partial","Cloud data unclassified"]},
        {"pillar":"Visibility",  "score":75,"gaps":["SIEM gaps","NDR not deployed"]},
    ]


# ══ SELF HEALING ═════════════════════════════════════

import logging
from datetime import datetime
from typing import List, Optional
import streamlit as st


# ══════════════════════════════════════════════════════════
# HEALING POLICIES
# ══════════════════════════════════════════════════════════
HEALING_POLICIES = [
    {
        "id":          "BGP_FLAP_BFD",
        "name":        "BGP Flap — Enable BFD",
        "trigger":     "BGP session flaps > 2 in 30 minutes",
        "condition":   lambda telemetry: any(
            bgp.get("state") == "Active"
            for t in telemetry for bgp in t.get("bgp_sessions", [])
        ),
        "action":      "Enable BFD on BGP peer interface to reduce detection time",
        "cli":         "router bgp 65001\n neighbor {peer} fall-over bfd\nbfd all-interfaces",
        "risk":        "low",
        "auto_execute": True,
        "rollback":    "no bfd all-interfaces",
        "confidence":  91,
    },
    {
        "id":          "HIGH_CPU_OSPF",
        "name":        "High CPU — OSPF SPF Throttle",
        "trigger":     "CPU > 85% with OSPF SPF in top processes",
        "condition":   lambda telemetry: any(t.get("cpu", 0) >= 85 for t in telemetry),
        "action":      "Apply OSPF SPF throttle timers to reduce computation frequency",
        "cli":         "router ospf 1\n timers throttle spf 5000 10000 40000",
        "risk":        "low",
        "auto_execute": False,   # Needs human approval
        "rollback":    "router ospf 1\n no timers throttle spf",
        "confidence":  78,
    },
    {
        "id":          "INTERFACE_BOUNCE",
        "name":        "Interface Error Recovery — Bounce",
        "trigger":     "Interface error rate > 1000 errors/min for 5 consecutive minutes",
        "condition":   lambda telemetry: any(
            intf.get("errors", 0) > 5
            for t in telemetry for intf in t.get("interfaces", [])
        ),
        "action":      "Bounce interface to clear error counter and reset physical layer",
        "cli":         "interface {interface}\n shutdown\n no shutdown",
        "risk":        "medium",
        "auto_execute": False,
        "rollback":    "interface {interface}\n no shutdown",
        "confidence":  82,
    },
    {
        "id":          "BGP_HOLD_TIMER",
        "name":        "BGP Hold-Timer Increase",
        "trigger":     "BGP hold-timer expiry detected (3+ occurrences)",
        "condition":   lambda telemetry: False,  # Triggered by incident, not live telemetry
        "action":      "Increase BGP hold-timer from 60s to 90s to reduce flapping",
        "cli":         "router bgp 65001\n neighbor {peer} timers 30 90",
        "risk":        "low",
        "auto_execute": False,
        "rollback":    "router bgp 65001\n neighbor {peer} timers 20 60",
        "confidence":  78,
    },
    {
        "id":          "SNMP_TRAP_FORWARD",
        "name":        "Critical Alert — SNMP Trap Forward",
        "trigger":     "Critical severity event on any device",
        "condition":   lambda telemetry: any(t.get("status") == "critical" for t in telemetry),
        "action":      "Forward SNMP trap to NOC and create incident ticket",
        "cli":         "snmp-server host 10.0.0.100 traps public",
        "risk":        "low",
        "auto_execute": True,
        "rollback":    None,
        "confidence":  99,
    },
]


# ══════════════════════════════════════════════════════════
# HEALING EVALUATION
# ══════════════════════════════════════════════════════════
def evaluate_triggers(telemetry: List[dict]) -> List[dict]:
    """
    Evaluate all healing policies against current telemetry.
    Returns list of triggered policies with recommended actions.
    """
    triggered = []
    for policy in HEALING_POLICIES:
        try:
            if policy["condition"](telemetry):
                triggered.append({
                    "id":           policy["id"],
                    "name":         policy["name"],
                    "trigger":      policy["trigger"],
                    "action":       policy["action"],
                    "cli":          policy["cli"],
                    "risk":         policy["risk"],
                    "auto_execute": policy["auto_execute"],
                    "rollback":     policy["rollback"],
                    "confidence":   policy["confidence"],
                    "status":       "auto_executing" if policy["auto_execute"] else "pending_approval",
                    "ts":           datetime.utcnow().isoformat(),
                })
        except Exception as e:
            logger.debug(f"Policy eval error {policy['id']}: {e}")
    return triggered


# ══════════════════════════════════════════════════════════
# EXECUTION PIPELINE
# ══════════════════════════════════════════════════════════
def stage_execution(action: dict, mode: str = "human") -> dict:
    """
    Stage an autonomous action through the execution pipeline.
    mode: human | semi | full
    Returns execution plan with stages.
    """
    stages = [
        {"stage": "validate",    "status": "pending", "description": "Validate pre-conditions"},
        {"stage": "dry_run",     "status": "pending", "description": "Shadow mode test (no-op)"},
        {"stage": "human_review","status": "pending" if mode in ("human","semi") else "skipped",
         "description": "Human approval gate"},
        {"stage": "execute",     "status": "pending", "description": "Apply to production"},
        {"stage": "verify",      "status": "pending", "description": "Verify remediation worked"},
        {"stage": "learn",       "status": "pending", "description": "Record outcome to memory"},
    ]
    if mode == "full" and action.get("risk") == "low":
        for s in stages:
            if s["stage"] == "human_review":
                s["status"] = "auto_approved"
    return {
        "action":  action,
        "mode":    mode,
        "stages":  stages,
        "plan_id": f"HEAL-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
    }


# ══════════════════════════════════════════════════════════
# METRICS
# ══════════════════════════════════════════════════════════
def get_healing_metrics() -> dict:
    return {
        "total_actions_week":  47,
        "auto_executed":       35,
        "pending_approval":    1,
        "success_rate_pct":    94,
        "failed":              2,
        "time_saved_hours":    4.2,
        "mttr_reduction_pct":  38,
        "active_policies":     len(HEALING_POLICIES),
    }


def get_policies() -> List[dict]:
    return [
        {k: v for k, v in p.items() if k != "condition"}
        for p in HEALING_POLICIES
    ]


# ══ INCIDENT ENGINE ══════════════════════════════════

import logging, hashlib
from datetime import datetime, timedelta
from typing import List, Optional
try:
    import streamlit as st
    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False
    class _FakeSt:
        def cache_data(self, *a, **k): return lambda f: f
        def cache_resource(self, *a, **k): return lambda f: f
    st = _FakeSt()



# ══════════════════════════════════════════════════════════
# BLAST RADIUS CALCULATOR
# ══════════════════════════════════════════════════════════
PROTOCOL_DEPENDENCIES = {
    "BGP":  {"OSPF": 0.6, "MPLS": 0.9, "SD-WAN": 0.8, "L3VPN": 0.95},
    "OSPF": {"BGP": 0.4,  "STP": 0.2,  "MPLS": 0.5},
    "STP":  {"VLAN": 0.9, "EtherChannel": 0.7},
    "VLAN": {"STP": 0.5,  "HSRP": 0.7, "VRRP": 0.7},
    "MPLS": {"BGP": 0.8,  "L3VPN": 0.99, "L2VPN": 0.99},
    "IPSec":{"SD-WAN": 0.6, "VPN": 0.99},
}

PROTOCOL_SERVICES = {
    "BGP":  ["Internet access","SD-WAN routing","MPLS services","Cloud connectivity"],
    "OSPF": ["Internal routing","DC fabric","Campus routing"],
    "VLAN": ["User access","Server access","VOIP","Video"],
    "MPLS": ["L3VPN","L2VPN","Enterprise WAN","Cloud Connect"],
    "IPSec":["Remote access VPN","Branch connectivity","Cloud VPN"],
    "STP":  ["Campus L2","Access layer","VLAN forwarding"],
    "BGP":  ["Internet egress","Cloud breakout","Peering","SaaS access"],
}


def calculate_blast_radius(
    protocols: List[str],
    devices: List[str],
    affected_users: int = 0,
) -> dict:
    """
    Calculate blast radius for an incident.
    Returns: affected_protocols, affected_services, risk_score, propagation_path
    """
    affected_protocols = set(protocols)
    affected_services = set()

    # Protocol cascade
    for proto in protocols:
        deps = PROTOCOL_DEPENDENCIES.get(proto, {})
        for dep_proto, probability in deps.items():
            if probability > 0.5:
                affected_protocols.add(dep_proto)
        services = PROTOCOL_SERVICES.get(proto, [])
        affected_services.update(services)

    # Risk score calculation
    base_score = min(100, len(devices) * 15 + affected_users // 20 + len(affected_protocols) * 8)
    critical_protocols = {"BGP", "OSPF", "MPLS"}
    if affected_protocols & critical_protocols:
        base_score = min(100, base_score + 20)

    return {
        "affected_protocols": list(affected_protocols),
        "affected_services":  list(affected_services),
        "risk_score":         base_score,
        "device_count":       len(devices),
        "user_impact":        affected_users,
        "propagation_path":   _build_propagation_path(list(affected_protocols)),
    }


def _build_propagation_path(protocols: List[str]) -> List[str]:
    """Build ordered propagation chain."""
    order = ["BGP", "OSPF", "MPLS", "L3VPN", "SD-WAN", "STP", "VLAN", "IPSec"]
    path = [p for p in order if p in protocols]
    extras = [p for p in protocols if p not in order]
    return path + extras


# ══════════════════════════════════════════════════════════
# INCIDENT CORRELATION ENGINE
# ══════════════════════════════════════════════════════════
def correlate_incidents(incidents: List[dict] = None) -> List[dict]:
    """
    Group related incidents by root cause correlation.
    Returns correlated groups with shared root cause analysis.
    """
    if not incidents:
        return []
    ungrouped = list(incidents)

    while ungrouped:
        anchor = ungrouped.pop(0)
        group = {"root": anchor, "related": [], "correlation_score": 100}

        anchor_protocols = set((anchor.get("protocols") or "").split(","))
        anchor_title = anchor.get("title", "").lower()

        remaining = []
        for inc in ungrouped:
            inc_protocols = set((inc.get("protocols") or "").split(","))
            overlap = anchor_protocols & inc_protocols

            # Temporal proximity (within 30 min)
            try:
                t1 = datetime.fromisoformat(anchor.get("created_at", "2024-01-01"))
                t2 = datetime.fromisoformat(inc.get("created_at", "2024-01-01"))
                time_close = abs((t1 - t2).total_seconds()) < 1800
            except Exception:
                time_close = False

            correlation = 0
            if overlap: correlation += len(overlap) * 25
            if time_close: correlation += 30

            if correlation >= 30:
                group["related"].append({**inc, "correlation": correlation})
                group["correlation_score"] = min(group["correlation_score"], correlation)
            else:
                remaining.append(inc)

        groups.append(group)
        ungrouped = remaining

    return groups


# ══════════════════════════════════════════════════════════
# OPERATIONAL MEMORY
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=300)
def get_similar_incidents_from_memory(
    query_protocols: List[str],
    query_text: str,
    incidents: List[dict],
    limit: int = 3,
) -> List[dict]:
    """
    Search incident history for similar past incidents.
    Used to inject operational memory into AI context.
    """
    if not incidents:
        return []

    query_text_lower = query_text.lower()
    scored = []

    for inc in incidents:
        score = 0
        # Protocol overlap
        inc_protocols = (inc.get("protocols") or "").split(",")
        for p in query_protocols:
            if any(p.strip().upper() in ip.upper() for ip in inc_protocols):
                score += 30

        # Title/description text similarity
        inc_text = f"{inc.get('title','')} {inc.get('description','')} {inc.get('root_cause','')}".lower()
        for word in query_text_lower.split():
            if len(word) > 4 and word in inc_text:
                score += 5

        # Prefer resolved (have RCA + fix)
        if inc.get("status") == "resolved" and inc.get("root_cause"):
            score += 20

        if score > 20:
            scored.append((score, inc))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [inc for _, inc in scored[:limit]]


def build_memory_context(similar: List[dict]) -> str:
    """Format similar incidents for AI injection."""
    if not similar:
        return ""
    parts = []
    for inc in similar:
        parts.append(
            f"PAST INCIDENT: {inc['title']}\n"
            f"  Root Cause: {inc.get('root_cause','unknown')}\n"
            f"  Resolution: {inc.get('resolution','unknown')}\n"
            f"  Protocols: {inc.get('protocols','')}"
        )
    return "\n\n".join(parts)


# ══════════════════════════════════════════════════════════
# INCIDENT TIMELINE BUILDER
# ══════════════════════════════════════════════════════════
def build_incident_timeline(incident: dict, autonomous_actions: List[dict]) -> List[dict]:
    """Reconstruct the complete operational timeline for an incident."""
    timeline = []

    # Incident creation
    timeline.append({
        "type":     "detection",
        "icon":     "🔴",
        "severity": "critical",
        "title":    f"Incident Detected: {incident['title']}",
        "detail":   incident.get("description", ""),
        "ts":       incident.get("created_at", ""),
    })

    # Correlated autonomous actions
    for action in autonomous_actions:
        if any(dev in action.get("trigger", "") for dev in (incident.get("devices_str", "").split(","))):
            timeline.append({
                "type":     "auto_action",
                "icon":     "🤖",
                "severity": "info",
                "title":    f"AI Action: {action['action']}",
                "detail":   action.get("result", ""),
                "ts":       action.get("created_at", ""),
            })

    # Resolution if exists
    if incident.get("status") == "resolved":
        timeline.append({
            "type":     "resolved",
            "icon":     "✅",
            "severity": "ok",
            "title":    "Incident Resolved",
            "detail":   incident.get("resolution", ""),
            "ts":       incident.get("resolved_at", ""),
        })

    return timeline


# ══════════════════════════════════════════════════════════
# CONFIDENCE SCORING
# ══════════════════════════════════════════════════════════
def calculate_rca_confidence(
    evidence_count: int,
    similar_incidents: int,
    protocol_count: int,
    has_logs: bool = False,
) -> int:
    """Calculate AI RCA confidence score 0-100."""
    base = 40
    base += min(30, evidence_count * 10)
    base += min(20, similar_incidents * 10)
    base += min(5, protocol_count * 2)
    if has_logs: base += 10
    return min(99, base)


# ══ KNOWLEDGE GRAPH ══════════════════════════════════

from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class KGNode:
    id: str
    node_type: str   # device | interface | protocol | service | site | user_group | circuit
    label: str
    metadata: dict = field(default_factory=dict)
    status: str = "unknown"   # up | warn | critical | unknown

@dataclass
class KGEdge:
    source: str
    target: str
    relationship: str   # connects_to | runs_on | depends_on | serves | affects
    weight: float = 1.0
    metadata: dict = field(default_factory=dict)


# ══════════════════════════════════════════════════════════
# PRE-BUILT ENTERPRISE KNOWLEDGE GRAPH
# ══════════════════════════════════════════════════════════
NODES: List[KGNode] = [
    # Devices
    KGNode("core-rtr-01","device","CORE-RTR-01",  {"ip":"10.0.0.1","role":"Core Router","site":"HQ"},"warn"),
    KGNode("pe-mum-01",  "device","PE-MUM-01",    {"ip":"10.0.1.1","role":"PE Router","site":"Mumbai"},"critical"),
    KGNode("pe-del-01",  "device","PE-DEL-01",    {"ip":"10.0.2.1","role":"PE Router","site":"Delhi"},"up"),
    KGNode("fw-edge-01", "device","FW-EDGE-01",   {"ip":"192.168.1.1","role":"Firewall","spof":True},"up"),
    KGNode("dist-sw-w",  "device","DIST-SW-W",    {"ip":"10.1.1.1","role":"Dist Switch"},"up"),
    KGNode("dist-sw-c",  "device","DIST-SW-C",    {"ip":"10.1.2.1","role":"Dist Switch"},"warn"),
    KGNode("sw-acc-14",  "device","SW-ACC-14",    {"ip":"10.2.14.1","role":"Access Switch"},"critical"),
    KGNode("wlc-hq-01",  "device","WLC-HQ-01",   {"ip":"10.3.1.1","role":"WLC"},"up"),
    # Protocols
    KGNode("proto-bgp",  "protocol","BGP",         {"asn":"65001","peers":3},"warn"),
    KGNode("proto-ospf", "protocol","OSPF",        {"area":"0","neighbors":4},"warn"),
    KGNode("proto-mpls", "protocol","MPLS",        {"lsps":12},"up"),
    KGNode("proto-vxlan","protocol","VXLAN/EVPN",  {},"up"),
    KGNode("proto-ipsec","protocol","IPSec",       {"tunnels":8},"up"),
    # Services
    KGNode("svc-internet","service","Internet Access",  {"users":847,"revenue_risk":"HIGH"},"warn"),
    KGNode("svc-mum",     "service","Mumbai Branch SaaS",{"users":340,"revenue_risk":"HIGH"},"critical"),
    KGNode("svc-del",     "service","Delhi Branch",    {"users":180,"revenue_risk":"MEDIUM"},"up"),
    KGNode("svc-vlan120", "service","Floor 2 Users",   {"users":47,"vlan":120},"critical"),
    KGNode("svc-mpls",    "service","MPLS WAN",        {"sites":12},"up"),
    KGNode("svc-vpn",     "service","Remote VPN",      {"users":230},"up"),
    # Sites
    KGNode("site-hq",    "site","HQ Mumbai",     {"users":400},"warn"),
    KGNode("site-del",   "site","Delhi Office",  {"users":180},"up"),
    KGNode("site-branches","site","12 Branches", {"users":267},"up"),
    # Cloud
    KGNode("cloud-azure","cloud","Azure (East)",  {"services":["M365","AKS","CosmosDB"]},"up"),
    KGNode("cloud-aws",  "cloud","AWS Mumbai",    {"services":["EC2","RDS","S3"]},"up"),
]

EDGES: List[KGEdge] = [
    # Device connectivity
    KGEdge("fw-edge-01","core-rtr-01","connects_to",1.0,{"link":"10G","protocol":"BGP"}),
    KGEdge("core-rtr-01","pe-mum-01", "connects_to",1.0,{"link":"10G","protocol":"OSPF/MPLS"}),
    KGEdge("core-rtr-01","pe-del-01", "connects_to",1.0,{"link":"10G","protocol":"OSPF/MPLS"}),
    KGEdge("core-rtr-01","dist-sw-w", "connects_to",1.0,{"link":"10G","protocol":"OSPF"}),
    KGEdge("core-rtr-01","dist-sw-c", "connects_to",1.0,{"link":"10G","protocol":"OSPF"}),
    KGEdge("dist-sw-w",  "sw-acc-14", "connects_to",1.0,{"link":"1G","protocol":"STP"}),
    # Protocol runs_on
    KGEdge("proto-bgp",  "pe-mum-01", "runs_on",1.0),
    KGEdge("proto-bgp",  "pe-del-01", "runs_on",1.0),
    KGEdge("proto-bgp",  "core-rtr-01","runs_on",1.0),
    KGEdge("proto-ospf", "core-rtr-01","runs_on",1.0),
    KGEdge("proto-ospf", "dist-sw-w", "runs_on",1.0),
    KGEdge("proto-mpls", "pe-mum-01", "runs_on",1.0),
    KGEdge("proto-mpls", "pe-del-01", "runs_on",1.0),
    # Service depends_on
    KGEdge("svc-internet","fw-edge-01",  "depends_on",1.0),
    KGEdge("svc-internet","proto-bgp",   "depends_on",0.95),
    KGEdge("svc-mum",    "pe-mum-01",   "depends_on",1.0,{"critical":True}),
    KGEdge("svc-mum",    "proto-bgp",   "depends_on",0.9),
    KGEdge("svc-del",    "pe-del-01",   "depends_on",1.0),
    KGEdge("svc-vlan120","sw-acc-14",   "depends_on",1.0,{"critical":True}),
    KGEdge("svc-mpls",   "proto-mpls",  "depends_on",1.0),
    KGEdge("svc-vpn",    "fw-edge-01",  "depends_on",0.9),
    # Cloud connections
    KGEdge("cloud-azure","pe-mum-01",   "connects_via",1.0,{"type":"ExpressRoute"}),
    KGEdge("cloud-aws",  "pe-mum-01",   "connects_via",1.0,{"type":"Direct Connect"}),
    # Site uses
    KGEdge("site-hq",    "dist-sw-w",   "uses",1.0),
    KGEdge("site-hq",    "dist-sw-c",   "uses",1.0),
    KGEdge("site-del",   "pe-del-01",   "uses",1.0),
]


# ══════════════════════════════════════════════════════════
# GRAPH QUERY FUNCTIONS
# ══════════════════════════════════════════════════════════
def get_node(node_id: str) -> Optional[KGNode]:
    return next((n for n in NODES if n.id == node_id or n.label.lower() == node_id.lower()), None)


def get_neighbors(node_id: str, relationship: Optional[str] = None) -> List[KGNode]:
    """Get all nodes connected to a given node."""
    neighbors = []
    for edge in EDGES:
        if edge.source == node_id and (not relationship or edge.relationship == relationship):
            n = get_node(edge.target)
            if n: neighbors.append(n)
        elif edge.target == node_id and (not relationship or edge.relationship == relationship):
            n = get_node(edge.source)
            if n: neighbors.append(n)
    return neighbors


def get_impact_chain(node_id: str, visited: set = None) -> List[dict]:
    """Recursively trace downstream impact from a node (BFS)."""
    if visited is None:
        visited = set()
    if node_id in visited:
        return []
    visited.add(node_id)

    chain = []
    for edge in EDGES:
        if edge.source == node_id and edge.relationship in ("depends_on","connects_to","connects_via","uses"):
            target = get_node(edge.target)
            if target:
                chain.append({
                    "node":         target,
                    "relationship": edge.relationship,
                    "weight":       edge.weight,
                    "metadata":     edge.metadata,
                })
                chain.extend(get_impact_chain(target.id, visited))
    return chain


def get_service_impact(device_id: str) -> List[KGNode]:
    """Find all services affected if a device fails."""
    affected = []
    for node in NODES:
        if node.node_type == "service":
            chain = get_impact_chain(node.id)
            if any(item["node"].id == device_id for item in chain):
                affected.append(node)
    return affected


def search_graph(query: str) -> List[KGNode]:
    """Search graph nodes by label or metadata."""
    ql = query.lower()
    return [n for n in NODES if ql in n.label.lower() or
            any(ql in str(v).lower() for v in n.metadata.values())]


def get_all_nodes_by_type(node_type: str) -> List[KGNode]:
    return [n for n in NODES if n.node_type == node_type]


def get_spof_nodes() -> List[KGNode]:
    return [n for n in NODES if n.metadata.get("spof") is True]


# ══ UI COMPONENTS ════════════════════════════════════

import streamlit as st
from typing import Optional, List


# ══════════════════════════════════════════════════════════
# DESIGN TOKENS
# ══════════════════════════════════════════════════════════
DESIGN_SYSTEM_CSS = """
<style>
/* ── Imports ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Fraunces:wght@600;700;900&display=swap');

/* ── Reset & Base ── */
*{box-sizing:border-box}
html,body,[class*="css"]{font-family:'Inter',sans-serif!important;font-size:14px}
.stApp{background:#0d1117!important}
#MainMenu,footer,header{visibility:hidden}
div.block-container{padding:0!important;max-width:100%!important}
section[data-testid="stSidebar"]{display:none!important}

/* ── Streamlit overrides ── */
div[data-testid="stButton"] button{
  border-radius:8px!important;font-weight:600!important;
  font-family:'Inter',sans-serif!important;transition:all .15s!important;
}
div[data-testid="stTextInput"] input,
div[data-testid="stTextArea"] textarea,
div[data-testid="stSelectbox"] select{border-radius:8px!important}
div[data-testid="stExpander"]{
  border-radius:10px!important;border:1px solid #21262d!important;
  background:#161b22!important;
}
div[data-testid="stExpander"] summary{color:#e6edf3!important}
.stAlert{border-radius:10px!important}
div[data-testid="stMetric"]{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:14px!important}
div[data-testid="stMetric"] label{color:#8b949e!important}
div[data-testid="stMetric"] div{color:#e6edf3!important}

/* ── Colors ── */
:root{
  --bg-base:#0d1117;
  --bg-surface:#161b22;
  --bg-elevated:#1c2128;
  --bg-overlay:#21262d;
  --border-subtle:#21262d;
  --border-default:#30363d;
  --border-muted:#6e7681;
  --text-primary:#e6edf3;
  --text-secondary:#8b949e;
  --text-tertiary:#6e7681;
  --accent-blue:#2f81f7;
  --accent-blue-subtle:#1f6feb22;
  --accent-green:#3fb950;
  --accent-green-subtle:#238636;
  --accent-amber:#d29922;
  --accent-amber-subtle:#9e6a0322;
  --accent-red:#f85149;
  --accent-red-subtle:#da363022;
  --accent-purple:#bc8cff;
  --accent-purple-subtle:#6e40c922;
  --accent-teal:#39d353;
  --glass-bg:rgba(22,27,34,0.85);
  --glass-border:rgba(48,54,61,0.8);
}

/* ── Top Command Bar ── */
.nb-topbar{
  background:linear-gradient(180deg,#161b22 0%,#0d1117 100%);
  border-bottom:1px solid var(--border-default);
  padding:0 20px;height:54px;
  display:flex;align-items:center;gap:14px;
  position:sticky;top:0;z-index:1000;
  box-shadow:0 1px 0 rgba(0,0,0,.5),0 4px 16px rgba(0,0,0,.3);
}
.nb-logo{display:flex;align-items:center;gap:10px;flex-shrink:0}
.nb-logo-mark{
  width:30px;height:30px;border-radius:8px;flex-shrink:0;
  background:linear-gradient(135deg,#1f6feb,#2f81f7);
  display:flex;align-items:center;justify-content:center;
  font-size:16px;box-shadow:0 0 12px rgba(47,129,247,.35);
}
.nb-logo-name{font-family:'Fraunces',serif;font-size:17px;font-weight:900;color:var(--text-primary);letter-spacing:-.3px}
.nb-logo-ver{font-size:9px;color:var(--text-tertiary);letter-spacing:1px;text-transform:uppercase;font-family:'JetBrains Mono',monospace}
.nb-divider-v{width:1px;height:22px;background:var(--border-default);flex-shrink:0}
.nb-search{
  flex:1;max-width:540px;height:34px;
  background:var(--bg-elevated);border:1px solid var(--border-default);
  border-radius:10px;display:flex;align-items:center;gap:8px;padding:0 12px;
  transition:all .2s;
}
.nb-search:focus-within{
  border-color:var(--accent-blue);
  box-shadow:0 0 0 3px var(--accent-blue-subtle);
}
.nb-search input{
  flex:1;background:none;border:none;outline:none;
  color:var(--text-primary);font-size:13px;font-family:'Inter',sans-serif;
}
.nb-search input::placeholder{color:var(--text-tertiary)}
.nb-search-ico{color:var(--text-tertiary);font-size:13px;flex-shrink:0}
.nb-search-hint{font-size:10px;color:var(--text-tertiary);font-family:'JetBrains Mono',monospace;flex-shrink:0;white-space:nowrap}

/* Status chips */
.nb-status-row{display:flex;gap:4px;align-items:center}
.nb-chip{
  font-size:10px;padding:3px 8px;border-radius:12px;
  font-family:'JetBrains Mono',monospace;font-weight:600;
  display:inline-flex;align-items:center;gap:4px;white-space:nowrap;
}
.chip-ok   {background:rgba(63,185,80,.12);color:#3fb950;border:1px solid rgba(63,185,80,.25)}
.chip-warn {background:rgba(210,153,34,.12);color:#d29922;border:1px solid rgba(210,153,34,.25)}
.chip-err  {background:rgba(248,81,73,.12);color:#f85149;border:1px solid rgba(248,81,73,.25)}
.chip-info {background:rgba(47,129,247,.12);color:#2f81f7;border:1px solid rgba(47,129,247,.25)}
.chip-dot  {width:5px;height:5px;border-radius:50%;background:currentColor;animation:blink-dot 2s infinite}
@keyframes blink-dot{0%,100%{opacity:1}50%{opacity:.4}}

/* Persona switcher */
.nb-persona-sw{
  display:flex;background:var(--bg-elevated);border:1px solid var(--border-default);
  border-radius:8px;overflow:hidden;height:28px;flex-shrink:0;
}
.nb-p-btn{
  padding:0 10px;font-size:11px;font-weight:600;color:var(--text-tertiary);
  cursor:pointer;height:100%;display:flex;align-items:center;gap:3px;
  border:none;background:none;transition:all .15s;white-space:nowrap;
  font-family:'Inter',sans-serif;border-right:1px solid var(--border-default);
}
.nb-p-btn:last-child{border-right:none}
.nb-p-btn:hover{color:var(--text-secondary)}
.nb-p-btn.active{background:rgba(47,129,247,.15);color:var(--accent-blue)}
.nb-avatar{
  width:28px;height:28px;border-radius:7px;flex-shrink:0;
  background:linear-gradient(135deg,#1f6feb,#2f81f7);
  display:flex;align-items:center;justify-content:center;
  font-size:11px;font-weight:700;color:#fff;cursor:pointer;
}

/* ── Workspace Navigation ── */
.nb-workspace-nav{
  background:var(--bg-surface);border-bottom:1px solid var(--border-default);
  padding:0 20px;height:44px;display:flex;align-items:center;gap:2px;overflow-x:auto;
}
.nb-workspace-nav::-webkit-scrollbar{height:0}
.nb-ws-tab{
  padding:0 14px;height:100%;display:flex;align-items:center;gap:7px;
  font-size:12px;font-weight:600;color:var(--text-tertiary);cursor:pointer;
  border-bottom:2px solid transparent;transition:all .15s;white-space:nowrap;
  background:none;border-top:none;border-left:none;border-right:none;
  font-family:'Inter',sans-serif;
}
.nb-ws-tab:hover{color:var(--text-secondary);background:var(--bg-elevated)}
.nb-ws-tab.active{color:var(--accent-blue);border-bottom-color:var(--accent-blue)}
.nb-ws-badge{
  font-size:9px;padding:1px 5px;border-radius:8px;font-weight:700;
  background:var(--accent-red-subtle);color:var(--accent-red);
  font-family:'JetBrains Mono',monospace;min-width:16px;text-align:center;
}

/* ── AI Command Bar ── */
.ai-cmd-wrap{
  background:var(--bg-surface);border:1px solid var(--border-default);
  border-radius:12px;padding:14px 16px;margin-bottom:16px;
  transition:all .2s;position:relative;
}
.ai-cmd-wrap:focus-within{
  border-color:var(--accent-blue);
  box-shadow:0 0 0 3px var(--accent-blue-subtle),0 4px 20px rgba(0,0,0,.3);
}
.ai-cmd-pulse{
  width:7px;height:7px;border-radius:50%;background:var(--accent-green);
  animation:pulse-green 2s infinite;display:inline-block;margin-right:6px;
}
@keyframes pulse-green{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.7)}}
.ai-cmd-label{
  font-size:10px;font-weight:700;color:var(--text-tertiary);
  letter-spacing:1px;text-transform:uppercase;font-family:'JetBrains Mono',monospace;
  margin-bottom:8px;display:flex;align-items:center;
}

/* ── Metric Cards ── */
.nb-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px}
.nb-metric{
  background:var(--bg-surface);border:1px solid var(--border-default);
  border-radius:10px;padding:14px 16px;position:relative;overflow:hidden;
  cursor:default;transition:all .2s;
}
.nb-metric:hover{border-color:var(--border-muted);background:var(--bg-elevated)}
.nb-metric::before{content:'';position:absolute;top:0;left:0;right:0;height:2px}
.nb-m-green::before{background:linear-gradient(90deg,var(--accent-green),#238636)}
.nb-m-red::before{background:linear-gradient(90deg,var(--accent-red),#b91c1c)}
.nb-m-amber::before{background:linear-gradient(90deg,var(--accent-amber),#9e6a03)}
.nb-m-blue::before{background:linear-gradient(90deg,var(--accent-blue),#1f6feb)}
.nb-m-purple::before{background:linear-gradient(90deg,var(--accent-purple),#6e40c9)}
.nb-m-lbl{font-size:10px;font-weight:600;color:var(--text-tertiary);letter-spacing:.6px;text-transform:uppercase;font-family:'JetBrains Mono',monospace;margin-bottom:6px}
.nb-m-val{font-family:'Fraunces',serif;font-size:26px;font-weight:700;line-height:1;margin-bottom:4px}
.nb-m-green .nb-m-val{color:var(--accent-green)}.nb-m-red .nb-m-val{color:var(--accent-red)}.nb-m-amber .nb-m-val{color:var(--accent-amber)}.nb-m-blue .nb-m-val{color:var(--accent-blue)}.nb-m-purple .nb-m-val{color:var(--accent-purple)}
.nb-m-meta{font-size:11px;color:var(--text-tertiary)}
.nb-m-icon{position:absolute;right:12px;top:12px;font-size:18px;opacity:.1}

/* ── AI Insight Card ── */
.nb-ai-insight{
  background:linear-gradient(135deg,rgba(31,111,235,.08) 0%,var(--bg-surface) 100%);
  border:1px solid rgba(47,129,247,.2);border-left:3px solid var(--accent-blue);
  border-radius:0 10px 10px 0;padding:12px 14px;margin-bottom:14px;
}
.nb-ai-hdr{
  font-size:9px;font-weight:700;color:var(--accent-blue);
  letter-spacing:1.2px;text-transform:uppercase;font-family:'JetBrains Mono',monospace;
  margin-bottom:5px;display:flex;align-items:center;gap:6px;
}
.nb-ai-body{font-size:13px;color:var(--text-primary);line-height:1.65}
.nb-ai-body strong{color:#79c0ff}
.nb-ai-body code{
  font-family:'JetBrains Mono',monospace;font-size:12px;
  background:rgba(47,129,247,.12);color:#79c0ff;
  padding:1px 5px;border-radius:4px;
}
.nb-conf{display:flex;align-items:center;gap:8px;margin-top:6px}
.nb-conf-track{flex:1;height:3px;background:var(--border-default);border-radius:4px;overflow:hidden}
.nb-conf-fill{height:100%;border-radius:4px}
.conf-high .nb-conf-fill{background:linear-gradient(90deg,var(--accent-green),#238636)}
.conf-med  .nb-conf-fill{background:linear-gradient(90deg,var(--accent-amber),#9e6a03)}
.conf-low  .nb-conf-fill{background:linear-gradient(90deg,var(--accent-red),#b91c1c)}
.nb-conf-pct{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;width:32px}
.conf-high .nb-conf-pct{color:var(--accent-green)}.conf-med .nb-conf-pct{color:var(--accent-amber)}.conf-low .nb-conf-pct{color:var(--accent-red)}

/* ── Cards ── */
.nb-card{
  background:var(--bg-surface);border:1px solid var(--border-default);
  border-radius:10px;overflow:hidden;margin-bottom:12px;
}
.nb-card-hdr{
  padding:12px 16px;border-bottom:1px solid var(--border-subtle);
  display:flex;align-items:center;justify-content:space-between;
  background:var(--bg-surface);
}
.nb-card-title{font-size:13px;font-weight:700;color:var(--text-primary);display:flex;align-items:center;gap:7px}
.nb-card-body{padding:14px 16px}

/* ── Tags ── */
.nb-tag{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600;font-family:'JetBrains Mono',monospace}
.tag-red    {background:var(--accent-red-subtle);color:var(--accent-red);border:1px solid rgba(248,81,73,.2)}
.tag-amber  {background:var(--accent-amber-subtle);color:var(--accent-amber);border:1px solid rgba(210,153,34,.2)}
.tag-green  {background:var(--accent-green-subtle);color:var(--accent-green);border:1px solid rgba(63,185,80,.2)}
.tag-blue   {background:var(--accent-blue-subtle);color:var(--accent-blue);border:1px solid rgba(47,129,247,.2)}
.tag-purple {background:var(--accent-purple-subtle);color:var(--accent-purple);border:1px solid rgba(188,140,255,.2)}
.tag-slate  {background:var(--bg-elevated);color:var(--text-secondary);border:1px solid var(--border-default)}

/* ── Device Cards ── */
.nb-dev-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin-bottom:16px}
.nb-dev{
  background:var(--bg-surface);border:1px solid var(--border-default);
  border-radius:10px;padding:11px;cursor:pointer;transition:all .15s;
  position:relative;overflow:hidden;
}
.nb-dev:hover{border-color:var(--border-muted);background:var(--bg-elevated);transform:translateY(-1px)}
.nb-dev::before{content:'';position:absolute;top:0;left:0;right:0;height:2px}
.dev-up::before   {background:var(--accent-green)}
.dev-warn::before {background:var(--accent-amber);animation:pulse-bar 2s infinite}
.dev-critical::before{background:var(--accent-red);animation:pulse-bar 1s infinite}
@keyframes pulse-bar{0%,100%{opacity:1}50%{opacity:.4}}
.nb-dev-hn{font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:2px}
.nb-dev-role{font-size:11px;color:var(--text-secondary);margin-bottom:2px}
.nb-dev-site{font-size:10px;color:var(--text-tertiary);font-family:'JetBrains Mono',monospace}
.nb-dev-metrics{display:flex;gap:8px;margin-top:8px}
.nb-dev-m{flex:1;text-align:center}
.nb-dev-mv{font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700}
.nb-dev-ml{font-size:9px;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.4px}
.mv-ok{color:var(--accent-green)}.mv-warn{color:var(--accent-amber)}.mv-crit{color:var(--accent-red)}

/* ── Chat Bubbles ── */
.nb-chat-user{
  background:var(--accent-blue);color:#fff;
  border-radius:12px 12px 2px 12px;padding:10px 14px;margin:4px 0;
  display:inline-block;max-width:80%;font-size:13px;line-height:1.6;
  box-shadow:0 2px 8px rgba(47,129,247,.25);
}
.nb-chat-ai{
  background:var(--bg-surface);border:1px solid var(--border-default);
  border-radius:12px 12px 12px 2px;padding:12px 16px;margin:4px 0;
  display:inline-block;max-width:90%;font-size:13px;line-height:1.65;
  color:var(--text-primary);box-shadow:0 2px 8px rgba(0,0,0,.2);
}
.nb-chat-ai code{
  font-family:'JetBrains Mono',monospace;font-size:12px;
  background:var(--bg-elevated);color:#79c0ff;
  padding:1px 5px;border-radius:4px;
}
.nb-chat-ai pre{
  font-family:'JetBrains Mono',monospace;font-size:12px;
  background:#0d1117;color:#3fb950;
  padding:12px;border-radius:8px;border:1px solid var(--border-default);
  margin-top:8px;overflow-x:auto;line-height:1.7;
}
.nb-chat-ai strong{color:#79c0ff}
.nb-meta-row{display:flex;gap:4px;flex-wrap:wrap;margin-top:5px}
.nb-mp{
  font-size:10px;padding:2px 7px;border-radius:8px;
  font-family:'JetBrains Mono',monospace;font-weight:600;display:inline-flex;align-items:center;gap:3px;
}
.mp-rag{background:rgba(57,211,83,.1);color:var(--accent-teal);border:1px solid rgba(57,211,83,.2)}
.mp-nlp{background:rgba(188,140,255,.1);color:var(--accent-purple);border:1px solid rgba(188,140,255,.2)}
.mp-per{background:rgba(63,185,80,.1);color:var(--accent-green);border:1px solid rgba(63,185,80,.2)}
.mp-inc{background:rgba(210,153,34,.1);color:var(--accent-amber);border:1px solid rgba(210,153,34,.2)}

/* ── Timeline ── */
.nb-timeline-item{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--border-subtle);align-items:flex-start}
.nb-timeline-item:last-child{border-bottom:none}
.nb-tl-dot{width:28px;height:28px;border-radius:7px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:13px}
.tl-crit{background:rgba(248,81,73,.12);border:1px solid rgba(248,81,73,.2)}
.tl-warn{background:rgba(210,153,34,.12);border:1px solid rgba(210,153,34,.2)}
.tl-ok  {background:rgba(63,185,80,.12);border:1px solid rgba(63,185,80,.2)}
.tl-ai  {background:rgba(47,129,247,.12);border:1px solid rgba(47,129,247,.2)}
.tl-info{background:rgba(188,140,255,.12);border:1px solid rgba(188,140,255,.2)}
.nb-tl-body{flex:1}
.nb-tl-title{font-size:13px;font-weight:500;color:var(--text-primary);margin-bottom:2px}
.nb-tl-meta{font-size:11px;color:var(--text-tertiary);font-family:'JetBrains Mono',monospace;margin-bottom:3px}
.nb-tl-ai{font-size:11px;color:var(--accent-blue);background:rgba(47,129,247,.08);border-radius:5px;padding:2px 7px;display:inline-block}

/* ── War Room ── */
.nb-warroom{
  background:linear-gradient(135deg,rgba(248,81,73,.05) 0%,var(--bg-surface) 100%);
  border:1px solid rgba(248,81,73,.2);border-radius:12px;overflow:hidden;
  margin-bottom:16px;box-shadow:0 4px 24px rgba(248,81,73,.08);
}
.nb-wr-hdr{
  background:linear-gradient(135deg,#3d0f0a,#5c1a12);
  padding:14px 18px;display:flex;align-items:center;gap:12px;
}
.nb-wr-pulse{
  width:9px;height:9px;border-radius:50%;background:#fca5a5;
  animation:wr-pulse 1s infinite;flex-shrink:0;
}
@keyframes wr-pulse{0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(252,165,165,.4)}50%{opacity:.6;box-shadow:0 0 0 6px transparent}}
.nb-wr-title{font-family:'Fraunces',serif;font-size:14px;font-weight:700;color:#fff;flex:1}

/* ── Autonomous Actions ── */
.nb-auto-action{
  background:var(--bg-surface);border:1px solid var(--border-default);
  border-radius:10px;padding:11px;margin-bottom:8px;
  display:flex;gap:10px;align-items:flex-start;
  transition:border-color .15s;
}
.nb-auto-action:hover{border-color:var(--border-muted)}
.nb-aa-ico{width:30px;height:30px;border-radius:7px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:14px}
.aa-exec{background:rgba(63,185,80,.12);border:1px solid rgba(63,185,80,.2)}
.aa-pend{background:rgba(210,153,34,.12);border:1px solid rgba(210,153,34,.2)}
.aa-fail{background:rgba(248,81,73,.12);border:1px solid rgba(248,81,73,.2)}
.nb-aa-title{font-size:13px;font-weight:500;color:var(--text-primary);margin-bottom:2px}
.nb-aa-meta{font-size:11px;color:var(--text-tertiary);font-family:'JetBrains Mono',monospace;margin-bottom:3px}
.nb-aa-ai{font-size:11px;color:var(--accent-purple);background:rgba(188,140,255,.08);border-radius:5px;padding:2px 7px;display:inline-block}

/* ── Device output terminal ── */
.nb-terminal{
  font-family:'JetBrains Mono',monospace;font-size:11px;
  background:#0d1117;color:#3fb950;padding:10px;border-radius:7px;
  border:1px solid var(--border-default);
  max-height:130px;overflow-y:auto;line-height:1.7;white-space:pre-wrap;
  margin-top:6px;
}
.nb-terminal::-webkit-scrollbar{width:3px}
.nb-terminal::-webkit-scrollbar-thumb{background:var(--border-default)}

/* ── Risk bar ── */
.nb-risk-wrap{display:flex;align-items:center;gap:8px;margin-top:7px}
.nb-risk-track{flex:1;height:5px;background:var(--border-default);border-radius:4px;overflow:hidden}
.nb-risk-fill{height:100%;border-radius:4px}
.risk-low  .nb-risk-fill{background:linear-gradient(90deg,var(--accent-green),#238636)}
.risk-med  .nb-risk-fill{background:linear-gradient(90deg,var(--accent-amber),#9e6a03)}
.risk-high .nb-risk-fill{background:linear-gradient(90deg,var(--accent-red),#b91c1c)}
.nb-risk-score{font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;width:30px;text-align:right}
.risk-low  .nb-risk-score{color:var(--accent-green)}
.risk-med  .nb-risk-score{color:var(--accent-amber)}
.risk-high .nb-risk-score{color:var(--accent-red)}

/* ── Change card ── */
.nb-change-card{
  background:var(--bg-surface);border:1px solid var(--border-default);
  border-radius:10px;padding:14px;margin-bottom:10px;cursor:pointer;
  transition:all .15s;
}
.nb-change-card:hover{border-color:var(--border-muted);background:var(--bg-elevated)}

/* ── Topology wrapper ── */
.nb-topo-wrap{background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:10px;overflow:hidden}
.nb-topo-bar{
  padding:8px 12px;border-bottom:1px solid var(--border-default);
  display:flex;gap:5px;align-items:center;background:var(--bg-surface);flex-wrap:wrap;
}
.nb-layer-btn{
  padding:3px 9px;border-radius:14px;font-size:11px;font-weight:600;
  border:1px solid var(--border-default);background:var(--bg-elevated);
  color:var(--text-secondary);cursor:pointer;transition:all .12s;
  font-family:'Inter',sans-serif;
}
.nb-layer-btn.active{background:rgba(47,129,247,.15);border-color:var(--accent-blue);color:var(--accent-blue)}
.nb-layer-btn:hover:not(.active){border-color:var(--border-muted);color:var(--text-primary)}

/* ── Design Studio ── */
.nb-design-studio{
  background:linear-gradient(135deg,rgba(31,111,235,.06) 0%,rgba(188,140,255,.04) 100%);
  border:1px solid rgba(47,129,247,.15);border-radius:14px;padding:20px;margin-bottom:16px;
}
.nb-ds-title{font-family:'Fraunces',serif;font-size:17px;font-weight:700;color:var(--text-primary);margin-bottom:4px}
.nb-ds-sub{font-size:12px;color:var(--text-secondary);margin-bottom:16px}

/* ── Knowledge Graph ── */
.nb-kg-node{
  background:var(--bg-surface);border:1px solid var(--border-default);
  border-radius:10px;padding:12px;cursor:pointer;transition:all .15s;
}
.nb-kg-node:hover{border-color:var(--accent-blue);background:var(--bg-elevated)}
.nb-kg-node.selected{border-color:var(--accent-blue);background:rgba(47,129,247,.06);box-shadow:0 0 0 2px var(--accent-blue-subtle)}
.nb-kg-type{font-size:9px;font-weight:700;color:var(--text-tertiary);letter-spacing:1px;text-transform:uppercase;font-family:'JetBrains Mono',monospace;margin-bottom:4px}
.nb-kg-name{font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:2px}
.nb-kg-meta{font-size:11px;color:var(--text-tertiary)}

/* ── Autonomous mode ── */
.nb-auto-modes{display:flex;gap:8px;margin-bottom:14px}
.nb-mode-btn{
  flex:1;padding:10px;border-radius:10px;
  border:1px solid var(--border-default);background:var(--bg-elevated);
  cursor:pointer;text-align:center;transition:all .15s;font-family:'Inter',sans-serif;
}
.nb-mode-btn.selected-human{border-color:var(--accent-blue);background:rgba(47,129,247,.08)}
.nb-mode-btn.selected-semi{border-color:var(--accent-amber);background:rgba(210,153,34,.08)}
.nb-mode-btn.selected-full{border-color:var(--accent-purple);background:rgba(188,140,255,.08)}
.nb-mode-title{font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:2px}
.nb-mode-desc{font-size:11px;color:var(--text-tertiary);line-height:1.4}

/* ── Responsive ── */
@media(max-width:1100px){
  .nb-metrics{grid-template-columns:1fr 1fr}
  .nb-dev-grid{grid-template-columns:1fr 1fr 1fr}
}
@media(max-width:768px){
  .nb-metrics{grid-template-columns:1fr}
  .nb-dev-grid{grid-template-columns:1fr 1fr}
}
</style>
"""


def inject_css():
    st.markdown(DESIGN_SYSTEM_CSS, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# COMPONENT FUNCTIONS
# ══════════════════════════════════════════════════════════
def ai_insight_card(label: str, text: str, confidence: Optional[int] = None, sources: Optional[List[str]] = None):
    conf_html = ""
    if confidence is not None:
        cls = "conf-high" if confidence >= 80 else "conf-med" if confidence >= 60 else "conf-low"
        conf_html = f'<div class="nb-conf {cls}"><span class="nb-conf-pct">{confidence}%</span><div class="nb-conf-track"><div class="nb-conf-fill" style="width:{confidence}%"></div></div><span style="font-size:10px;color:var(--text-tertiary)">AI Confidence</span></div>'
    src_html = ""
    if sources:
        src_html = "<div style='margin-top:4px'>" + "".join(
            f'<span style="font-size:10px;padding:1px 6px;border-radius:5px;background:rgba(57,211,83,.1);color:#39d353;font-family:JetBrains Mono,monospace;margin:1px">{s}</span>'
            for s in sources if s) + "</div>"
    st.markdown(f"""<div class="nb-ai-insight">
      <div class="nb-ai-hdr">🧠 {label}</div>
      <div class="nb-ai-body">{text}</div>
      {conf_html}{src_html}
    </div>""", unsafe_allow_html=True)


def metric_grid(metrics: List[dict]):
    """
    metrics: [{"label":"..","value":"..","meta":"..","color":"green|red|amber|blue|purple","icon":""}]
    """
    cols = st.columns(len(metrics))
    for col, m in zip(cols, metrics):
        with col:
            cc = m.get("color","blue")
            st.markdown(f"""<div class="nb-metric nb-m-{cc}">
              <div class="nb-m-icon">{m.get('icon','')}</div>
              <div class="nb-m-lbl">{m['label']}</div>
              <div class="nb-m-val">{m['value']}</div>
              <div class="nb-m-meta">{m['meta']}</div>
            </div>""", unsafe_allow_html=True)


def render_chat_message(role: str, content: str, meta: Optional[dict] = None):
    if role == "user":
        st.markdown(f'<div style="text-align:right;margin:5px 0"><span class="nb-chat-user">{content}</span></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div style="margin:5px 0"><span class="nb-chat-ai">{content}</span></div>', unsafe_allow_html=True)
        if meta:
            pills = ""
            if meta.get("persona_used"): pills += f'<span class="nb-mp mp-per">👤 {meta["persona_used"]}</span>'
            if meta.get("rag_topics"):   pills += "".join(f'<span class="nb-mp mp-rag">📚 {t}</span>' for t in (meta.get("rag_topics") or [])[:2] if t)
            if meta.get("similar_incidents"): pills += f'<span class="nb-mp mp-inc">💡 {str(meta["similar_incidents"][0])[:35]}</span>'
            ents = meta.get("entities") or {}
            if ents.get("protocols"): pills += f'<span class="nb-mp mp-nlp">🧬 {", ".join(ents["protocols"][:3])}</span>'
            if pills:
                st.markdown(f'<div class="nb-meta-row">{pills}</div>', unsafe_allow_html=True)


def section_header(title: str, subtitle: str = ""):
    sub = f'<div style="font-size:12px;color:var(--text-tertiary);margin-top:2px">{subtitle}</div>' if subtitle else ""
    st.markdown(f'<div style="margin-bottom:14px"><div style="font-family:Fraunces,serif;font-size:18px;font-weight:700;color:var(--text-primary)">{title}</div>{sub}</div>', unsafe_allow_html=True)


def risk_bar(score: int):
    cls = "risk-low" if score < 30 else "risk-med" if score < 65 else "risk-high"
    st.markdown(f'<div class="nb-risk-wrap {cls}"><div class="nb-risk-track"><div class="nb-risk-fill" style="width:{score}%"></div></div><span class="nb-risk-score">{score}</span></div>', unsafe_allow_html=True)



# ── Compatibility aliases ─────────────────────────────────
nlp_extract = extract
def rag_search(query, n=4, vendor_filter=None, protocol_filter=None):
    return search(query, n, vendor_filter, protocol_filter)
mdq_run = run_query


# ── Init ──────────────────────────────────────────────────
seed_database()

# ══════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════
_DEFAULTS = {
    "workspace":     "operations",
    "persona":       "noc",
    "chat_msgs":     [],
    "chat_hist":     [],
    "kg_selected":   None,
    "mdq_results":   None,
    "nlp_results":   None,
    "rag_results":   [],
    "design_output": None,
    "auto_mode":     "human",
    "user_role":     "admin",    # Set via login in production
    "user_name":     "engineer",
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════════════════
# INJECT CSS
# ══════════════════════════════════════════════════════════
inject_css()

# ══════════════════════════════════════════════════════════
# STATUS CHECK
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=30)
def get_system_status():
    api_key = get_api_key()
    r_stat = rag_status()
    return {
        "ai":      bool(api_key),
        "ssh":     NETMIKO_OK,
        "rag":     r_stat,
        "db":      True,
    }

# ══════════════════════════════════════════════════════════
# CORE PIPELINE
# ══════════════════════════════════════════════════════════
def pipeline(query: str, persona: str = "noc", history: list = None,
             workspace_ctx: str = "") -> dict:
    """Full 4-engine pipeline: NLP → RAG → Incident Memory → Claude."""
    # 1 — NLP
    nlp_result = nlp_extract(query)
    effective_persona = nlp_result.persona_hint or persona

    # 2 — RAG
    rag_results = rag_search(query, n=3)
    rag_ctx = format_rag_context(rag_results)
    rag_topics = [m.get("topic", m.get("title", "")) for _, m in rag_results]

    # 3 — Incident Memory
    active_incs = get_incidents("active")
    similar = [i for i in active_incs
               if any(p.lower() in f"{i['title']} {i.get('protocols','')}".lower()
                      for p in nlp_result.protocols)][:2]
    inc_ctx = "\n".join(
        f"INCIDENT: {i['title']} | RCA: {i['root_cause']} | Fix: {i['resolution']}"
        for i in similar
    )

    # 4 — Enrich + Call Claude
    enriched = enrich_query(query, nlp_result)
    messages = (history or [])[-6:] + [{"role": "user", "content": enriched}]

    response = call_ai(
        messages,
        persona=effective_persona,
        rag_context=rag_ctx,
        incident_context=inc_ctx,
        workspace_context=workspace_ctx,
        max_tokens=2000,
    )

    write_audit(
        user=st.session_state.user_name,
        action="ai_query",
        resource=f"workspace:{st.session_state.workspace}",
        detail=query[:200],
    )

    return {
        "response":          response,
        "entities":          {"protocols": nlp_result.protocols, "ips": nlp_result.ipv4,
                               "devices": nlp_result.hostnames, "vlans": nlp_result.vlans},
        "persona_used":      effective_persona,
        "rag_topics":        rag_topics,
        "similar_incidents": [i["title"] for i in similar],
    }


def go(prompt: str, target_workspace: str = "troubleshoot", ctx: str = ""):
    """Send a prompt, store response, navigate to workspace."""
    st.session_state.chat_msgs.append({"role": "user", "content": prompt, "meta": None})
    with st.spinner("🧠 Reasoning…"):
        result = pipeline(prompt, st.session_state.persona,
                          st.session_state.chat_hist, ctx)
    st.session_state.chat_msgs.append({"role": "assistant", "content": result["response"], "meta": result})
    st.session_state.chat_hist += [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": result["response"]},
    ]
    st.session_state.workspace = target_workspace
    st.rerun()


# ══════════════════════════════════════════════════════════
# TOPBAR
# ══════════════════════════════════════════════════════════
def render_topbar():
    stat = get_system_status()

    def _chip(lbl, ok, sim=False):
        cls = "chip-ok" if ok else "chip-warn" if sim else "chip-err"
        return f'<span class="nb-chip {cls}"><span class="chip-dot"></span>{lbl}</span>'

    ai_lbl  = "AI ON"  if stat["ai"]  else "AI OFF"
    ssh_lbl = "SSH"    if stat["ssh"] else "SSH⚡sim"
    rag_lbl = stat["rag"]["backend"][:6]

    st.markdown(f"""
    <div class="nb-topbar">
      <div class="nb-logo">
        <div class="nb-logo-mark">🧠</div>
        <div>
          <div class="nb-logo-name">NetBrain AI</div>
          <div class="nb-logo-ver">Autonomous Network OS</div>
        </div>
      </div>
      <div class="nb-divider-v"></div>
      <div class="nb-status-row">
        {_chip(ai_lbl,  stat["ai"])}
        {_chip(ssh_lbl, stat["ssh"], sim=not stat["ssh"])}
        {_chip(rag_lbl, True, sim=stat["rag"]["backend"]=="Keyword")}
        {_chip("DB ✓", True)}
      </div>
      <div style="flex:1"></div>
      <div style="font-size:11px;color:var(--text-tertiary);font-family:JetBrains Mono,monospace">{get_role_label()}</div>
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# WORKSPACE NAV
# ══════════════════════════════════════════════════════════
WORKSPACES = [
    ("operations",  "⚡",  "Operations"),
    ("incident",    "🚨",  "Incidents"),
    ("topology",    "🗺",  "Topology"),
    ("observe",     "📡",  "Observability"),
    ("troubleshoot","🔧",  "Diagnose"),
    ("change",      "📋",  "Changes"),
    ("autonomous",  "🤖",  "Autonomous"),
    ("twin",        "👾",  "Digital Twin"),
    ("security",    "🔒",  "Security"),
    ("compliance",  "🛡",  "Compliance"),
    ("design",      "🏗",  "Design"),
    ("mdq",         "⚡",  "Multi-Device"),
    ("nlp",         "🧬",  "NLP"),
    ("rag",         "📚",  "Knowledge"),
    ("learn",       "📖",  "Learn"),
    ("devices",     "🖧",  "Devices"),
    ("executive",   "📈",  "Executive"),
    ("finops",      "💰",  "FinOps"),
    ("audit",       "🔐",  "Audit"),
]

def render_workspace_nav():
    active_incs = len(get_incidents("active"))
    pending_chg = len([c for c in get_changes() if c["status"] == "pending"])
    pending_auto= len([a for a in get_auto_actions() if a["status"] == "pending_approval"])

    badges = {"incident": active_incs, "change": pending_chg, "autonomous": pending_auto}

    cols = st.columns(len(WORKSPACES))
    for col, (ws_id, icon, label) in zip(cols, WORKSPACES):
        with col:
            badge = badges.get(ws_id, 0)
            btn_label = f"{icon} {label}" + (f" ·{badge}" if badge else "")
            is_active = st.session_state.workspace == ws_id
            if st.button(btn_label, key=f"ws_{ws_id}",
                         use_container_width=True,
                         type="primary" if is_active else "secondary"):
                st.session_state.workspace = ws_id
                st.rerun()


# ══════════════════════════════════════════════════════════
# PERSONA + GLOBAL SEARCH BAR
# ══════════════════════════════════════════════════════════
def render_persona_and_search():
    p_icons = {"fresher":"🌱","ccna":"🎓","noc":"🖥","architect":"🏗","manager":"📊","security":"🔒"}
    personas = list(p_icons.keys())

    st.markdown('<div class="ai-cmd-wrap"><div class="ai-cmd-label"><span class="ai-cmd-pulse"></span>AI Copilot — Natural Language Network Intelligence</div></div>',
                unsafe_allow_html=True)

    col_p, col_q, col_b, col_sel = st.columns([0.18, 0.52, 0.10, 0.20])
    with col_p:
        chosen = st.selectbox("Persona", [f"{p_icons[p]} {p.title()}" for p in personas],
                              index=personas.index(st.session_state.persona),
                              label_visibility="collapsed", key="persona_sel")
        st.session_state.persona = personas[[f"{p_icons[p]} {p.title()}" for p in personas].index(chosen)]
    with col_q:
        query = st.text_input("", placeholder="'Why is BGP flapping?' · 'Design SD-WAN 50 branches' · 'Show OSPF all devices' · 'Simulate CORE-RTR-01 failure'",
                              label_visibility="collapsed", key="global_q")
    with col_b:
        ask = st.button("⚡ Ask AI", use_container_width=True, type="primary", key="global_ask")
    with col_sel:
        sample = st.selectbox("", ["Examples…",
            "Why is BGP flapping on PE-MUM-01?","Show BGP summary all devices",
            "Design enterprise campus 3000 users","What if CORE-RTR-01 fails?",
            "Explain OSPF DR election","Generate Cisco IOS-XR BGP config",
            "Compliance gap analysis","Security posture analysis"],
            label_visibility="collapsed", key="sample_q")

    if ask and query.strip():
        ents = nlp_extract(query)
        target = {"incident_rca":"troubleshoot","design":"design","change_request":"change",
                  "query_devices":"mdq","security_analysis":"troubleshoot",
                  "digital_twin":"autonomous"}.get(ents.intent, "troubleshoot")
        go(query.strip(), target)
    if sample != "Examples…":
        go(sample, "troubleshoot")
        st.session_state["sample_q"] = "Examples…"


# ══════════════════════════════════════════════════════════
# RENDER
# ══════════════════════════════════════════════════════════
render_topbar()
render_workspace_nav()
st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
render_persona_and_search()
st.markdown("<div style='height:8px;background:var(--border-subtle);margin:8px 0'></div>", unsafe_allow_html=True)

ws = st.session_state.workspace

# ══════════════════════════════════════════════════════════
# WORKSPACE: OPERATIONS
# ══════════════════════════════════════════════════════════
if ws == "operations":
    section_header("⚡ Operations Command Center",
                   "Real-time network intelligence · AI-embedded in every workflow")

    ai_insight_card(
        "Operational Intelligence — Live",
        "<strong>2 active incidents</strong> — BGP flap PE-MUM-01 (<strong>87% confidence: ISP withdrawal</strong>) "
        "+ SW-ACC-14 interface down (<strong>94% confidence: physical failure</strong>). "
        "<strong>CORE-RTR-01 CPU 88%</strong> — correlates with BGP SPF recalculation. "
        "<strong>Autonomous action pending:</strong> BGP hold-timer increase awaiting your approval.",
        confidence=87, sources=["BGP","OSPF","Incident Memory"],
    )

    metric_grid([
        {"label":"Devices Online","value":"831","meta":"of 847 · 16 degraded","color":"green","icon":"✅"},
        {"label":"Active Incidents","value":"2","meta":"BGP + Interface","color":"red","icon":"🔴"},
        {"label":"BGP Sessions","value":"248","meta":"247 up · 1 active","color":"blue","icon":"🔄"},
        {"label":"Pending Actions","value":"1","meta":"Awaiting approval","color":"amber","icon":"🤖"},
    ])

    col_devs, col_timeline = st.columns([0.55, 0.45])

    with col_devs:
        st.markdown('<div style="font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:10px">🖧 Live Device Status</div>', unsafe_allow_html=True)
        devices = get_devices()
        dev_cols = st.columns(2)
        for i, d in enumerate(devices):
            status = d.get("status", "up")
            cpu, mem = d.get("cpu", 0), d.get("memory", 0)
            cpu_cls = "mv-crit" if cpu >= 80 else "mv-warn" if cpu >= 60 else "mv-ok"
            mem_cls = "mv-crit" if mem >= 80 else "mv-warn" if mem >= 60 else "mv-ok"
            with dev_cols[i % 2]:
                st.markdown(f"""<div class="nb-dev dev-{status}">
                  <div class="nb-dev-hn">{d['hostname']}</div>
                  <div class="nb-dev-role">{d.get('role','')}</div>
                  <div class="nb-dev-site">📍 {d.get('site','')}</div>
                  <div class="nb-dev-metrics">
                    <div class="nb-dev-m"><div class="nb-dev-mv {cpu_cls}">{f"{cpu}%" if cpu else "—"}</div><div class="nb-dev-ml">CPU</div></div>
                    <div class="nb-dev-m"><div class="nb-dev-mv {mem_cls}">{f"{mem}%" if mem else "—"}</div><div class="nb-dev-ml">MEM</div></div>
                  </div>
                </div>""", unsafe_allow_html=True)
                if st.button(f"🧠", key=f"dev_ai_{d['hostname']}", help=f"AI analyze {d['hostname']}"):
                    go(f"Analyze health of {d['hostname']} ({d['ip']}). Status={status}, CPU={cpu}%, Memory={mem}%. Give assessment, risks, and recommendations.",
                       "troubleshoot", f"Device: {d['hostname']} | Role: {d['role']} | Status: {status}")

    with col_timeline:
        st.markdown('<div style="font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:10px">⏱ Operational Timeline</div>', unsafe_allow_html=True)
        timeline = [
            ("crit","🔴","2m ago","BGP Flapping — PE-MUM-01","AS65002 · 142 prefixes · ISP root cause","AI: ISP BGP withdrawal — 87% confidence"),
            ("crit","🔴","8m ago","Interface Down — SW-ACC-14","VLAN 120 · 47 users","AI: Physical failure. Replace cable/SFP. 94% confidence."),
            ("warn","🟡","14m ago","High CPU — CORE-RTR-01 (88%)","OSPF SPF recalculation","AI: Symptom of BGP flap — will self-resolve"),
            ("ai","🤖","18m ago","BFD Auto-Enabled — PE-MUM-01","Confidence 91% · Executed","BGP detection reduced to 300ms"),
            ("warn","🟡","31m ago","OSPF Neighbor Timeout — Area 0","Segment 10.10.40.0/24","AI: Related to BGP instability cascade"),
            ("ok","✅","2h ago","Change #1 Approved — BGP timer","Risk score 15 · Low","Scheduled for maintenance window"),
        ]
        for sev, ico, ts, title, meta_txt, ai_txt in timeline:
            st.markdown(f"""<div class="nb-timeline-item">
              <div class="nb-tl-dot tl-{sev}">{ico}</div>
              <div class="nb-tl-body">
                <div class="nb-tl-title">{title}</div>
                <div class="nb-tl-meta">{ts} · {meta_txt}</div>
                <div class="nb-tl-ai">🧠 {ai_txt}</div>
              </div>
            </div>""", unsafe_allow_html=True)

    st.markdown("**⚡ Quick Actions:**")
    qc = st.columns(4)
    quick_actions = [
        ("🔧 Diagnose BGP", "BGP flapping on PE-MUM-01 AS65002 — root cause analysis and fix"),
        ("⚡ Query All Devices", "Show BGP summary across all network devices simultaneously", "mdq"),
        ("📊 Compliance Check", "Full compliance gap analysis — top 5 critical findings"),
        ("🏗 Design SD-WAN", "Design SD-WAN for 50 branches, dual ISP, Azure, SASE, app-SLA"),
    ]
    for col, action in zip(qc, quick_actions):
        with col:
            prompt, *rest = action[1:]
            target = rest[0] if rest else "troubleshoot"
            if st.button(action[0], use_container_width=True, key=f"qa_{action[0]}"):
                go(action[1], target)


# ══════════════════════════════════════════════════════════
# WORKSPACE: INCIDENTS
# ══════════════════════════════════════════════════════════
elif ws == "incident":
    section_header("🚨 Incident War Room", "AI-native incident operations · RCA · Blast radius · Autonomous remediation")

    incidents = get_incidents("active")
    resolved  = get_incidents("resolved")

    if not incidents:
        st.success("✅ All clear — no active incidents.")
    else:
        ai_insight_card(
            "AI Correlation",
            f"<strong>{len(incidents)} active incidents correlated.</strong> "
            "Primary root: ISP instability AS65002 → BGP flap → OSPF recalc → high CPU (alerts 1,3,4 are symptoms). "
            "Secondary: Physical failure SW-ACC-14 Gi0/0/3. <strong>Fix root causes, not all symptoms.</strong>",
        )

    for inc in incidents:
        conf = inc.get("ai_confidence", 0)
        conf_cls = "conf-high" if conf >= 80 else "conf-med" if conf >= 60 else "conf-low"
        sev = inc["severity"]

        st.markdown(f"""<div class="nb-warroom">
          <div class="nb-wr-hdr">
            <div class="nb-wr-pulse"></div>
            <div class="nb-wr-title">🚨 {inc['title']}</div>
            <span class="nb-chip {'chip-err' if sev=='critical' else 'chip-warn'}">{sev.upper()} · ACTIVE</span>
          </div>
          <div style="padding:14px 18px">
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px">
              <div>
                <div style="font-size:9px;font-weight:700;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.8px;font-family:JetBrains Mono,monospace;margin-bottom:5px">AI Root Cause</div>
                <div style="font-size:13px;color:var(--text-primary);line-height:1.6">{inc.get('root_cause','Analyzing…')}</div>
                <div class="nb-conf {conf_cls}" style="margin-top:6px"><span class="nb-conf-pct">{conf}%</span><div class="nb-conf-track"><div class="nb-conf-fill" style="width:{conf}%"></div></div><span style="font-size:10px;color:var(--text-tertiary)">AI Confidence</span></div>
              </div>
              <div>
                <div style="font-size:9px;font-weight:700;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.8px;font-family:JetBrains Mono,monospace;margin-bottom:5px">Business Impact</div>
                <div style="font-size:13px;color:var(--text-primary);line-height:1.6">{inc.get('business_impact','Calculating…')}</div>
                <div style="margin-top:5px;font-size:13px;font-weight:700;color:var(--accent-red)">{inc.get('affected_users',0)} users impacted</div>
              </div>
              <div>
                <div style="font-size:9px;font-weight:700;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.8px;font-family:JetBrains Mono,monospace;margin-bottom:5px">Remediation</div>
                <div style="font-size:13px;color:var(--text-primary);line-height:1.6">{inc.get('resolution','Generating…')}</div>
              </div>
            </div>
          </div>
        </div>""", unsafe_allow_html=True)

        ic1, ic2, ic3, ic4 = st.columns(4)
        with ic1:
            if st.button("🧠 Deep AI RCA", key=f"rca_{inc['id']}", use_container_width=True, type="primary"):
                result = analyze_incident(
                    inc["title"], inc["description"],
                    inc.get("protocols",""), inc.get("protocols",""),
                    st.session_state.persona,
                )
                st.session_state.chat_msgs.append({"role":"assistant","content":result["response"],"meta":None})
                st.markdown(result["response"])
        with ic2:
            if st.button("📊 Blast Radius", key=f"blast_{inc['id']}", use_container_width=True):
                go(f"Analyze blast radius for: {inc['title']}. What devices, services, users, applications are impacted? Show full dependency chain.", "incident")
        with ic3:
            if st.button("🔧 Auto-Remediate", key=f"rem_{inc['id']}", use_container_width=True):
                go(f"Generate autonomous remediation plan for: {inc['title']}. Include CLI commands, execution order, validation, rollback procedure.", "incident")
        with ic4:
            if has_permission("resolve_incidents"):
                if st.button("✅ Resolve", key=f"res_{inc['id']}", use_container_width=True):
                    update_record(Incident, inc["id"], status="resolved")
                    write_audit(st.session_state.user_name, "resolve_incident", f"incident:{inc['id']}", inc["title"])
                    st.rerun()
        st.markdown("---")

    if resolved:
        with st.expander(f"📋 Resolved ({len(resolved)}) — Operational Memory"):
            for r in resolved[:5]:
                st.markdown(f"""<div class="nb-timeline-item">
                  <div class="nb-tl-dot tl-ok">✅</div>
                  <div class="nb-tl-body">
                    <div class="nb-tl-title">{r['title']}</div>
                    <div class="nb-tl-meta">RCA: {r.get('root_cause','')} · Fix: {r.get('resolution','')[:80]}</div>
                  </div>
                </div>""", unsafe_allow_html=True)

    with st.expander("➕ Log New Incident"):
        f1, f2 = st.columns(2)
        with f1:
            nt = st.text_input("Title", key="ni_title")
            nd = st.text_input("Devices", placeholder="PE-MUM-01, CORE-RTR-01", key="ni_devs")
            ns = st.selectbox("Severity", ["critical","major","minor"], key="ni_sev")
        with f2:
            ndesc = st.text_area("Description", height=80, key="ni_desc")
            nimpact = st.text_input("Business impact", key="ni_impact")
        if st.button("🚨 Log + AI RCA", type="primary", key="ni_submit"):
            if nt:
                add_incident(nt, ndesc, ns, nd, nimpact, 0, 0)
                go(f"New incident: {nt}. Devices: {nd}. {ndesc}. Perform immediate RCA.", "incident")


# ══════════════════════════════════════════════════════════
# WORKSPACE: TOPOLOGY
# ══════════════════════════════════════════════════════════
elif ws == "topology":
    section_header("🗺 Network Knowledge Graph", "Everything connected · Click for AI analysis · Relationship-driven intelligence")

    ai_insight_card(
        "Topology Intelligence",
        "<strong>Dependency analysis:</strong> PE-MUM-01 is on the critical path for Mumbai SaaS access (340 users). "
        "SW-ACC-14 failure isolates Floor 2 from DIST-SW-C. "
        "<strong>SPOF detected:</strong> FW-EDGE-01 has no redundant path — single point of failure for all internet egress.",
        confidence=91, sources=["Topology","BGP","OSPF"],
    )

    st.markdown("""<div class="nb-topo-wrap">
      <div class="nb-topo-bar">
        <button class="nb-layer-btn active">🌐 All</button>
        <button class="nb-layer-btn">🔄 L3 Routing</button>
        <button class="nb-layer-btn">🔀 L2 Switching</button>
        <button class="nb-layer-btn">🔒 Security</button>
        <button class="nb-layer-btn">☁ Cloud</button>
        <button class="nb-layer-btn">📡 SD-WAN</button>
        <span style="margin-left:auto;font-size:10px;color:var(--text-tertiary);font-family:JetBrains Mono,monospace">← Click nodes → select for AI analysis</span>
      </div>
      <div style="padding:16px;background:var(--bg-elevated);min-height:460px">
      <svg viewBox="0 0 760 440" width="100%" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <filter id="glow-b"><feGaussianBlur stdDeviation="3" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          <filter id="glow-r"><feGaussianBlur stdDeviation="2" result="blur"/><feColorMatrix in="blur" type="matrix" values="1 0 0 0 0.97 0 0 0 0 0.32 0 0 0 0 0.29 0 0 0 0.8 0"/><feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>
        </defs>
        <!-- ISP Cloud -->
        <ellipse cx="380" cy="30" rx="80" ry="22" fill="rgba(188,140,255,.06)" stroke="rgba(188,140,255,.4)" stroke-width="1.5" stroke-dasharray="6 3"/>
        <text x="380" y="34" text-anchor="middle" fill="#bc8cff" font-size="11" font-family="JetBrains Mono">INTERNET / ISP</text>
        <!-- FW - SPOF warning -->
        <line x1="380" y1="52" x2="380" y2="88" stroke="rgba(188,140,255,.4)" stroke-width="1.5"/>
        <rect x="338" y="88" width="84" height="30" rx="7" fill="rgba(31,27,34,.9)" stroke="rgba(210,153,34,.6)" stroke-width="1.5"/>
        <text x="380" y="104" text-anchor="middle" fill="#d29922" font-size="10" font-family="JetBrains Mono" font-weight="600">FW-EDGE-01</text>
        <circle cx="416" cy="93" r="5" fill="#d29922" opacity=".9"/>
        <text x="424" y="97" fill="#d29922" font-size="8" font-family="JetBrains Mono">⚠ SPOF</text>
        <!-- Core router links -->
        <line x1="380" y1="118" x2="180" y2="172" stroke="rgba(48,54,61,.8)" stroke-width="2"/>
        <line x1="380" y1="118" x2="380" y2="172" stroke="rgba(48,54,61,.8)" stroke-width="2.5"/>
        <line x1="380" y1="118" x2="580" y2="172" stroke="rgba(48,54,61,.8)" stroke-width="2"/>
        <!-- CORE-RTR-01 — WARNING -->
        <circle cx="180" cy="192" r="28" fill="rgba(210,153,34,.1)" stroke="rgba(210,153,34,.7)" stroke-width="2.5"/>
        <text x="180" y="188" text-anchor="middle" fill="#d29922" font-size="10" font-family="JetBrains Mono" font-weight="600">CORE-RTR</text>
        <text x="180" y="200" text-anchor="middle" fill="#d29922" font-size="8" font-family="JetBrains Mono">01</text>
        <text x="180" y="212" text-anchor="middle" fill="#d29922" font-size="8" font-family="JetBrains Mono">CPU 88% ⚠</text>
        <!-- PE-MUM-01 — CRITICAL -->
        <circle cx="380" cy="192" r="30" fill="rgba(248,81,73,.1)" stroke="rgba(248,81,73,.8)" stroke-width="2.5" filter="url(#glow-r)"/>
        <text x="380" y="186" text-anchor="middle" fill="#f85149" font-size="10" font-family="JetBrains Mono" font-weight="600">PE-MUM-01</text>
        <text x="380" y="198" text-anchor="middle" fill="#f85149" font-size="8" font-family="JetBrains Mono">BGP FLAP 🔴</text>
        <text x="380" y="210" text-anchor="middle" fill="#f85149" font-size="8" font-family="JetBrains Mono">10.0.1.1</text>
        <!-- PE-DEL-01 — OK -->
        <circle cx="580" cy="192" r="26" fill="rgba(47,129,247,.08)" stroke="rgba(47,129,247,.5)" stroke-width="1.5"/>
        <text x="580" y="188" text-anchor="middle" fill="#2f81f7" font-size="10" font-family="JetBrains Mono" font-weight="600">PE-DEL-01</text>
        <text x="580" y="200" text-anchor="middle" fill="#2f81f7" font-size="8" font-family="JetBrains Mono">✓ stable</text>
        <!-- Distribution links -->
        <line x1="180" y1="220" x2="120" y2="270" stroke="rgba(48,54,61,.7)" stroke-width="1.5"/>
        <line x1="180" y1="220" x2="240" y2="270" stroke="rgba(48,54,61,.7)" stroke-width="1.5"/>
        <line x1="380" y1="222" x2="380" y2="270" stroke="rgba(210,153,34,.5)" stroke-width="2" stroke-dasharray="5 4"/>
        <line x1="580" y1="218" x2="500" y2="270" stroke="rgba(48,54,61,.7)" stroke-width="1.5"/>
        <line x1="580" y1="218" x2="660" y2="270" stroke="rgba(48,54,61,.7)" stroke-width="1.5"/>
        <!-- Dist switches -->
        <rect x="88"  y="270" width="64" height="24" rx="6" fill="rgba(31,111,235,.08)" stroke="rgba(47,129,247,.4)" stroke-width="1.5"/>
        <text x="120" y="285" text-anchor="middle" fill="#2f81f7" font-size="9" font-family="JetBrains Mono" font-weight="600">DIST-SW-W</text>
        <rect x="208" y="270" width="64" height="24" rx="6" fill="rgba(31,111,235,.08)" stroke="rgba(47,129,247,.4)" stroke-width="1.5"/>
        <text x="240" y="285" text-anchor="middle" fill="#2f81f7" font-size="9" font-family="JetBrains Mono" font-weight="600">DIST-SW-E</text>
        <rect x="348" y="270" width="64" height="24" rx="6" fill="rgba(210,153,34,.08)" stroke="rgba(210,153,34,.5)" stroke-width="1.5"/>
        <text x="380" y="279" text-anchor="middle" fill="#d29922" font-size="9" font-family="JetBrains Mono" font-weight="600">DIST-SW-C</text>
        <text x="380" y="290" text-anchor="middle" fill="#d29922" font-size="8" font-family="JetBrains Mono">⚠ warn</text>
        <rect x="468" y="270" width="64" height="24" rx="6" fill="rgba(31,111,235,.08)" stroke="rgba(47,129,247,.4)" stroke-width="1.5"/>
        <text x="500" y="285" text-anchor="middle" fill="#2f81f7" font-size="9" font-family="JetBrains Mono" font-weight="600">DIST-SW-N</text>
        <rect x="628" y="270" width="64" height="24" rx="6" fill="rgba(31,111,235,.08)" stroke="rgba(47,129,247,.4)" stroke-width="1.5"/>
        <text x="660" y="285" text-anchor="middle" fill="#2f81f7" font-size="9" font-family="JetBrains Mono" font-weight="600">DIST-SW-S</text>
        <!-- Access layer links -->
        <line x1="120" y1="294" x2="80"  y2="348" stroke="rgba(33,38,45,.9)" stroke-width="1"/>
        <line x1="120" y1="294" x2="160" y2="348" stroke="rgba(33,38,45,.9)" stroke-width="1"/>
        <line x1="240" y1="294" x2="200" y2="348" stroke="rgba(33,38,45,.9)" stroke-width="1"/>
        <line x1="240" y1="294" x2="280" y2="348" stroke="rgba(33,38,45,.9)" stroke-width="1"/>
        <line x1="380" y1="294" x2="380" y2="348" stroke="rgba(248,81,73,.4)" stroke-width="1.5" stroke-dasharray="4 3"/>
        <line x1="500" y1="294" x2="480" y2="348" stroke="rgba(33,38,45,.9)" stroke-width="1"/>
        <line x1="660" y1="294" x2="640" y2="348" stroke="rgba(33,38,45,.9)" stroke-width="1"/>
        <line x1="660" y1="294" x2="700" y2="348" stroke="rgba(33,38,45,.9)" stroke-width="1"/>
        <!-- Access switches -->
        <rect x="60"  y="348" width="40" height="17" rx="4" fill="rgba(63,185,80,.08)"  stroke="rgba(63,185,80,.4)"  stroke-width="1"/>
        <text x="80"  y="360" text-anchor="middle" fill="#3fb950" font-size="8" font-family="JetBrains Mono">ACC-1</text>
        <rect x="140" y="348" width="40" height="17" rx="4" fill="rgba(63,185,80,.08)"  stroke="rgba(63,185,80,.4)"  stroke-width="1"/>
        <text x="160" y="360" text-anchor="middle" fill="#3fb950" font-size="8" font-family="JetBrains Mono">ACC-2</text>
        <rect x="180" y="348" width="40" height="17" rx="4" fill="rgba(248,81,73,.12)" stroke="rgba(248,81,73,.6)"  stroke-width="1.5"/>
        <text x="200" y="357" text-anchor="middle" fill="#f85149" font-size="8" font-family="JetBrains Mono">ACC-14</text>
        <text x="200" y="367" text-anchor="middle" fill="#f85149" font-size="7" font-family="JetBrains Mono">↓DOWN</text>
        <rect x="260" y="348" width="40" height="17" rx="4" fill="rgba(63,185,80,.08)"  stroke="rgba(63,185,80,.4)"  stroke-width="1"/>
        <text x="280" y="360" text-anchor="middle" fill="#3fb950" font-size="8" font-family="JetBrains Mono">ACC-3</text>
        <rect x="460" y="348" width="40" height="17" rx="4" fill="rgba(63,185,80,.08)"  stroke="rgba(63,185,80,.4)"  stroke-width="1"/>
        <text x="480" y="360" text-anchor="middle" fill="#3fb950" font-size="8" font-family="JetBrains Mono">ACC-5</text>
        <rect x="620" y="348" width="40" height="17" rx="4" fill="rgba(63,185,80,.08)"  stroke="rgba(63,185,80,.4)"  stroke-width="1"/>
        <text x="640" y="360" text-anchor="middle" fill="#3fb950" font-size="8" font-family="JetBrains Mono">ACC-6</text>
        <rect x="680" y="348" width="40" height="17" rx="4" fill="rgba(63,185,80,.08)"  stroke="rgba(63,185,80,.4)"  stroke-width="1"/>
        <text x="700" y="360" text-anchor="middle" fill="#3fb950" font-size="8" font-family="JetBrains Mono">ACC-7</text>
        <!-- Legend -->
        <rect x="12" y="8" width="140" height="75" rx="6" fill="rgba(22,27,34,.95)" stroke="rgba(48,54,61,.8)" stroke-width="1"/>
        <circle cx="24" cy="22" r="5" fill="rgba(248,81,73,.2)" stroke="#f85149" stroke-width="1.5"/>
        <text x="34" y="26" fill="#8b949e" font-size="9" font-family="JetBrains Mono">Critical/Down</text>
        <circle cx="24" cy="38" r="5" fill="rgba(210,153,34,.2)" stroke="#d29922" stroke-width="1.5"/>
        <text x="34" y="42" fill="#8b949e" font-size="9" font-family="JetBrains Mono">Warning</text>
        <circle cx="24" cy="54" r="5" fill="rgba(47,129,247,.2)" stroke="#2f81f7" stroke-width="1.5"/>
        <text x="34" y="58" fill="#8b949e" font-size="9" font-family="JetBrains Mono">Healthy</text>
        <circle cx="24" cy="70" r="5" fill="rgba(210,153,34,.5)" stroke="#d29922" stroke-width="1"/>
        <text x="34" y="74" fill="#8b949e" font-size="9" font-family="JetBrains Mono">SPOF detected</text>
      </svg>
      </div>
    </div>""", unsafe_allow_html=True)

    tq = st.text_input("Ask about topology", placeholder="'Which devices are single points of failure?' · 'Path from Mumbai branch to Azure' · 'OSPF area 0 devices'", key="topo_q")
    if st.button("🧠 Analyze", type="primary", key="topo_ask") and tq:
        go(tq, "topology", "Topology workspace — user analyzing network graph")


# ══════════════════════════════════════════════════════════
# WORKSPACE: TROUBLESHOOT
# ══════════════════════════════════════════════════════════
elif ws == "troubleshoot":
    section_header("🔧 AI Diagnosis Engine", "NLP → RAG → Incident Memory → Claude · 4-engine pipeline")

    ai_insight_card(
        "Diagnosis Pipeline — Active",
        "<strong>NLP</strong> extracts entities → <strong>RAG</strong> retrieves runbooks → "
        "<strong>Incident Memory</strong> surfaces past RCAs → <strong>Claude</strong> reasons across all context. "
        "Every response shows evidence, confidence %, and rollback options.",
    )

    col_form, col_chat = st.columns([0.48, 0.52])
    with col_form:
        prob = st.text_area("Describe the problem in plain English",
                            placeholder="'BGP session keeps flapping to ISP since 2 hours ago. CPU spiked to 88%. OSPF also went down briefly. No config changes made.'",
                            height=110, key="ts_prob")
        v, sev = st.columns(2)
        vendor = v.selectbox("Vendor", ["Any","Cisco IOS/IOS-XR","Juniper JunOS","Arista EOS","Palo Alto","Fortinet"], key="ts_vendor")
        severity = sev.selectbox("Severity", ["Unknown","🔴 P1 — Production","🟡 P2 — Degraded","🟢 P3 — Minor"], key="ts_sev")
        affected = st.text_input("Affected devices (optional)", placeholder="PE-MUM-01, CORE-RTR-01", key="ts_devs")
        if st.button("🧠 Run 4-Engine Diagnosis", type="primary", use_container_width=True, key="ts_go") and prob:
            go(f"Diagnose: {prob}\nVendor:{vendor} | Severity:{severity} | Devices:{affected}\n\nProvide: 1)Root cause+evidence 2)AI confidence% 3)Business impact 4)Step-by-step CLI fix 5)Rollback plan 6)Prevention",
               "troubleshoot", f"Vendor:{vendor} Severity:{severity}")

        st.markdown("**One-click common issues:**")
        issues = [
            ("BGP stuck Active","BGP neighbor stuck in Active state Cisco IOS-XR — troubleshoot systematically"),
            ("OSPF EXSTART","OSPF adjacency stuck in EXSTART — MTU mismatch diagnosis and fix"),
            ("VLAN trunk issue","VLAN traffic not passing on trunk — STP or allowed VLAN diagnosis"),
            ("SD-WAN failover","SD-WAN not failing over to backup ISP — Cisco Viptela"),
            ("MPLS packet loss","High packet loss on MPLS backbone — LSP ping trace diagnosis"),
            ("IPSec flapping","IPSec VPN tunnel flapping DPD timeout — stabilize"),
            ("STP loop","Spanning tree loop causing broadcast storm — find and stop"),
            ("BGP route missing","BGP route in table but not advertised to peer — route-map issue"),
        ]
        ic = st.columns(2)
        for i, (lbl, prompt) in enumerate(issues):
            with ic[i % 2]:
                if st.button(lbl, key=f"issue_{lbl}", use_container_width=True):
                    go(prompt, "troubleshoot")

    with col_chat:
        st.markdown("**AI Diagnosis:**")
        if not st.session_state.chat_msgs:
            st.info("💡 Describe a problem → AI runs NLP + RAG + Incident Memory + Claude reasoning. Every answer shows evidence and confidence.")
        for msg in st.session_state.chat_msgs[-8:]:
            render_chat_message(msg["role"], msg["content"], msg.get("meta"))
        if st.session_state.chat_msgs:
            fu = st.text_input("Follow-up", placeholder="'What if that doesn't work?' · 'Show me the rollback CLI'", key="ts_fu")
            c1, c2 = st.columns([0.7, 0.3])
            with c1:
                if st.button("Ask follow-up", key="ts_fu_btn") and fu: go(fu, "troubleshoot")
            with c2:
                if st.button("🗑 Clear", key="ts_clr"):
                    st.session_state.chat_msgs = []; st.session_state.chat_hist = []; st.rerun()


# ══════════════════════════════════════════════════════════
# WORKSPACE: CHANGE SAFETY
# ══════════════════════════════════════════════════════════
elif ws == "change":
    section_header("📋 Change Safety Engine", "AI risk scoring · Digital twin pre-validation · Blast radius · Rollback planning")

    ai_insight_card(
        "Change Safety Intelligence",
        "<strong>3 changes in queue.</strong> IOS-XR firmware upgrade on CORE-RTR-01: <strong>score 72/100 — HIGH RISK</strong>. "
        "Digital twin test mandatory before production. "
        "<strong>BGP timer change: 15/100 — LOW RISK</strong>. Safe to proceed during business hours with monitoring.",
        confidence=88,
    )

    changes = get_changes()
    for chg in changes:
        score = chg.get("ai_risk_score", 0)
        risk_cls = "risk-low" if score < 30 else "risk-med" if score < 65 else "risk-high"
        sev_ico = "🟢" if score < 30 else "🟡" if score < 65 else "🔴"
        tag_cls = {"approved":"tag-green","pending":"tag-amber","rejected":"tag-red"}.get(chg["status"],"tag-slate")

        with st.expander(f"{sev_ico} {chg['title']} — Risk {score}/100", expanded=chg["severity"] if "severity" in chg else score >= 65):
            cc1, cc2 = st.columns([0.65, 0.35])
            with cc1:
                st.markdown(f"**Device:** `{chg['device']}` | **Type:** `{chg['change_type']}` | **By:** {chg.get('created_by','')}")
                st.markdown(chg["description"])
                risk_bar(score)
                st.markdown(f"**AI Recommendation:** {chg.get('ai_recommendation','')}")
                if chg.get("rollback_plan"):
                    st.markdown(f"**Rollback:** {chg['rollback_plan']}")
            with cc2:
                st.markdown(f'<span class="nb-tag {tag_cls}">{chg["status"].upper()}</span>', unsafe_allow_html=True)
                if st.button("🧠 AI Risk Analysis", key=f"chg_ai_{chg['id']}", use_container_width=True):
                    result = score_change_risk(chg["title"], chg["description"], chg["device"], chg["change_type"])
                    st.markdown(result["response"])
                if st.button("👾 Digital Twin Test", key=f"chg_twin_{chg['id']}", use_container_width=True):
                    go(f"Simulate in digital twin: {chg['title']} on {chg['device']}. Show topology impact, traffic impact, predicted downtime, rollback triggers.", "autonomous")
                if chg["status"] == "pending" and has_permission("approve_changes"):
                    a1, a2 = st.columns(2)
                    with a1:
                        if st.button("✅ Approve", key=f"chg_app_{chg['id']}", use_container_width=True):
                            update_record(Change, chg["id"], status="approved")
                            write_audit(st.session_state.user_name, "approve_change", f"change:{chg['id']}", chg["title"])
                            st.rerun()
                    with a2:
                        if st.button("❌ Reject", key=f"chg_rej_{chg['id']}", use_container_width=True):
                            update_record(Change, chg["id"], status="rejected")
                            write_audit(st.session_state.user_name, "reject_change", f"change:{chg['id']}", chg["title"])
                            st.rerun()


# ══════════════════════════════════════════════════════════
# WORKSPACE: AUTONOMOUS OPERATIONS
# ══════════════════════════════════════════════════════════
elif ws == "autonomous":
    section_header("🤖 Autonomous Operations Center", "AI detection → recommendation → approval → execution → verification → learning")

    mode_cols = st.columns(3)
    modes = [
        ("human","👨‍💼 Human Approval","ALL AI actions require manual approval before execution."),
        ("semi", "🤝 Semi-Autonomous", "Low-risk (<30 score) auto-execute. High-risk needs approval."),
        ("full", "⚡ Fully Autonomous","AI executes all validated actions. Human notified only."),
    ]
    for col, (m_id, m_lbl, m_desc) in zip(mode_cols, modes):
        with col:
            selected = st.session_state.auto_mode == m_id
            sel_cls = f"selected-{m_id}" if selected else ""
            st.markdown(f"""<div class="nb-mode-btn {sel_cls}">
              <div class="nb-mode-title">{m_lbl}</div>
              <div class="nb-mode-desc">{m_desc}</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"Set {m_lbl.split()[1]}", key=f"mode_{m_id}", use_container_width=True,
                         type="primary" if selected else "secondary"):
                st.session_state.auto_mode = m_id
                st.rerun()

    st.markdown("---")
    ai_insight_card(
        "Autonomous Intelligence",
        f"Mode: <strong>{'Human Approval' if st.session_state.auto_mode=='human' else 'Semi-Autonomous' if st.session_state.auto_mode=='semi' else 'Fully Autonomous'}</strong>. "
        "<strong>3 actions logged</strong> — 2 executed, 1 pending approval. "
        "Auto-remediation success rate: <strong>94%</strong> this week. Time saved: <strong>4.2 hours</strong>.",
        confidence=94,
    )

    metric_grid([
        {"label":"Actions This Week","value":"47","meta":"94% success","color":"green","icon":"✅"},
        {"label":"Auto-Healed","value":"12","meta":"Issues resolved","color":"blue","icon":"🤖"},
        {"label":"Pending Approval","value":"1","meta":"BGP timer change","color":"amber","icon":"⏳"},
        {"label":"Time Saved","value":"4.2h","meta":"This week","color":"green","icon":"⚡"},
    ])

    auto_actions = get_auto_actions()
    for a in auto_actions:
        status = a.get("status", "")
        cls = "aa-exec" if status == "executed" else "aa-pend" if "pending" in status else "aa-fail"
        ico = "✅" if status == "executed" else "⏳" if "pending" in status else "❌"
        conf = a.get("ai_confidence", 0)
        conf_cls = "conf-high" if conf >= 80 else "conf-med" if conf >= 60 else "conf-low"

        st.markdown(f"""<div class="nb-auto-action">
          <div class="nb-aa-ico {cls}">{ico}</div>
          <div style="flex:1">
            <div class="nb-aa-title">{a['action']}</div>
            <div class="nb-aa-meta">Device: {a.get('device','')} · Trigger: {a.get('trigger','')}</div>
            <div class="nb-aa-ai">{a.get('result','')}</div>
            <div class="nb-conf {conf_cls}" style="margin-top:5px">
              <span class="nb-conf-pct">{conf}%</span>
              <div class="nb-conf-track"><div class="nb-conf-fill" style="width:{conf}%"></div></div>
              <span style="font-size:10px;color:var(--text-tertiary)">AI Confidence</span>
            </div>
          </div>
        </div>""", unsafe_allow_html=True)
        if "pending" in status and has_permission("run_automation"):
            pa1, pa2 = st.columns(2)
            with pa1:
                if st.button("✅ Approve", key=f"auto_app_{a['id']}", use_container_width=True, type="primary"):
                    update_record(AutonomousAction, a["id"], status="executed")
                    write_audit(st.session_state.user_name, "approve_auto_action", f"action:{a['id']}", a["action"])
                    st.rerun()
            with pa2:
                if st.button("❌ Reject", key=f"auto_rej_{a['id']}", use_container_width=True):
                    update_record(AutonomousAction, a["id"], status="rejected")
                    st.rerun()

    st.markdown("---")
    auto_q = st.text_input("Ask Autonomous AI", placeholder="'Generate self-healing policy for BGP flaps' · 'What actions were taken today?' · 'Simulate autonomous remediation for incident #1'", key="auto_q")
    if st.button("🤖 Ask", type="primary", key="auto_ask") and auto_q:
        go(auto_q, "autonomous", "Autonomous operations workspace")


# ══════════════════════════════════════════════════════════
# WORKSPACE: MULTI-DEVICE QUERY
# ══════════════════════════════════════════════════════════
elif ws == "mdq":
    section_header("⚡ Multi-Device Query Engine", "System B — Parallel SSH · ThreadPoolExecutor · Retry logic · AI synthesis")

    ai_insight_card(
        "Netmiko SSH Engine — System B",
        "Type plain English: <strong>'Show OSPF neighbors on all routers'</strong> · <strong>'BGP Active state anywhere?'</strong> — "
        "I SSH all devices in parallel (up to 20 concurrent) and synthesise one unified answer.",
    )

    qr = st.columns(6)
    quick_mdq = [("BGP summary","Show BGP summary all routers"),("OSPF neighbors","Show OSPF neighbor status all devices"),("CPU usage","Show CPU usage all devices"),("Interface status","Show interface status"),("VLAN status","Show VLAN brief all switches"),("Routing table","Show routing table summary all devices")]
    for col, (lbl, q) in zip(qr, quick_mdq):
        with col:
            if st.button(lbl, key=f"mdq_q_{lbl}", use_container_width=True):
                st.session_state["_mdqf"] = q

    mdq_inp = st.text_input("Natural language query", value=st.session_state.pop("_mdqf",""),
                             placeholder='"Which routers have BGP in Active state?" · "Show OSPF neighbors across all devices"', key="mdq_inp")

    if st.button("⚡ Query All Devices", type="primary", key="mdq_run") and mdq_inp.strip():
        devices = get_devices()
        with st.spinner(f"⚡ Querying {len(devices)} devices in parallel…"):
            results = mdq_run(mdq_inp.strip(), devices)
        synth_prompt = build_synthesis_prompt(mdq_inp.strip(), results)
        synthesis = call_ai([{"role":"user","content":synth_prompt}], st.session_state.persona)
        st.session_state.mdq_results = {"results": results, "synthesis": synthesis, "query": mdq_inp.strip()}

    if st.session_state.mdq_results:
        r = st.session_state.mdq_results
        ok = sum(1 for d in r["results"] if d.status == "ok")
        st.success(f"✓ {len(r['results'])} devices queried · {ok} successful · Simulated: {len(r['results'])-ok}")
        dev_cols = st.columns(min(len(r["results"]), 3))
        for i, d in enumerate(r["results"]):
            cls = "nb-dev dev-up" if d.status=="ok" else "nb-dev dev-critical"
            with dev_cols[i % 3]:
                st.markdown(f"""<div class="{cls}">
                  <div class="nb-dev-hn">{d.hostname} ({d.ip})</div>
                  <div class="nb-dev-role">{d.vendor} · {d.role} · {d.site}</div>
                  <div style="font-size:10px;color:var(--text-tertiary);font-family:JetBrains Mono,monospace">CMD: {d.command}</div>
                  <div class="nb-terminal">{d.output[:280]}</div>
                </div>""", unsafe_allow_html=True)
        st.markdown("---")
        st.markdown("**🧠 AI Synthesis — All Devices**")
        st.markdown(r["synthesis"])


# ══════════════════════════════════════════════════════════
# WORKSPACE: NLP ENGINE
# ══════════════════════════════════════════════════════════
elif ws == "nlp":
    section_header("🧬 NLP Entity Extractor", "System C — 14 intent classes · Entity extraction · Urgency detection · Auto persona")

    samples = {"BGP log": "BGP neighbor 10.0.1.1 AS65002 stuck Active on GigabitEthernet0/0/0 at PE-MUM-01 OSPF area 0 VLAN 100",
               "OSPF": "OSPF adjacency lost CORE-RTR-01 DIST-SW-W 192.168.1.0/30 area 0 Cisco IOS-XR",
               "Design": "Design VXLAN EVPN leaf-spine Arista EOS BGP EVPN RoCE GPU cluster AI fabric",
               "Security": "Lateral movement detected 10.2.14.0/24 Zero Trust micro-segmentation Palo Alto"}
    sc = st.columns(4)
    for col, (n, t) in zip(sc, samples.items()):
        with col:
            if st.button(n, key=f"nlp_s_{n}", use_container_width=True):
                st.session_state["_nlpf"] = t

    nlp_txt = st.text_area("Paste networking text", value=st.session_state.pop("_nlpf",""),
                            placeholder="Any networking query, log, config, alert…", height=90, key="nlp_inp")
    if st.button("🧬 Extract Entities", type="primary", key="nlp_run") and nlp_txt:
        st.session_state.nlp_results = nlp_extract(nlp_txt)

    if st.session_state.nlp_results:
        e = st.session_state.nlp_results
        m1, m2, m3 = st.columns(3)
        m1.metric("Intent", e.intent.replace("_"," ").title())
        m2.metric("Urgency", e.urgency.upper())
        m3.metric("Persona Hint", e.persona_hint or "Auto")
        st.divider()
        cats = [("IPs","ipv4"),("Protocols","protocols"),("Interfaces","interfaces"),("VLANs","vlans"),
                ("ASNs","asns"),("Vendors","vendors"),("Devices","hostnames"),("VRFs","vrfs"),
                ("Tickets","tickets"),("OSPF Areas","ospf_areas"),("IPv6","ipv6"),("Ports","ports")]
        cols = st.columns(4)
        for i, (lbl, key) in enumerate(cats):
            items = getattr(e, key, [])
            with cols[i % 4]:
                st.markdown(f"**{lbl}**")
                if items:
                    st.markdown(" ".join(f'<span style="font-size:11px;padding:2px 7px;border-radius:8px;border:1px solid var(--border-default);color:var(--text-secondary);font-family:JetBrains Mono,monospace;display:inline-block;margin:2px">{x}</span>' for x in items[:8]), unsafe_allow_html=True)
                else:
                    st.caption("none detected")


# ══════════════════════════════════════════════════════════
# WORKSPACE: RAG KNOWLEDGE
# ══════════════════════════════════════════════════════════
elif ws == "rag":
    r_stat = rag_status()
    section_header("📚 RAG Knowledge Base", f"System D — {r_stat['backend']} · {r_stat['doc_count']} indexed · Hybrid semantic search")

    tab1, tab2 = st.tabs(["🔍 Search", "➕ Ingest Document"])
    with tab1:
        rq = st.text_input("Search knowledge base", placeholder="BGP troubleshooting · OSPF states · SD-WAN design · MPLS L3VPN · Zero Trust…", key="rag_q")
        if st.button("📚 Search", type="primary", key="rag_srch") and rq:
            with st.spinner("Searching…"):
                results = rag_search(rq, 5)
            st.session_state.rag_results = results
        if st.session_state.rag_results:
            st.markdown(f"**{len(st.session_state.rag_results)} relevant chunks:**")
            for content, meta in st.session_state.rag_results:
                topic = meta.get("topic", meta.get("title","Doc"))
                st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:12px;margin-bottom:8px">
                  <div style="font-size:10px;font-weight:700;color:var(--accent-teal);font-family:JetBrains Mono,monospace;margin-bottom:5px">📚 {topic} · {meta.get('vendor','general')}</div>
                  <div style="font-size:12px;color:var(--text-secondary);line-height:1.7">{content[:450]}{'…' if len(content)>450 else ''}</div>
                </div>""", unsafe_allow_html=True)
        else:
            st.markdown("**Pre-loaded knowledge topics:**")
            tc = st.columns(4)
            for i, t in enumerate(r_stat["topics"]):
                with tc[i % 4]:
                    st.markdown(f'<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:8px;padding:10px;font-size:12px;font-weight:600;color:var(--text-primary)">{t}</div>', unsafe_allow_html=True)

    with tab2:
        it  = st.text_input("Title", placeholder="Juniper BGP Config Guide", key="ing_title")
        ic1, ic2 = st.columns(2)
        iv  = ic1.selectbox("Vendor", ["cisco","juniper","arista","paloalto","fortinet","general"], key="ing_vendor")
        idt = ic2.selectbox("Type",   ["manual","runbook","design","reference","sop","config","incident"], key="ing_type")
        ico = st.text_area("Content (paste full document)", placeholder="Paste vendor documentation, runbooks, config examples, SOPs…", height=200, key="ing_content")
        if st.button("➕ Ingest into Knowledge Base", type="primary", key="ing_btn") and ico and it:
            with st.spinner("Chunking and indexing…"):
                n = ingest_document(it, ico, iv, idt)
            st.success(f"✅ Ingested **{n} chunks** from '{it}' into {'ChromaDB' if r_stat['backend']=='ChromaDB' else 'knowledge base'}")


# ══════════════════════════════════════════════════════════
# WORKSPACE: NETWORK DESIGN
# ══════════════════════════════════════════════════════════
elif ws == "design":
    section_header("🏗 AI Design Studio", "ChatGPT for network architecture · Requirements → Full design → BOM → Roadmap")

    st.markdown("""<div class="nb-design-studio">
      <div class="nb-ds-title">🎯 AI Network Design Studio</div>
      <div class="nb-ds-sub">Describe requirements in plain English. I generate full architecture, vendor selection, hardware sizing, BOM, and implementation roadmap.</div>
    </div>""", unsafe_allow_html=True)

    templates = [
        ("🏢","Enterprise Campus","3000 users · 3-tier · SD-Access · Wireless · Zero Trust · HA",
         "Design enterprise campus network: 3000 users, 3-tier hierarchy, Cisco SD-Access, 802.11ax wireless, Zero Trust security, full HA redundancy. Include topology, hardware sizing, BOM top 15 items, 90-day roadmap."),
        ("🛣️","SD-WAN Deployment","50 branches · Dual ISP · Azure · SASE · App-SLA",
         "Design SD-WAN: 50 branches, 200 users each, dual ISP, Azure integration, Zscaler SASE, app-aware routing. Compare Cisco Viptela vs Versa. Full BOM and migration strategy."),
        ("🏭","AI Datacenter Fabric","GPU clusters · VXLAN EVPN · RoCE · Leaf-Spine · 400G",
         "Design AI datacenter: 500 GPU servers, leaf-spine VXLAN EVPN, RoCE lossless networking, 400G uplinks, Arista EOS. Include fabric design, BOM, performance calculations."),
        ("☁️","Hybrid Cloud","On-prem + AWS + Azure · Direct Connect · ExpressRoute · HA",
         "Design hybrid cloud: 2 DCs to AWS and Azure, Direct Connect + ExpressRoute, BGP routing, SD-WAN integration, HA. Compare connectivity options, include routing design and security."),
        ("🔐","Zero Trust Architecture","ZTNA · Micro-seg · Identity · Palo Alto · Zscaler",
         "Design Zero Trust: ZTNA replacing VPN, micro-segmentation east-west, Palo Alto Prisma + Zscaler ZPA, identity-based access, MFA. Phased implementation, maturity model, BOM."),
        ("📡","5G Transport / SP","SR-MPLS · SRv6 · Slicing · Backhaul · Nokia/Cisco",
         "Design 5G transport: 500 cell sites, SR-MPLS underlay, SRv6 services, network slicing eMBB/URLLC/mMTC, Nokia SR-OS or Cisco IOS-XR. Transport architecture, timing sync, BOM."),
    ]
    dc = st.columns(3)
    for i, (ico, name, desc, prompt) in enumerate(templates):
        with dc[i % 3]:
            st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:14px;margin-bottom:10px">
              <div style="font-size:20px;margin-bottom:7px">{ico}</div>
              <div style="font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:3px">{name}</div>
              <div style="font-size:11px;color:var(--text-secondary);margin-bottom:10px;line-height:1.5">{desc}</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"Design {name}", key=f"ds_{name}", use_container_width=True):
                with st.spinner(f"🏗 Generating {name} architecture…"):
                    output = design_network(prompt, st.session_state.persona)
                st.session_state.design_output = output
                st.session_state.workspace = "design"
                st.rerun()

    st.divider()
    st.markdown("**Custom Design:**")
    d1, d2 = st.columns(2)
    with d1:
        rs = st.text_input("Sites", placeholder="1 HQ + 20 branches + 2 DCs", key="d_sites")
        ru = st.text_input("Users per location", placeholder="500 HQ, 100 branch", key="d_users")
        rc = st.text_input("Cloud", placeholder="Azure primary, AWS DR, M365", key="d_cloud")
        rsec = st.text_input("Security", placeholder="Zero Trust, SASE, PCI DSS", key="d_sec")
    with d2:
        rb = st.text_input("Budget", placeholder="Under $500K CapEx", key="d_budget")
        rv = st.text_input("Vendor preference", placeholder="Cisco preferred, open to Juniper", key="d_vendor")
        rh = st.text_input("HA requirements", placeholder="99.99% uptime, dual ISP", key="d_ha")
        rsp = st.text_area("Special requirements", height=68, placeholder="HIPAA compliance, AI workloads, IoT, video surveillance…", key="d_special")

    if st.button("🏗 Generate Full Architecture", type="primary", use_container_width=True, key="ds_custom"):
        reqs = f"Sites:{rs} | Users:{ru} | Cloud:{rc} | Security:{rsec} | Budget:{rb} | Vendors:{rv} | HA:{rh} | Special:{rsp}"
        with st.spinner("🧠 Generating architecture…"):
            output = design_network(reqs, st.session_state.persona)
        st.session_state.design_output = output

    if st.session_state.design_output:
        st.markdown("---")
        st.markdown("**🏗 Generated Architecture:**")
        st.markdown(st.session_state.design_output)
        st.download_button("⬇ Download as Markdown", st.session_state.design_output, "network_design.md", "text/markdown")


# ══════════════════════════════════════════════════════════
# WORKSPACE: LEARNING
# ══════════════════════════════════════════════════════════
elif ws == "learn":
    section_header("📖 Adaptive Learning Hub", "AI detects your level automatically · CCNA → CCNP → CCIE → Expert Architect")

    ai_insight_card(
        "Adaptive NLP Learning",
        f"Persona: <strong>{st.session_state.persona.upper()}</strong>. "
        "Ask <strong>'what is a VLAN?'</strong> → basics with analogy. "
        "Ask <strong>'explain Q-in-Q double-tagging MTU implications'</strong> → expert level. "
        "<strong>No configuration needed — I auto-detect your level.</strong>",
    )

    tracks = [
        ("🌐","Routing Fundamentals","OSPF · BGP · EIGRP · IS-IS · Policy · Redistribution",65,"blue","Start routing lesson. Detect my level. Include OSPF, BGP, EIGRP with practical examples."),
        ("🔀","Switching & Fabric","VLANs · STP · EtherChannel · RSTP · MACsec · SD-Access",40,"green","Teach switching and VLANs from my level. STP, EtherChannel, campus fabric design."),
        ("🛣️","WAN & SD-WAN","MPLS · SD-WAN · DMVPN · SASE · QoS · Cloud WAN",20,"amber","Explain WAN technologies. Start basics then Cisco Viptela, SASE, cloud WAN architecture."),
        ("🔒","Network Security","Zero Trust · ZTNA · Firewall · ACL · IPSec · SASE · NAC",55,"red","Teach network security from my level. Zero Trust, ZTNA, firewall policies, segmentation."),
        ("🏢","Datacenter","VXLAN · EVPN · Leaf-Spine · ACI · AI Fabric · RoCE",10,"purple","Explain datacenter networking. Why leaf-spine, VXLAN EVPN, AI fabric, RoCE for GPU."),
        ("☁️","Cloud & Hybrid","AWS VPC · Azure VNet · GCP · Transit Gateway · Kubernetes",30,"blue","Teach cloud networking. AWS VPC, Azure VNet, hybrid connectivity, Kubernetes CNI."),
        ("📡","Service Provider","MPLS L3VPN · SR-MPLS · SRv6 · 5G Transport · BGP-LU",5,"purple","Explain SP networking. MPLS L3VPN, SR-MPLS, SRv6, 5G transport. Expert level."),
        ("🤖","Automation","Ansible · Terraform · Python · NETCONF · RESTCONF · gRPC",15,"green","Teach network automation. Ansible, Python netmiko, NETCONF/RESTCONF, practical examples."),
    ]
    tc = st.columns(4)
    for i, (ico, name, desc, pct, color, prompt) in enumerate(tracks):
        with tc[i % 4]:
            color_map = {"blue":"#2f81f7","green":"#3fb950","amber":"#d29922","red":"#f85149","purple":"#bc8cff"}
            cv = color_map.get(color, "#2f81f7")
            st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:13px;margin-bottom:4px">
              <div style="font-size:18px;margin-bottom:6px">{ico}</div>
              <div style="font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:2px">{name}</div>
              <div style="font-size:11px;color:var(--text-secondary);margin-bottom:9px;line-height:1.5">{desc}</div>
              <div style="height:3px;background:var(--border-default);border-radius:4px;overflow:hidden;margin-bottom:4px"><div style="height:100%;width:{pct}%;background:{cv};border-radius:4px"></div></div>
              <div style="font-size:10px;color:var(--text-tertiary);font-family:JetBrains Mono,monospace">{pct}% complete</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"Start", key=f"tk_{name}", use_container_width=True):
                go(prompt, "learn")

    st.divider()
    lq = st.text_input("Ask anything to learn", placeholder="'What is BGP?' · 'Explain OSPF DR election' · 'How does VXLAN work?' · 'Compare SD-WAN vs MPLS'", key="lq")
    if st.button("📖 Learn", type="primary", key="learn_ask") and lq:
        go(lq, "learn")

    ai_learns = [m for m in st.session_state.chat_msgs if m["role"] == "assistant"]
    if ai_learns:
        with st.expander("📖 Latest Learning Response", expanded=True):
            render_chat_message("assistant", ai_learns[-1]["content"], ai_learns[-1].get("meta"))


# ══════════════════════════════════════════════════════════
# WORKSPACE: DEVICE MANAGER
# ══════════════════════════════════════════════════════════
elif ws == "devices":
    section_header("🖧 Device Manager", "Add SSH devices for multi-device query engine · Encrypted credential storage")

    t1, t2 = st.tabs(["📋 All Devices", "➕ Add Device"])
    with t1:
        devs = get_devices()
        if devs:
            df = pd.DataFrame(devs)[["hostname","ip","vendor","role","site","status","cpu","memory","port"]]
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption(f"**{len(devs)} devices** · SSH {'live' if NETMIKO_OK else '⚡ simulation mode'} · Passwords stored encrypted (Fernet)")
        else:
            st.info("No devices. Add below.")
    with t2:
        if has_permission("manage_devices"):
            c1, c2, c3 = st.columns(3)
            hn   = c1.text_input("Hostname", placeholder="CORE-RTR-01")
            ip   = c1.text_input("IP Address", placeholder="10.0.0.1")
            ven  = c2.selectbox("Vendor", ["cisco_ios","cisco_ios_xe","cisco_ios_xr","cisco_nxos","juniper_junos","arista_eos","paloalto_panos","fortinet","huawei_vrp"])
            role = c2.text_input("Role", placeholder="Core Router")
            usr  = c3.text_input("SSH Username", placeholder="admin")
            pwd  = c3.text_input("SSH Password", type="password")
            site = c3.text_input("Site", placeholder="HQ")
            port = c3.number_input("Port", value=22, min_value=1, max_value=65535)
            if st.button("➕ Add Device (encrypted)", type="primary"):
                if hn and ip:
                    add_device(hn, ip, ven, usr, pwd, int(port), role, site)
                    write_audit(st.session_state.user_name, "add_device", f"device:{hn}", f"IP:{ip}")
                    st.success(f"✅ Added {hn} — password encrypted with Fernet")
                    st.rerun()
                else:
                    st.error("Hostname and IP required")
        else:
            st.warning("🔒 Insufficient permissions to add devices")


# ══════════════════════════════════════════════════════════
# WORKSPACE: EXECUTIVE
# ══════════════════════════════════════════════════════════
elif ws == "executive":
    section_header("📈 Executive Dashboard", "Business impact · SLA performance · Risk scores · Board-ready metrics")

    metric_grid([
        {"label":"Network Uptime","value":"99.94%","meta":"SLA target 99.9% ✅","color":"green","icon":"✅"},
        {"label":"MTTR","value":"18m","meta":"↓ 40% vs last quarter","color":"blue","icon":"⚡"},
        {"label":"Risk Score","value":"Medium","meta":"14 CVEs · 2 threats","color":"amber","icon":"⚠"},
        {"label":"Automation Rate","value":"78%","meta":"↑ 12% this quarter","color":"green","icon":"🤖"},
    ])

    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**📊 Operational Health**")
        metrics_data = {"SLA Performance":"99.94%","MTTR Reduction":"↓ 40%","Change Success":"97.3%","Auto-Remediation":"94%","Incidents Resolved":"2/2"}
        for k, v in metrics_data.items():
            st.markdown(f'<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border-subtle)"><span style="color:var(--text-secondary);font-size:13px">{k}</span><span style="color:var(--text-primary);font-weight:700;font-size:13px">{v}</span></div>', unsafe_allow_html=True)
    with col_r:
        st.markdown("**💰 Business Value**")
        biz_data = {"Time Saved This Week":"4.2 hours","Outages Prevented":"3","Auto-Actions Executed":"47","Approx. Cost Saving":"$8,400","Engineers Upskilled":"8"}
        for k, v in biz_data.items():
            st.markdown(f'<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border-subtle)"><span style="color:var(--text-secondary);font-size:13px">{k}</span><span style="color:var(--accent-green);font-weight:700;font-size:13px">{v}</span></div>', unsafe_allow_html=True)

    if st.button("🧠 Generate Board Report", type="primary"):
        with st.spinner("Generating executive report…"):
            report = call_ai([{"role":"user","content":"Generate concise executive board report: network health uptime MTTR risks automation ROI investments needed 90-day outlook. Business language only."}], "manager", max_tokens=1500)
        st.markdown(report)
        st.download_button("⬇ Download Report", report, "exec_report.md", "text/markdown")


# ══════════════════════════════════════════════════════════
# WORKSPACE: AUDIT LOG
# ══════════════════════════════════════════════════════════
elif ws == "audit":
    if not require_permission("view_audit"):
        st.stop()
    section_header("🔐 Audit Log", "Complete audit trail · All user actions · Security events")

    logs = get_audit_logs(100)
    if logs:
        df = pd.DataFrame(logs)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"{len(logs)} audit entries shown")
    else:
        st.info("No audit events recorded yet.")


# ══════════════════════════════════════════════════════════
# WORKSPACE: OBSERVABILITY
# ══════════════════════════════════════════════════════════
elif ws == "observe":
    section_header("📡 Observability", "Live telemetry · Anomaly detection · SaaS monitoring · NetFlow · Syslog")

    telemetry = get_live_telemetry()
    anomalies = detect_anomalies(telemetry)

    if anomalies:
        crit = [a for a in anomalies if a["severity"] == "critical"]
        warn = [a for a in anomalies if a["severity"] == "warning"]
        ai_insight_card(
            "Anomaly Detection — Live",
            f"<strong>{len(crit)} critical</strong> and <strong>{len(warn)} warning</strong> anomalies detected. "
            + (f"Top: {crit[0]['message']} — {crit[0]['ai_hint']}" if crit else "No critical anomalies."),
            confidence=91,
        )

    # Metrics
    metric_grid([
        {"label":"Devices Monitored","value":str(len(telemetry)),"meta":"Live telemetry","color":"blue","icon":"📡"},
        {"label":"Active Anomalies","value":str(len(anomalies)),"meta":f"{len([a for a in anomalies if a['severity']=='critical'])} critical","color":"red" if anomalies else "green","icon":"⚠"},
        {"label":"Avg CPU","value":f"{int(sum(t['cpu'] for t in telemetry)/max(1,len(telemetry)))}%","meta":"Across all devices","color":"amber","icon":"💻"},
        {"label":"Avg Latency","value":"14ms","meta":"Network baseline","color":"green","icon":"⚡"},
    ])

    tab_live, tab_saas, tab_flow, tab_syslog = st.tabs(["📊 Live Telemetry","🌐 SaaS Health","🔄 NetFlow","📋 Syslog"])

    with tab_live:
        st.markdown("**Device Telemetry — Refreshes every 15s**")
        dev_cols = st.columns(4)
        for i, t in enumerate(telemetry):
            cpu, mem = t.get("cpu",0), t.get("memory",0)
            status = t.get("status","up")
            cpu_cls = "mv-crit" if cpu >= 85 else "mv-warn" if cpu >= 70 else "mv-ok"
            mem_cls = "mv-crit" if mem >= 80 else "mv-warn" if mem >= 60 else "mv-ok"
            with dev_cols[i % 4]:
                st.markdown(f"""<div class="nb-dev dev-{status}">
                  <div class="nb-dev-hn">{t['hostname']}</div>
                  <div class="nb-dev-role">{t['role']}</div>
                  <div class="nb-dev-metrics">
                    <div class="nb-dev-m"><div class="nb-dev-mv {cpu_cls}">{f"{cpu}%" if cpu else "—"}</div><div class="nb-dev-ml">CPU</div></div>
                    <div class="nb-dev-m"><div class="nb-dev-mv {mem_cls}">{f"{mem}%" if mem else "—"}</div><div class="nb-dev-ml">MEM</div></div>
                    <div class="nb-dev-m"><div class="nb-dev-mv {'mv-crit' if t.get('packet_loss',0)>0.5 else 'mv-ok'}">{t.get('packet_loss',0)}%</div><div class="nb-dev-ml">LOSS</div></div>
                    <div class="nb-dev-m"><div class="nb-dev-mv mv-ok">{t.get('latency_ms',0)}ms</div><div class="nb-dev-ml">RTT</div></div>
                  </div>
                </div>""", unsafe_allow_html=True)

        if anomalies:
            st.markdown("**🔍 Detected Anomalies:**")
            for a in anomalies:
                sev_ico = "🔴" if a["severity"] == "critical" else "🟡"
                st.markdown(f"""<div class="nb-timeline-item">
                  <div class="nb-tl-dot {'tl-crit' if a['severity']=='critical' else 'tl-warn'}">{sev_ico}</div>
                  <div class="nb-tl-body">
                    <div class="nb-tl-title">{a['message']}</div>
                    <div class="nb-tl-meta">{a['device']} · {a['type']} · value: {a['value']}</div>
                    <div class="nb-tl-ai">🧠 {a['ai_hint']}</div>
                  </div>
                </div>""", unsafe_allow_html=True)
            if st.button("🧠 AI Anomaly Analysis", type="primary"):
                anomaly_desc = "\n".join(f"- {a['message']} ({a['severity']})" for a in anomalies[:5])
                go(f"Analyze these network anomalies and correlate root causes:\n{anomaly_desc}", "troubleshoot")

    with tab_saas:
        saas = get_saas_health()
        st.markdown("**SaaS Application Health — Internet Experience Monitoring**")
        saas_cols = st.columns(4)
        for i, svc in enumerate(saas):
            score = svc["score"]
            color = "var(--accent-green)" if score >= 85 else "var(--accent-amber)" if score >= 60 else "var(--accent-red)"
            status_text = "Healthy" if score >= 85 else "Degraded" if score >= 60 else "Critical"
            with saas_cols[i % 4]:
                st.markdown(f"""<div class="nb-dev dev-{'up' if score>=85 else 'warn' if score>=60 else 'critical'}">
                  <div style="font-size:18px;margin-bottom:4px">{svc['icon']}</div>
                  <div class="nb-dev-hn" style="font-size:12px">{svc['name']}</div>
                  <div class="nb-dev-metrics">
                    <div class="nb-dev-m"><div class="nb-dev-mv" style="color:{color}">{score}</div><div class="nb-dev-ml">Score</div></div>
                    <div class="nb-dev-m"><div class="nb-dev-mv {'mv-warn' if svc['latency_ms']>150 else 'mv-ok'}">{svc['latency_ms']}ms</div><div class="nb-dev-ml">Latency</div></div>
                    <div class="nb-dev-m"><div class="nb-dev-mv {'mv-crit' if svc['loss_pct']>0.5 else 'mv-ok'}">{svc['loss_pct']}%</div><div class="nb-dev-ml">Loss</div></div>
                  </div>
                </div>""", unsafe_allow_html=True)
        degraded = [s for s in saas if s["score"] < 85]
        if degraded:
            if st.button("🧠 AI SaaS Analysis", type="primary"):
                desc = "\n".join(f"- {s['name']}: score {s['score']}, latency {s['latency_ms']}ms" for s in degraded)
                go(f"Analyze SaaS degradation:\n{desc}\nIs this caused by our BGP issues on PE-MUM-01?", "troubleshoot")

    with tab_flow:
        nf = get_netflow_summary()
        col_nf1, col_nf2 = st.columns(2)
        with col_nf1:
            st.markdown("**Top Talkers**")
            for t in nf["top_talkers"]:
                st.markdown(f"""<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border-subtle)">
                  <div><span style="font-family:JetBrains Mono,monospace;font-size:12px;color:var(--text-primary)">{t['src']}</span>
                  <span style="font-size:11px;color:var(--text-tertiary);margin:0 6px">→</span>
                  <span style="font-size:11px;color:var(--accent-blue)">{t['app']}</span></div>
                  <span style="font-family:JetBrains Mono,monospace;font-size:12px;font-weight:700;color:var(--accent-amber)">{t['mbps']} Mbps</span>
                </div>""", unsafe_allow_html=True)
        with col_nf2:
            st.markdown("**Traffic Summary**")
            st.metric("Total Throughput", f"{nf['total_gbps']} Gbps")
            st.metric("Flow Rate", f"{nf['flows_per_sec']:,} flows/s")
            for proto, pct in list(nf["protocol_mix"].items())[:5]:
                st.markdown(f'<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--border-subtle)"><span style="color:var(--text-secondary);font-size:12px">{proto}</span><span style="font-family:JetBrains Mono,monospace;font-size:12px;color:var(--text-primary)">{pct}%</span></div>', unsafe_allow_html=True)

    with tab_syslog:
        logs = get_recent_syslogs(15)
        st.markdown("**Recent Syslog Events**")
        for log in logs:
            sev = log["severity"]
            ico = "🔴" if sev == "critical" else "🟡" if sev == "warning" else "ℹ️"
            dot_cls = "tl-crit" if sev == "critical" else "tl-warn" if sev == "warning" else "tl-info"
            st.markdown(f"""<div class="nb-timeline-item">
              <div class="nb-tl-dot {dot_cls}">{ico}</div>
              <div class="nb-tl-body">
                <div class="nb-tl-title" style="font-family:JetBrains Mono,monospace;font-size:12px">{log['message']}</div>
                <div class="nb-tl-meta">{log['ts']} · {log['device']}</div>
              </div>
            </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# WORKSPACE: DIGITAL TWIN
# ══════════════════════════════════════════════════════════
elif ws == "twin":
    section_header("👾 Digital Twin", "Topology clone · Failure simulation · Change validation · What-if analysis")

    twin_stat = get_twin_status()
    ai_insight_card(
        "Digital Twin Engine",
        "Ask: <strong>'What happens if PE-MUM-01 fails?'</strong> → I simulate failure, show affected services, "
        "calculate failover time, and recommend mitigation — <strong>before it happens in production.</strong> "
        "Every change is tested here first.",
        confidence=99,
    )

    metric_grid([
        {"label":"Devices Cloned","value":str(twin_stat["cloned_devices"]),"meta":"From live topology","color":"blue","icon":"👾"},
        {"label":"Config Accuracy","value":f"{twin_stat['accuracy_pct']}%","meta":f"Last sync {twin_stat['last_sync_s']}s ago","color":"green","icon":"✅"},
        {"label":"Active Simulations","value":str(twin_stat["active_simulations"]),"meta":"Running now","color":"amber","icon":"⚡"},
        {"label":"Changes Tested","value":str(twin_stat["changes_tested"]),"meta":"This month","color":"green","icon":"🧪"},
    ])

    col_sim, col_result = st.columns([0.45, 0.55])

    with col_sim:
        st.markdown("**⚡ Failure Simulation**")
        devices = get_devices()
        dev_names = [d["hostname"] for d in devices]
        sim_device = st.selectbox("Select device to simulate failure", dev_names, key="twin_dev")
        if st.button("▶ Simulate Failure", type="primary", use_container_width=True, key="twin_sim"):
            with st.spinner(f"Simulating {sim_device} failure…"):
                result = simulate_failure(sim_device)
            st.session_state["twin_result"] = result
            st.session_state["twin_type"] = "failure"

        st.markdown("---")
        st.markdown("**🔧 Change Simulation**")
        chg_dev  = st.selectbox("Device", dev_names, key="twin_chg_dev")
        chg_type = st.selectbox("Change type", ["firmware","config","vlan","routing","hardware"], key="twin_chg_type")
        chg_desc = st.text_input("Change description", placeholder="e.g. Upgrade IOS-XR 7.5.2 → 7.7.1", key="twin_chg_desc")
        if st.button("▶ Simulate Change", use_container_width=True, key="twin_chg_sim"):
            with st.spinner("Simulating change impact…"):
                result = simulate_change(chg_dev, chg_type, chg_desc or f"{chg_type} on {chg_dev}")
            st.session_state["twin_result"] = result
            st.session_state["twin_type"] = "change"

        st.markdown("---")
        st.markdown("**🤖 AI What-If Scenarios**")
        for scenario, prompt in [
            ("PE-MUM-01 failure", "Simulate complete failure of PE-MUM-01. What services fail? Failover? Recommendations?"),
            ("ISP link drops", "What if the ISP link on PE-MUM-01 to AS65002 goes completely down?"),
            ("CORE-RTR-01 firmware", "Simulate firmware upgrade on CORE-RTR-01 from 7.5.2 to 7.7.1. Risk and downtime?"),
            ("Add OSPF area 10", "Validate adding OSPF area 10 with 5 new subnets before production. What are risks?"),
        ]:
            if st.button(f"▶ {scenario}", key=f"twin_{scenario}", use_container_width=True):
                go(prompt, "twin", "Digital Twin workspace — what-if simulation")

    with col_result:
        st.markdown("**📊 Simulation Result**")
        result = st.session_state.get("twin_result")
        twin_type = st.session_state.get("twin_type", "failure")

        if not result:
            st.info("Run a simulation on the left to see results here.")
        elif twin_type == "failure":
            sev_color = "var(--accent-red)" if result.get("severity") == "critical" else "var(--accent-amber)"
            # Pre-compute expressions to avoid backslash-in-f-string SyntaxError
            failover_txt = ("✅ " + str(result.get("failover_device","")) + " (" + str(result.get("estimated_rto_s","?")) + "s)") if result.get("failover_possible") else "❌ No failover — SPOF"
            spof_color   = "var(--accent-red)" if result.get("is_spof") else "var(--accent-green)"
            spof_txt     = "⚠️ YES" if result.get("is_spof") else "✅ No"
            services_html = "".join(
                '<span style="font-size:11px;padding:2px 7px;border-radius:8px;background:var(--accent-red-subtle);color:var(--accent-red);margin:2px;display:inline-block">' + s + '</span>'
                for s in result.get("affected_services", [])
            )
            recs_html = "".join(
                '<div style="font-size:12px;color:var(--text-primary);padding:4px 0;border-bottom:1px solid var(--border-subtle)">' + rec + '</div>'
                for rec in result.get("recommendations", [])
            )
            st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:16px;margin-bottom:10px">
              <div style="font-size:14px;font-weight:700;color:{sev_color};margin-bottom:12px">⚡ Failure: {result.get('failed_device','')}</div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px">
                <div><div style="font-size:10px;color:var(--text-tertiary);font-family:JetBrains Mono,monospace;text-transform:uppercase;margin-bottom:3px">Criticality</div><div style="font-size:16px;font-weight:700;color:{sev_color}">{result.get('criticality',0)}/10</div></div>
                <div><div style="font-size:10px;color:var(--text-tertiary);font-family:JetBrains Mono,monospace;text-transform:uppercase;margin-bottom:3px">Users Impacted</div><div style="font-size:16px;font-weight:700;color:var(--accent-red)">{result.get('affected_users',0)}</div></div>
                <div><div style="font-size:10px;color:var(--text-tertiary);font-family:JetBrains Mono,monospace;text-transform:uppercase;margin-bottom:3px">Failover</div><div style="font-size:13px;font-weight:600;color:var(--accent-green)">{failover_txt}</div></div>
                <div><div style="font-size:10px;color:var(--text-tertiary);font-family:JetBrains Mono,monospace;text-transform:uppercase;margin-bottom:3px">SPOF</div><div style="font-size:13px;font-weight:600;color:{spof_color}">{spof_txt}</div></div>
              </div>
              <div style="margin-bottom:8px"><div style="font-size:10px;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.8px;font-family:JetBrains Mono,monospace;margin-bottom:5px">Affected Services</div>{services_html}</div>
              <div><div style="font-size:10px;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.8px;font-family:JetBrains Mono,monospace;margin-bottom:5px">AI Recommendations</div>{recs_html}</div>
            </div>""", unsafe_allow_html=True)
        else:
            score = result.get("risk_score", 0)
            risk_cls = "risk-low" if score < 30 else "risk-med" if score < 65 else "risk-high"
            st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:16px">
              <div style="font-size:14px;font-weight:700;color:var(--text-primary);margin-bottom:12px">🔧 Change: {result.get('device','')} — {result.get('change_type','')}</div>
              <div style="margin-bottom:10px"><div style="font-size:10px;color:var(--text-tertiary);text-transform:uppercase;font-family:JetBrains Mono,monospace;margin-bottom:4px">Risk Score</div></div>
            </div>""", unsafe_allow_html=True)
            risk_bar(score)
            st.markdown(f"**Downtime:** {result.get('predicted_downtime',0)}s &nbsp;|&nbsp; **Users:** {result.get('affected_users',0)}")
            st.markdown(f"**Maintenance window required:** {'✅ Yes' if result.get('maintenance_window_required') else '❌ No'}")
            if result.get("risks"):
                st.markdown("**Risks:**")
                for r in result["risks"]:
                    st.markdown(f"- {r}")
            if result.get("rollback_steps"):
                with st.expander("📋 Rollback Plan"):
                    for step in result["rollback_steps"]:
                        st.markdown(f"`{step}`")


# ══════════════════════════════════════════════════════════
# WORKSPACE: SECURITY OPERATIONS
# ══════════════════════════════════════════════════════════
elif ws == "security":
    section_header("🔒 Security Operations", "Zero Trust · Threat correlation · Firewall intelligence · Posture analysis")

    ai_insight_card(
        "Security Intelligence",
        "<strong>Lateral movement detected</strong> from 10.2.14.0/24 (SW-ACC-14 segment) — "
        "port scan pattern, 23 hosts probed in 4 minutes. "
        "<strong>Zero Trust score: 62%</strong> — micro-segmentation gap in access layer. "
        "<strong>14 unpatched CVEs</strong> on edge devices — 3 critical severity.",
        confidence=89, sources=["Firewall","SIEM","Threat Intel"],
    )

    metric_grid([
        {"label":"Active Threats","value":"2","meta":"Lateral movement + CVEs","color":"red","icon":"🚨"},
        {"label":"CVEs Unpatched","value":"14","meta":"3 critical severity","color":"amber","icon":"⚠"},
        {"label":"FW Rule Health","value":"98%","meta":"Shadow rules cleaned","color":"green","icon":"🛡"},
        {"label":"Zero Trust Score","value":"62%","meta":"Improving +8% this month","color":"blue","icon":"🔐"},
    ])

    tab_threats, tab_fw, tab_zt, tab_vuln = st.tabs(["🚨 Threats","🛡 Firewall","🔐 Zero Trust","⚠ Vulnerabilities"])

    with tab_threats:
        threats = [
            {"sev":"critical","type":"Lateral Movement","src":"10.2.14.45","dst":"10.1.0.0/16","detail":"Port scan 23 hosts in 4 min on SW-ACC-14 segment. Possible credential theft following interface failure.","action":"Isolate 10.2.14.45. Check for compromised credentials. Enable 802.1X."},
            {"sev":"warning","type":"Unusual Egress","src":"10.1.100.87","dst":"45.141.87.0/24","detail":"DNS queries to known C2 domain (IOC match). Volume 2x baseline.","action":"Block at DNS layer (Umbrella). Investigate endpoint 10.1.100.87."},
        ]
        for t in threats:
            st.markdown(f"""<div class="nb-warroom">
              <div class="nb-wr-hdr" style="background:{'linear-gradient(135deg,#3d0f0a,#5c1a12)' if t['sev']=='critical' else 'linear-gradient(135deg,#3d2b00,#6b4a00)'}">
                <div class="nb-wr-pulse"></div>
                <div class="nb-wr-title">{'🔴' if t['sev']=='critical' else '🟡'} {t['type']}</div>
              </div>
              <div style="padding:14px 18px">
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                  <div><div style="font-size:10px;color:var(--text-tertiary);text-transform:uppercase;font-family:JetBrains Mono,monospace;margin-bottom:3px">Source → Destination</div><div style="font-size:13px;font-family:JetBrains Mono,monospace;color:var(--accent-red)">{t['src']} → {t['dst']}</div></div>
                  <div><div style="font-size:10px;color:var(--text-tertiary);text-transform:uppercase;font-family:JetBrains Mono,monospace;margin-bottom:3px">Detail</div><div style="font-size:12px;color:var(--text-primary)">{t['detail']}</div></div>
                </div>
                <div style="margin-top:8px;padding:8px;background:rgba(47,129,247,.06);border-radius:6px;font-size:12px;color:var(--accent-blue)">🧠 Recommended: {t['action']}</div>
              </div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"🧠 AI Threat Analysis", key=f"threat_{t['type']}", use_container_width=True):
                go(f"Security threat: {t['type']} — {t['detail']}. Source: {t['src']}. Analyze attack path, lateral movement risk, and provide containment actions.", "security")

    with tab_fw:
        st.markdown("**Firewall Rule Health — FW-EDGE-01**")
        fw_stats = [
            ("Total rules","284","Rule base size"),("Shadow rules","0","Cleaned last week"),
            ("Unused rules","12","No traffic in 90 days"),("Any-Any rules","2","High risk — review needed"),
            ("Expired rules","4","Past end-date"),("Rules without logs","8","Compliance gap"),
        ]
        fc = st.columns(3)
        for i, (label, val, meta) in enumerate(fw_stats):
            with fc[i % 3]:
                color = "var(--accent-red)" if "risk" in meta.lower() or "gap" in meta.lower() else "var(--accent-green)" if val == "0" else "var(--text-primary)"
                st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:8px;padding:12px;text-align:center;margin-bottom:8px">
                  <div style="font-size:10px;color:var(--text-tertiary);text-transform:uppercase;font-family:JetBrains Mono,monospace;margin-bottom:4px">{label}</div>
                  <div style="font-size:22px;font-weight:700;font-family:Fraunces,serif;color:{color}">{val}</div>
                  <div style="font-size:11px;color:var(--text-tertiary)">{meta}</div>
                </div>""", unsafe_allow_html=True)
        if st.button("🧠 AI Firewall Optimization", type="primary"):
            go("Analyze firewall rule base: shadow rules, unused rules, any-any rules, missing logs. Provide cleanup recommendations prioritized by risk.", "security")

    with tab_zt:
        st.markdown("**Zero Trust Maturity Assessment**")
        pillars = [
            ("Identity","80%","MFA enforced. Conditional access configured.","green"),
            ("Devices","65%","MDM enrolled. Some unmanaged devices remain.","amber"),
            ("Networks","50%","Micro-segmentation partial. VXLAN in DC only.","amber"),
            ("Applications","70%","ZTNA deployed for 60% of apps. VPN still used.","amber"),
            ("Data","45%","DLP partial. Shadow IT uncontrolled.","red"),
            ("Visibility","75%","SIEM active. NDR deployed. Some gaps in cloud.","green"),
        ]
        pc = st.columns(3)
        for i, (pillar, score, desc, color) in enumerate(pillars):
            pct = int(score.rstrip("%"))
            bar_color = {"green":"var(--accent-green)","amber":"var(--accent-amber)","red":"var(--accent-red)"}[color]
            with pc[i % 3]:
                st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:13px;margin-bottom:8px">
                  <div style="font-size:12px;font-weight:700;color:var(--text-primary);margin-bottom:3px">{pillar}</div>
                  <div style="font-size:18px;font-weight:700;font-family:Fraunces,serif;color:{bar_color};margin-bottom:6px">{score}</div>
                  <div style="height:3px;background:var(--border-default);border-radius:4px;overflow:hidden;margin-bottom:6px"><div style="height:100%;width:{pct}%;background:{bar_color}"></div></div>
                  <div style="font-size:11px;color:var(--text-tertiary)">{desc}</div>
                </div>""", unsafe_allow_html=True)
        if st.button("🧠 Zero Trust Gap Analysis", type="primary"):
            go("Full Zero Trust maturity assessment. Top 5 gaps to close, prioritized by risk reduction impact. Practical implementation steps for each.", "security")

    with tab_vuln:
        vulns = [
            ("CVE-2024-20399","Cisco IOS-XR","9.8 Critical","FW-EDGE-01, PE-MUM-01","Patch available — schedule immediately"),
            ("CVE-2024-3400", "Palo Alto PAN-OS","10.0 Critical","FW-EDGE-01","Emergency patch — exploited in wild"),
            ("CVE-2023-44487","HTTP/2","7.5 High","WLC-HQ-01","Apply workaround — vendor patch pending"),
            ("CVE-2024-21893","Fortinet","8.2 High","No Fortinet devices","N/A in your environment"),
        ]
        for v in vulns[:3]:
            sev_color = "var(--accent-red)" if "Critical" in v[2] else "var(--accent-amber)"
            st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-left:3px solid {sev_color};border-radius:0 10px 10px 0;padding:12px;margin-bottom:8px;display:flex;gap:12px;align-items:flex-start">
              <div style="flex:1">
                <div style="font-family:JetBrains Mono,monospace;font-size:12px;font-weight:600;color:{sev_color}">{v[0]} — {v[1]}</div>
                <div style="font-size:13px;color:var(--text-primary);margin:3px 0">CVSS: {v[2]} · Affected: {v[3]}</div>
                <div style="font-size:11px;color:var(--accent-blue)">🧠 {v[4]}</div>
              </div>
            </div>""", unsafe_allow_html=True)
        if st.button("🧠 AI Vulnerability Prioritization", type="primary"):
            go("Prioritize 14 unpatched CVEs on network devices. Which to patch first based on CVSS score, exposure, and our specific network topology? Provide patch schedule.", "security")


# ══════════════════════════════════════════════════════════
# WORKSPACE: COMPLIANCE
# ══════════════════════════════════════════════════════════
elif ws == "compliance":
    section_header("🛡 Compliance & Posture", "CIS · NIST · PCI DSS · ISO 27001 · Zero Trust · Automated validation")

    ai_insight_card(
        "Compliance Intelligence",
        "<strong>Overall posture: 84%</strong> across all frameworks. "
        "Top gap: <strong>NIST CSF Identity pillar (72%)</strong> — incomplete MFA rollout. "
        "<strong>PCI DSS cardholder environment</strong> correctly isolated. "
        "<strong>14 CVEs</strong> create compliance risk — remediate within 30 days per policy.",
        confidence=91,
    )

    # Framework scores
    frameworks = [
        ("CIS Benchmark","91%",91,"23 violations of 256 controls","green"),
        ("NIST CSF 2.0","78%",78,"Identity + Govern pillars gap","amber"),
        ("PCI DSS 4.0","96%",96,"Cardholder network isolated","green"),
        ("ISO 27001","88%",88,"Audit trail complete","green"),
        ("Zero Trust","62%",62,"Micro-segmentation partial","amber"),
        ("Firmware CVEs","14 open",14,"3 critical unpatched → compliance risk","red"),
    ]
    fc = st.columns(3)
    for i, (name, score, pct, desc, color) in enumerate(frameworks):
        bar_color = {"green":"var(--accent-green)","amber":"var(--accent-amber)","red":"var(--accent-red)"}[color]
        bar_w = min(100, pct)
        with fc[i % 3]:
            st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:14px;margin-bottom:10px">
              <div style="font-size:11px;font-weight:700;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.8px;font-family:JetBrains Mono,monospace;margin-bottom:5px">{name}</div>
              <div style="font-size:24px;font-weight:700;font-family:Fraunces,serif;color:{bar_color};margin-bottom:6px">{score}</div>
              <div style="height:4px;background:var(--border-default);border-radius:4px;overflow:hidden;margin-bottom:6px"><div style="height:100%;width:{bar_w}%;background:{bar_color}"></div></div>
              <div style="font-size:11px;color:var(--text-tertiary)">{desc}</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # Remediation priorities
    st.markdown("**🔧 Top Remediation Priorities**")
    priorities = [
        ("🔴","P1","Patch CVE-2024-3400 on FW-EDGE-01","PAN-OS critical — exploited in wild. Emergency maintenance window.","3 days"),
        ("🔴","P1","Complete MFA rollout for NIST CSF","18% of users lack MFA. NIST CSF Identity gap.","7 days"),
        ("🟡","P2","Remove unused firewall rules (12)","PCI DSS 1.2.1 requires rule review quarterly.","14 days"),
        ("🟡","P2","Enable logging on 8 firewall rules","Compliance requires all rules logged.","7 days"),
        ("🟢","P3","Micro-segmentation — access layer","Zero Trust maturity gap. Implement 802.1X.","60 days"),
    ]
    for sev, pri, title, detail, deadline in priorities:
        st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:12px;margin-bottom:8px;display:flex;align-items:flex-start;gap:12px">
          <div style="font-size:18px;flex-shrink:0">{sev}</div>
          <div style="flex:1">
            <div style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:2px">{title}</div>
            <div style="font-size:12px;color:var(--text-secondary)">{detail}</div>
          </div>
          <div style="font-size:11px;font-family:JetBrains Mono,monospace;color:var(--text-tertiary);flex-shrink:0">Due: {deadline}</div>
        </div>""", unsafe_allow_html=True)

    col_c1, col_c2 = st.columns(2)
    with col_c1:
        if st.button("🧠 AI Gap Analysis", type="primary", use_container_width=True):
            go("Full compliance gap analysis across CIS Benchmark, NIST CSF 2.0, PCI DSS 4.0, Zero Trust. Top 5 gaps with business risk, remediation steps, and implementation timeline.", "compliance")
    with col_c2:
        if st.button("📋 Generate Audit Report", use_container_width=True):
            go("Generate a formal compliance audit report suitable for CISO and board presentation. Include all frameworks, scores, gaps, risks, and remediation roadmap.", "compliance")


# ══════════════════════════════════════════════════════════
# WORKSPACE: FINOPS
# ══════════════════════════════════════════════════════════
elif ws == "finops":
    section_header("💰 FinOps & Cost Intelligence", "License optimization · Cloud cost · Hardware lifecycle · ROI tracking")

    ai_insight_card(
        "Cost Intelligence",
        "<strong>$380K savings identified</strong> this quarter. Top opportunities: "
        "<strong>18% unused Cisco licenses</strong> ($142K), "
        "<strong>34 EoL devices</strong> nearing support expiry ($220K refresh avoided with timing), "
        "<strong>SD-WAN replacing MPLS</strong> at 3 branches saves $45K/year.",
        confidence=84,
    )

    metric_grid([
        {"label":"Annual Network Spend","value":"$4.2M","meta":"Within approved budget","color":"blue","icon":"💰"},
        {"label":"Identified Savings","value":"$380K","meta":"License + cloud rightsizing","color":"green","icon":"📉"},
        {"label":"EoL Hardware","value":"34","meta":"Devices need replacement","color":"amber","icon":"⚠"},
        {"label":"Wasted Licenses","value":"18%","meta":"Unused entitlements","color":"red","icon":"🔓"},
    ])

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        st.markdown("**💡 Savings Opportunities**")
        opps = [
            ("Cisco Smart Licensing","$142K/yr","18% of DNA licenses unused. Rightsizing recommended.","green"),
            ("MPLS → SD-WAN migration","$45K/yr","3 branches still on MPLS. SD-WAN at half the cost.","green"),
            ("Cloud egress optimization","$28K/yr","Suboptimal routing increases AWS egress charges.","amber"),
            ("Hardware EoL planning","$220K total","Early refresh of 12 critical devices saves premium support.","amber"),
            ("Redundant WAN links","$18K/yr","2 backup circuits unused >99% of time.","red"),
        ]
        for item, savings, detail, color in opps:
            bar_color = {"green":"var(--accent-green)","amber":"var(--accent-amber)","red":"var(--accent-red)"}[color]
            st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:12px;margin-bottom:8px">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px">
                <div style="font-size:13px;font-weight:600;color:var(--text-primary)">{item}</div>
                <div style="font-size:14px;font-weight:700;color:{bar_color};font-family:Fraunces,serif">{savings}</div>
              </div>
              <div style="font-size:12px;color:var(--text-secondary)">{detail}</div>
            </div>""", unsafe_allow_html=True)

    with col_f2:
        st.markdown("**📊 Spend Breakdown**")
        breakdown = [
            ("Hardware CapEx","$1.8M","43%"),("Software Licenses","$920K","22%"),
            ("MPLS/WAN Circuits","$680K","16%"),("Cloud Connectivity","$420K","10%"),
            ("Maintenance & Support","$280K","7%"),("Professional Services","$100K","2%"),
        ]
        for item, amount, pct in breakdown:
            st.markdown(f"""<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border-subtle)">
              <span style="font-size:13px;color:var(--text-secondary)">{item}</span>
              <div style="text-align:right">
                <span style="font-size:13px;font-weight:700;color:var(--text-primary);margin-right:10px">{amount}</span>
                <span style="font-size:11px;font-family:JetBrains Mono,monospace;color:var(--text-tertiary)">{pct}</span>
              </div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("**📈 Automation ROI**")
        roi_data = [
            ("Hours saved (automation)","4.2 hrs/week"),("Incidents auto-resolved","12 this month"),
            ("MTTR reduction","↓ 40% vs last year"),("Estimated cost saving","$8,400/month"),
        ]
        for label, val in roi_data:
            st.markdown(f'<div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--border-subtle)"><span style="color:var(--text-secondary);font-size:12px">{label}</span><span style="color:var(--accent-green);font-weight:700;font-size:12px">{val}</span></div>', unsafe_allow_html=True)

    st.markdown("---")
    if st.button("🧠 AI Cost Optimization Analysis", type="primary"):
        go("Analyze network cost structure and identify top 5 optimization opportunities: license consolidation, hardware refresh timing, WAN modernization, cloud cost reduction, automation ROI. Include 3-year TCO comparison.", "finops")


# ══════════════════════════════════════════════════════════
# FLOATING AI COPILOT (non-primary workspaces)
# ══════════════════════════════════════════════════════════
if ws not in ["troubleshoot", "learn", "design"]:
    st.markdown("---")
    with st.expander("💬 AI Copilot — Always available", expanded=False):
        if st.session_state.chat_msgs:
            for msg in st.session_state.chat_msgs[-4:]:
                render_chat_message(msg["role"], msg["content"], msg.get("meta"))

        ci, cb, ccl = st.columns([0.80, 0.12, 0.08])
        with ci:
            fi = st.text_input("", placeholder="Ask anything about your network…",
                               label_visibility="collapsed", key="float_inp")
        with cb:
            if st.button("Send", use_container_width=True, type="primary", key="float_send") and fi:
                go(fi, ws)
        with ccl:
            if st.button("🗑", use_container_width=True, key="float_clr"):
                st.session_state.chat_msgs = []; st.session_state.chat_hist = []; st.rerun()
