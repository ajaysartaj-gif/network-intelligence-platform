import os
from contextlib import contextmanager
from typing import Dict, Generator, List, Optional

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from database.models import (
    Base,
    AIQuery,
    ChangeRequest,
    ComplianceRule,
    Device,
    Incident,
    NetworkLink,
    Telemetry,
)

DATABASE_URL = os.environ.get("NETBRAIN_DATABASE_URL", "sqlite:///netbrain_ai.db")

engine: Engine = create_engine(
    DATABASE_URL,
    future=True,
    echo=False,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_db() -> None:
    Base.metadata.create_all(engine)


def seed_database() -> bool:
    create_db()
    from database.seed import seed_database as run_seed
    return run_seed()


def _serialize_device(device: Device) -> Dict[str, object]:
    return {
        "id": device.id,
        "hostname": device.hostname,
        "ip_address": device.ip_address,
        "vendor": device.vendor,
        "model": device.model,
        "role": device.role,
        "site": device.site,
        "os_version": device.os_version,
        "status": device.status,
    }


def _serialize_incident(incident: Incident) -> Dict[str, object]:
    return {
        "id": incident.id,
        "title": incident.title,
        "severity": incident.severity,
        "status": incident.status,
        "assigned_to": incident.assigned_to,
        "affected_service": incident.affected_service,
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
        "description": incident.description,
    }


def get_devices(status: Optional[str] = None) -> List[Dict[str, object]]:
    with get_session() as session:
        stmt = select(Device)
        if status:
            stmt = stmt.where(Device.status == status)
        devices = session.execute(stmt).scalars().all()
        return [_serialize_device(device) for device in devices]


def get_incidents(status: Optional[str] = None) -> List[Dict[str, object]]:
    with get_session() as session:
        stmt = select(Incident)
        if status:
            stmt = stmt.where(Incident.status == status)
        incidents = session.execute(stmt).scalars().all()
        return [_serialize_incident(incident) for incident in incidents]


def get_changes() -> List[Dict[str, object]]:
    with get_session() as session:
        changes = session.execute(select(ChangeRequest)).scalars().all()
        return [
            {
                "id": change.id,
                "title": change.title,
                "status": change.status,
                "risk": change.risk,
                "implementation_date": change.implementation_date,
                "engineer": change.engineer,
            }
            for change in changes
        ]


def get_auto_actions() -> List[Dict[str, object]]:
    # Auto actions are simulated from incident state and remediation recommendations.
    with get_session() as session:
        incidents = session.execute(select(Incident).limit(5)).scalars().all()
        return [
            {
                "incident_id": incident.id,
                "title": incident.title,
                "recommended_action": "Review incident and approve remediation.",
                "severity": incident.severity,
            }
            for incident in incidents
        ]


def add_device(device_data: Dict[str, object]) -> Device:
    with get_session() as session:
        device = Device(**device_data)
        session.add(device)
        session.commit()
        session.refresh(device)
        return device


def add_incident(incident_data: Dict[str, object]) -> Incident:
    with get_session() as session:
        incident = Incident(**incident_data)
        session.add(incident)
        session.commit()
        session.refresh(incident)
        return incident


def update_record(model: object, record_id: int, update_data: Dict[str, object]) -> Optional[object]:
    with get_session() as session:
        instance = session.get(model, record_id)
        if instance is None:
            return None
        for key, value in update_data.items():
            setattr(instance, key, value)
        session.commit()
        session.refresh(instance)
        return instance


def write_audit(*args, **kwargs) -> bool:
    # Placeholder for audit log persistence in later phases.
    return True


def log_ai_query(query: str, response: str, source: str = "user") -> AIQuery:
    with get_session() as session:
        record = AIQuery(query=query, response=response, source=source)
        session.add(record)
        session.commit()
        session.refresh(record)
        return record


def get_ai_history(limit: int = 20) -> List[Dict[str, object]]:
    with get_session() as session:
        queries = session.execute(select(AIQuery).order_by(AIQuery.created_at.desc()).limit(limit)).scalars().all()
        return [
            {
                "id": query.id,
                "query": query.query,
                "response": query.response,
                "source": query.source,
                "created_at": query.created_at.isoformat() if query.created_at else None,
            }
            for query in queries
        ]


def get_audit_logs(limit: int = 100) -> List[Dict[str, object]]:
    return []
