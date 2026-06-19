"""
core/knowledge/cache/cache_db.py
================================
SQLite-backed local cache of vendor knowledge.

Schema:
  - One row per (vendor, platform, command) tuple
  - Stores source URL, syntax, description, example output
  - TTL-based expiry, hit count tracking
  - Auto-creates DB and tables on first use
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.knowledge.base import (
    Citation,
    ConfidenceLevel,
    KnowledgeEntry,
)

logger = logging.getLogger("NetBrain.Knowledge.Cache")

# ── Default cache location (gitignored) ──────────────────────────────────────
DEFAULT_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    ".knowledge_cache",
)
DEFAULT_DB_PATH = os.path.join(DEFAULT_CACHE_DIR, "knowledge.db")


# ═══════════════════════════════════════════════════════════════════════════════
# SQL schema
# ═══════════════════════════════════════════════════════════════════════════════

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_cache (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor          TEXT NOT NULL,
    platform        TEXT DEFAULT '',
    command         TEXT NOT NULL,
    syntax          TEXT DEFAULT '',
    description     TEXT DEFAULT '',
    example_output  TEXT DEFAULT '',
    min_version     TEXT DEFAULT '',
    source_url      TEXT DEFAULT '',
    source_title    TEXT DEFAULT '',
    source_name     TEXT DEFAULT '',
    source_type     TEXT DEFAULT '',
    confidence      TEXT DEFAULT 'unverified',
    fetched_at      TEXT NOT NULL,
    verified_at     TEXT NOT NULL,
    ttl_days        INTEGER DEFAULT 90,
    hit_count       INTEGER DEFAULT 0,
    UNIQUE(vendor, platform, command)
);

CREATE INDEX IF NOT EXISTS idx_kc_vendor_cmd
    ON knowledge_cache(vendor, command);

CREATE INDEX IF NOT EXISTS idx_kc_verified
    ON knowledge_cache(verified_at);
"""


# ═══════════════════════════════════════════════════════════════════════════════
# KnowledgeCacheDB
# ═══════════════════════════════════════════════════════════════════════════════

class KnowledgeCacheDB:
    """
    Thread-safe SQLite cache for vendor knowledge entries.
    Singleton-style — use `get_cache()` helper.
    """

    _instance = None
    _instance_lock = threading.Lock()

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._conn_lock = threading.Lock()
        self._ensure_dir()
        self._init_schema()

    def _ensure_dir(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_schema(self) -> None:
        with self._conn_lock, self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
        logger.info(f"Knowledge cache initialized at {self.db_path}")

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def get(
        self,
        vendor: str,
        command: str,
        platform: str = "",
    ) -> Optional[KnowledgeEntry]:
        """Look up a single entry; returns None on miss."""
        vendor = (vendor or "").lower().strip()
        command = (command or "").strip()
        platform = (platform or "").lower().strip()

        if not vendor or not command:
            return None

        # Try exact platform match first, then any platform for that vendor+command
        with self._conn_lock, self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM knowledge_cache
                   WHERE vendor = ? AND command = ? AND platform = ?""",
                (vendor, command, platform),
            ).fetchone()

            if not row and platform:
                # Fallback: same vendor+command, any platform
                row = conn.execute(
                    """SELECT * FROM knowledge_cache
                       WHERE vendor = ? AND command = ?
                       ORDER BY verified_at DESC LIMIT 1""",
                    (vendor, command),
                ).fetchone()

            if not row:
                return None

            # Bump hit count
            conn.execute(
                "UPDATE knowledge_cache SET hit_count = hit_count + 1 WHERE id = ?",
                (row["id"],),
            )
            conn.commit()

            return self._row_to_entry(row)

    def upsert(self, entry: KnowledgeEntry) -> bool:
        """Insert or update an entry. Returns True if successful."""
        if not entry.vendor or not entry.command:
            return False

        with self._conn_lock, self._connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO knowledge_cache
                       (vendor, platform, command, syntax, description,
                        example_output, min_version, source_url, source_title,
                        source_name, source_type, confidence,
                        fetched_at, verified_at, ttl_days, hit_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(vendor, platform, command) DO UPDATE SET
                         syntax = excluded.syntax,
                         description = excluded.description,
                         example_output = excluded.example_output,
                         min_version = excluded.min_version,
                         source_url = excluded.source_url,
                         source_title = excluded.source_title,
                         source_name = excluded.source_name,
                         source_type = excluded.source_type,
                         confidence = excluded.confidence,
                         verified_at = excluded.verified_at,
                         ttl_days = excluded.ttl_days
                    """,
                    (
                        entry.vendor.lower(),
                        entry.platform.lower() if entry.platform else "",
                        entry.command.strip(),
                        entry.syntax,
                        entry.description,
                        entry.example_output,
                        entry.min_version,
                        entry.citation.source_url or "",
                        entry.citation.source_title or "",
                        entry.citation.source_name,
                        entry.citation.source_type,
                        entry.citation.confidence.value,
                        entry.fetched_at,
                        entry.verified_at,
                        entry.ttl_days,
                        entry.hit_count,
                    ),
                )
                conn.commit()
                return True
            except Exception as exc:
                logger.error(f"Cache upsert failed: {exc}")
                return False

    def delete(self, vendor: str, command: str, platform: str = "") -> bool:
        """Remove a specific entry."""
        with self._conn_lock, self._connect() as conn:
            cur = conn.execute(
                """DELETE FROM knowledge_cache
                   WHERE vendor = ? AND command = ? AND platform = ?""",
                (vendor.lower(), command.strip(), platform.lower()),
            )
            conn.commit()
            return cur.rowcount > 0

    def clear_all(self) -> int:
        """Wipe the cache. Returns row count deleted."""
        with self._conn_lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM knowledge_cache")
            conn.commit()
            return cur.rowcount

    # ── Reporting ─────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Cache stats for admin UI."""
        with self._conn_lock, self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) c FROM knowledge_cache").fetchone()["c"]
            by_vendor = {
                r["vendor"]: r["c"]
                for r in conn.execute(
                    "SELECT vendor, COUNT(*) c FROM knowledge_cache GROUP BY vendor"
                ).fetchall()
            }
            by_confidence = {
                r["confidence"]: r["c"]
                for r in conn.execute(
                    "SELECT confidence, COUNT(*) c FROM knowledge_cache GROUP BY confidence"
                ).fetchall()
            }
            top_hits = [
                {"vendor": r["vendor"], "command": r["command"], "hits": r["hit_count"]}
                for r in conn.execute(
                    """SELECT vendor, command, hit_count FROM knowledge_cache
                       ORDER BY hit_count DESC LIMIT 10"""
                ).fetchall()
            ]
            stale_count = conn.execute(
                """SELECT COUNT(*) c FROM knowledge_cache
                   WHERE julianday('now') - julianday(verified_at) > ttl_days"""
            ).fetchone()["c"]

            return {
                "total_entries": total,
                "by_vendor":     by_vendor,
                "by_confidence": by_confidence,
                "top_hits":      top_hits,
                "stale_count":   stale_count,
                "db_path":       self.db_path,
                "db_size_kb":    round(os.path.getsize(self.db_path) / 1024, 1)
                                 if os.path.exists(self.db_path) else 0,
            }

    def list_entries(self, vendor: Optional[str] = None, limit: int = 100) -> List[KnowledgeEntry]:
        """List cached entries, optionally filtered by vendor."""
        with self._conn_lock, self._connect() as conn:
            if vendor:
                rows = conn.execute(
                    """SELECT * FROM knowledge_cache
                       WHERE vendor = ? ORDER BY verified_at DESC LIMIT ?""",
                    (vendor.lower(), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM knowledge_cache ORDER BY verified_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._row_to_entry(r) for r in rows]

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> KnowledgeEntry:
        try:
            confidence = ConfidenceLevel(row["confidence"])
        except Exception:
            confidence = ConfidenceLevel.UNVERIFIED

        return KnowledgeEntry(
            vendor=row["vendor"],
            platform=row["platform"] or "",
            command=row["command"],
            syntax=row["syntax"] or "",
            description=row["description"] or "",
            example_output=row["example_output"] or "",
            min_version=row["min_version"] or "",
            citation=Citation(
                source_name=row["source_name"] or "",
                source_type=row["source_type"] or "",
                source_url=row["source_url"] or None,
                source_title=row["source_title"] or None,
                vendor=row["vendor"],
                confidence=confidence,
                fetched_at=row["fetched_at"],
            ),
            fetched_at=row["fetched_at"],
            verified_at=row["verified_at"],
            ttl_days=row["ttl_days"] or 90,
            hit_count=row["hit_count"] or 0,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton accessor
# ═══════════════════════════════════════════════════════════════════════════════

def get_cache(db_path: Optional[str] = None) -> KnowledgeCacheDB:
    """Singleton accessor for the cache DB."""
    with KnowledgeCacheDB._instance_lock:
        if KnowledgeCacheDB._instance is None:
            KnowledgeCacheDB._instance = KnowledgeCacheDB(db_path)
        return KnowledgeCacheDB._instance
