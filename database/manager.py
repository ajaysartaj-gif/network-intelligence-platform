"""Database connection and caching manager."""

import os
import logging
from datetime import datetime
from contextlib import contextmanager
from typing import List, Optional

import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from config import DATABASE_URL, SECRET_KEY
from database.models import Base, Device, Incident, Change, AutonomousAction, AuditLog, User
from core.cache_manager import CacheManager

logger = logging.getLogger(__name__)


# Encryption utilities
def _get_fernet():
    """Get Fernet cipher for password encryption."""
    try:
        from cryptography.fernet import Fernet
        key = SECRET_KEY
        if not key:
            key = Fernet.generate_key().decode()
            logger.warning("No SECRET_KEY — using ephemeral key")
        if isinstance(key, str):
            key = key.encode()
        return Fernet(key)
    except ImportError:
        return None


def encrypt_password(plaintext: str) -> str:
    """Encrypt password with Fernet."""
    f = _get_fernet()
    if f and plaintext:
        return f.encrypt(plaintext.encode()).decode()
    return plaintext


def decrypt_password(ciphertext: str) -> str:
    """Decrypt password with Fernet."""
    f = _get_fernet()
    if f and ciphertext:
        try:
            return f.decrypt(ciphertext.encode()).decode()
        except Exception:
            return ciphertext
    return ciphertext


# Database engine
@st.cache_resource
def get_engine():
    """Create and cache database engine."""
    if DATABASE_URL and "postgresql" in DATABASE_URL:
        engine = create_engine(
            DATABASE_URL,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True
        )
        logger.info("Connected to PostgreSQL")
    else:
        engine = create_engine(
            "sqlite:///netbrain.db",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.commit()
        logger.info("Connected to SQLite")

    Base.metadata.create_all(engine)
    return engine


SessionLocal = sessionmaker(autocommit=False, autoflush=False)


@contextmanager
def get_db() -> Session:
    """Get database session with auto-commit/rollback."""
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


class DatabaseManager:
    """Cached database access layer."""

    def __init__(self):
        self.cache = CacheManager()

    def get_devices(self) -> List[dict]:
        """Get all devices with caching."""
        cache_key = "devices:all"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        with get_db() as db:
            rows = db.query(Device).order_by(Device.hostname).all()
            result = [_device_to_dict(r) for r in rows]

        self.cache.set(cache_key, result)
        return result

    def get_incidents(self, status: Optional[str] = None) -> List[dict]:
        """Get incidents with optional status filter."""
        cache_key = f"incidents:{status or 'all'}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        with get_db() as db:
            q = db.query(Incident).order_by(Incident.created_at.desc())
            if status:
                q = q.filter(Incident.status == status)
            result = [_inc_to_dict(r) for r in q.all()]

        self.cache.set(cache_key, result)
        return result

    def get_changes(self) -> List[dict]:
        """Get all changes with caching."""
        cache_key = "changes:all"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        with get_db() as db:
            result = [_chg_to_dict(r) for r in db.query(Change).order_by(Change.created_at.desc()).all()]

        self.cache.set(cache_key, result)
        return result

    def get_auto_actions(self) -> List[dict]:
        """Get autonomous actions with caching."""
        cache_key = "auto_actions:all"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        with get_db() as db:
            result = [_aa_to_dict(r) for r in db.query(AutonomousAction).order_by(AutonomousAction.created_at.desc()).all()]

        self.cache.set(cache_key, result)
        return result

    def get_audit_logs(self, limit: int = 100) -> List[dict]:
        """Get audit logs."""
        with get_db() as db:
            rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
            return [{"user": r.user, "action": r.action, "resource": r.resource,
                     "detail": r.detail, "result": r.result, "ts": str(r.created_at)} for r in rows]

    def invalidate_cache(self, pattern: str) -> None:
        """Invalidate cache entries matching pattern."""
        self.cache.invalidate(pattern)


# Converters
def _device_to_dict(d: Device) -> dict:
    return {
        "id": d.id,
        "hostname": d.hostname,
        "ip": d.ip,
        "vendor": d.vendor,
        "username": d.username,
        "password": decrypt_password(d.password_enc or ""),
        "port": d.port,
        "role": d.role or "",
        "site": d.site or "",
        "status": d.status or "unknown",
        "cpu": d.cpu or 0,
        "memory": d.memory or 0,
        "os_version": d.os_version or "",
    }


def _inc_to_dict(i: Incident) -> dict:
    return {
        "id": i.id,
        "title": i.title,
        "description": i.description or "",
        "root_cause": i.root_cause or "",
        "resolution": i.resolution or "",
        "protocols": i.protocols or "",
        "severity": i.severity or "major",
        "status": i.status or "active",
        "business_impact": i.business_impact or "",
        "affected_users": i.affected_users or 0,
        "ai_confidence": i.ai_confidence or 0,
        "created_at": str(i.created_at or ""),
    }


def _chg_to_dict(c: Change) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "description": c.description or "",
        "device": c.device or "",
        "change_type": c.change_type or "",
        "risk_level": c.risk_level or "low",
        "status": c.status or "pending",
        "ai_risk_score": c.ai_risk_score or 0,
        "ai_recommendation": c.ai_recommendation or "",
        "rollback_plan": c.rollback_plan or "",
        "created_by": c.created_by or "",
    }


def _aa_to_dict(a: AutonomousAction) -> dict:
    return {
        "id": a.id,
        "action": a.action,
        "device": a.device or "",
        "trigger": a.trigger or "",
        "ai_confidence": a.ai_confidence or 0,
        "status": a.status or "pending",
        "result": a.result or "",
    }


@st.cache_resource
def get_db_manager() -> DatabaseManager:
    """Get singleton database manager instance."""
    return DatabaseManager()
