"""
core/intelligence/operational_memory.py
========================================
Enterprise Operational Memory — a standalone, persistent memory service.

The platform stops forgetting. Every operationally significant event
(incident, root cause, remediation, deployment outcome, operator decision,
rollback, verification result, recurring failure) is written to a durable
store and becomes searchable — so the system accumulates experience instead
of relearning every time.

Design decisions (as architect):
  • STANDALONE service with its OWN persistent store (SQLite at
    .netbrain_memory.sqlite) — independent of RAG/Chroma, so memory is a
    first-class subsystem, not a tenant of the knowledge store.
  • REUSES the existing Embedder (no new embedding infra) for similarity
    search. Vectors are stored alongside structured columns.
  • DUAL-INDEXED: structured columns (device, interface, site, protocol,
    event_type, timestamp) power temporal + dimensional history queries;
    an embedding column powers similarity search. One store, many lenses.
  • AUTO-WRITE: workflows call record_from_contract() after verification, so
    memory is written automatically, not manually.
  • Continuous accumulation: append-only; recurring-failure detection emerges
    from querying repeated signatures.

Integrates with the Capability Registry via bind_memory_capability().
"""
from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("NetBrain.Intelligence.Memory")

_DB_PATH = os.environ.get("NETBRAIN_MEMORY_DB", ".netbrain_memory.sqlite")


class EventType(str, Enum):
    INCIDENT = "incident"
    ROOT_CAUSE = "root_cause"
    REMEDIATION = "remediation"
    DEPLOYMENT = "deployment_outcome"
    DECISION = "operator_decision"
    ROLLBACK = "rollback"
    VERIFICATION = "verification_result"
    RECURRING_FAILURE = "recurring_failure"


@dataclass
class MemoryEvent:
    """One operationally significant, remembered event."""
    event_type: str
    summary: str                       # short human description (also embedded)
    detail: str = ""                   # full text (commands, evidence, reasoning)
    device: str = ""                   # ip or hostname
    interface: str = ""
    site: str = ""
    protocol: str = ""                 # ospf, bgp, interface, ...
    outcome: str = ""                  # success | failure | partial | n/a
    signature: str = ""                # stable key for recurrence detection
    intent: str = ""
    operator: str = ""
    related_ids: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)
    # filled by the store:
    id: str = ""
    ts: float = 0.0


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class _Backend:
    """
    Storage backend abstraction. The rich memory LOGIC lives once in
    OperationalMemory; only raw SQL execution differs between SQLite (local)
    and Postgres (shared cloud brain). This class normalizes the two real
    differences: the parameter placeholder ('?' vs '%s') and the upsert
    clause. Pick Postgres by setting a connection string; otherwise SQLite.
    """
    def __init__(self, dsn: str = "", sqlite_path: str = _DB_PATH):
        self.is_postgres = bool(dsn)
        if self.is_postgres:
            import psycopg2
            import psycopg2.extras
            self._pg = psycopg2
            self._extras = psycopg2.extras
            self._conn = psycopg2.connect(dsn)
            self._conn.autocommit = True
            self.ph = "%s"                       # Postgres placeholder
        else:
            self._conn = sqlite3.connect(sqlite_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self.ph = "?"                        # SQLite placeholder

    def kind(self) -> str:
        return "postgres" if self.is_postgres else "sqlite"

    def execute(self, sql: str, params: tuple = ()):  # returns cursor
        # callers write SQL with '?' placeholders; translate for Postgres.
        if self.is_postgres:
            sql = sql.replace("?", "%s")
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def query(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        if self.is_postgres:
            sql = sql.replace("?", "%s")
            cur = self._conn.cursor(cursor_factory=self._extras.RealDictCursor)
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
        cur = self._conn.cursor()
        cur.execute(sql, params)
        cols = [c[0] for c in cur.description] if cur.description else []
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def upsert_event_sql(self) -> str:
        """INSERT-or-replace, dialect-correct, same column order both ways."""
        cols = ("id, ts, event_type, summary, detail, device, interface, site, "
                "protocol, outcome, signature, intent, operator, related_ids, "
                "extra, embedding")
        ph = ", ".join(["?"] * 16)
        if self.is_postgres:
            return (f"INSERT INTO memory_events ({cols}) VALUES ({ph}) "
                    f"ON CONFLICT (id) DO UPDATE SET "
                    + ", ".join(f"{c}=EXCLUDED.{c}" for c in cols.replace(" ", "").split(",") if c != "id"))
        return f"INSERT OR REPLACE INTO memory_events ({cols}) VALUES ({ph})"

    def commit(self):
        if not self.is_postgres:
            self._conn.commit()


class OperationalMemory:
    """Persistent, searchable operational memory service.

    Backend is chosen automatically: if a Postgres connection string is
    configured (NETBRAIN_MEMORY_DSN env, or memory_dsn in secrets bridged to
    that env), ALL instances share ONE cloud brain in real time — true
    Continuous Learning across machines. Otherwise it uses a local SQLite
    file. Identical method surface either way.
    """

    def __init__(self, db_path: str = _DB_PATH, embedder: Optional[Any] = None,
                 dsn: str = ""):
        self.db_path = db_path
        self._embedder = embedder            # lazy; reuse RAG embedder
        dsn = dsn or os.environ.get("NETBRAIN_MEMORY_DSN", "")
        try:
            self._be = _Backend(dsn=dsn, sqlite_path=db_path)
        except Exception as exc:
            logger.warning(f"Postgres unavailable ({exc}); falling back to local SQLite.")
            self._be = _Backend(dsn="", sqlite_path=db_path)
        self._init_schema()

    # ── schema ───────────────────────────────────────────────────────────────
    def _init_schema(self):
        # 'ts double precision' works on both; TEXT/REAL map cleanly.
        ts_type = "DOUBLE PRECISION" if self._be.is_postgres else "REAL"
        self._be.execute(f"""
            CREATE TABLE IF NOT EXISTS memory_events (
                id TEXT PRIMARY KEY,
                ts {ts_type} NOT NULL,
                event_type TEXT,
                summary TEXT,
                detail TEXT,
                device TEXT,
                interface TEXT,
                site TEXT,
                protocol TEXT,
                outcome TEXT,
                signature TEXT,
                intent TEXT,
                operator TEXT,
                related_ids TEXT,
                extra TEXT,
                embedding TEXT
            )
        """)
        for col in ("ts", "device", "site", "protocol", "interface",
                    "event_type", "signature"):
            self._be.execute(
                f"CREATE INDEX IF NOT EXISTS idx_mem_{col} ON memory_events({col})")
        self._be.commit()

    def _embedder_obj(self):
        if self._embedder is None:
            try:
                from core.knowledge.rag.embedder import get_embedder
                self._embedder = get_embedder()
            except Exception as exc:
                logger.warning(f"embedder unavailable, similarity disabled: {exc}")
                self._embedder = False
        return self._embedder or None

    # ── write ────────────────────────────────────────────────────────────────
    def record(self, event: MemoryEvent) -> str:
        event.id = event.id or uuid.uuid4().hex[:16]
        event.ts = event.ts or time.time()
        emb_json = ""
        emb = self._embedder_obj()
        if emb:
            try:
                vec = emb.embed_one(f"{event.summary}\n{event.detail[:1000]}")
                emb_json = json.dumps(vec)
            except Exception as exc:
                logger.debug(f"embed failed: {exc}")
        self._be.execute(self._be.upsert_event_sql(), (
            event.id, event.ts, event.event_type, event.summary, event.detail,
            (event.device or "").lower(), (event.interface or "").lower(),
            (event.site or "").lower(), (event.protocol or "").lower(),
            event.outcome, event.signature, event.intent, event.operator,
            json.dumps(event.related_ids), json.dumps(event.extra), emb_json,
        ))
        self._be.commit()
        return event.id

    # ── AUTO-WRITE from a verified outcome contract ──────────────────────────
    def record_from_contract(
        self, contract: Any, *, site: str = "", protocol: str = "",
        interface: str = "", operator: str = "",
        commands: Optional[List[str]] = None,
    ) -> List[str]:
        """
        The hook every workflow calls AFTER verification. Turns a
        ContractResult into durable memory: a deployment-outcome event, plus a
        remediation event if it succeeded, plus a recurring-failure event if it
        didn't (and the same signature has failed before).
        """
        ids: List[str] = []
        intent = getattr(contract, "intent", "") or ""
        device = getattr(contract, "device", "") or ""
        satisfied = bool(getattr(contract, "satisfied", False))
        conditions = getattr(contract, "conditions", []) or []
        cond_text = "\n".join(
            f"- {getattr(c,'description','')}: {getattr(getattr(c,'verdict',None),'value',c.__dict__.get('verdict',''))} "
            f"({getattr(c,'reason','')})" for c in conditions
        )
        signature = _signature(intent, protocol, [
            getattr(c, "description", "") for c in conditions
            if getattr(getattr(c, "verdict", None), "value", "") == "fail"
        ])

        # 1) deployment outcome (always)
        ids.append(self.record(MemoryEvent(
            event_type=EventType.DEPLOYMENT.value,
            summary=f"{'✅' if satisfied else '⚠️'} {intent} on {device}",
            detail=(("Commands:\n" + "\n".join(commands) + "\n\n") if commands else "")
                   + "Post-conditions:\n" + cond_text,
            device=device, interface=interface, site=site, protocol=protocol,
            outcome="success" if satisfied else "failure",
            signature=signature, intent=intent, operator=operator,
        )))

        # 2) verification result (the proof itself)
        ids.append(self.record(MemoryEvent(
            event_type=EventType.VERIFICATION.value,
            summary=f"Verification {'passed' if satisfied else 'failed'}: {intent} on {device}",
            detail=cond_text, device=device, interface=interface, site=site,
            protocol=protocol, outcome="success" if satisfied else "failure",
            signature=signature, intent=intent, operator=operator,
            related_ids=[ids[0]],
        )))

        if satisfied:
            # 3) successful remediation — reusable experience
            ids.append(self.record(MemoryEvent(
                event_type=EventType.REMEDIATION.value,
                summary=f"Known-good: {intent} on {device}",
                detail=(("Commands:\n" + "\n".join(commands)) if commands else intent),
                device=device, interface=interface, site=site, protocol=protocol,
                outcome="success", signature=signature, intent=intent,
                operator=operator, related_ids=[ids[0]],
            )))
        else:
            # 3) recurring-failure detection: has this signature failed before?
            priors = self.by_signature(signature, outcome="failure", limit=5)
            if priors:
                ids.append(self.record(MemoryEvent(
                    event_type=EventType.RECURRING_FAILURE.value,
                    summary=f"⚠️ RECURRING failure ({len(priors)+1}x): {intent} on {device}",
                    detail=f"Signature '{signature}' has failed {len(priors)} time(s) before.\n"
                           f"Latest conditions:\n{cond_text}",
                    device=device, interface=interface, site=site, protocol=protocol,
                    outcome="failure", signature=signature, intent=intent,
                    operator=operator, related_ids=[p["id"] for p in priors] + [ids[0]],
                )))
        return ids

    # convenience writers for the other event types
    def record_decision(self, summary, detail="", device="", site="", operator="",
                        intent="") -> str:
        return self.record(MemoryEvent(
            event_type=EventType.DECISION.value, summary=summary, detail=detail,
            device=device, site=site, operator=operator, intent=intent))

    def record_rollback(self, summary, detail="", device="", site="", protocol="",
                       operator="", related_ids=None) -> str:
        return self.record(MemoryEvent(
            event_type=EventType.ROLLBACK.value, summary=summary, detail=detail,
            device=device, site=site, protocol=protocol, operator=operator,
            outcome="n/a", related_ids=related_ids or []))

    def record_root_cause(self, summary, detail="", device="", site="", protocol="",
                         signature="", related_ids=None) -> str:
        return self.record(MemoryEvent(
            event_type=EventType.ROOT_CAUSE.value, summary=summary, detail=detail,
            device=device, site=site, protocol=protocol, signature=signature,
            related_ids=related_ids or []))

    # ── search: similarity ───────────────────────────────────────────────────
    def similar(self, query: str, top_k: int = 5,
                event_type: Optional[str] = None,
                min_score: float = 0.0) -> List[Dict[str, Any]]:
        """Semantic similarity over remembered events (reuses the embedder)."""
        emb = self._embedder_obj()
        if not emb:
            return []
        try:
            qv = emb.embed_one(query)
        except Exception:
            return []
        sql = "SELECT * FROM memory_events WHERE embedding != ''"
        params: List[Any] = []
        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        rows = self._be.query(sql, tuple(params))
        scored = []
        for r in rows:
            try:
                vec = json.loads(r["embedding"])
            except Exception:
                continue
            s = _cosine(qv, vec)
            if s >= min_score:
                d = _row_to_dict(r)
                d["score"] = round(s, 4)
                scored.append(d)
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    # ── search: temporal ─────────────────────────────────────────────────────
    def temporal(self, since: Optional[float] = None, until: Optional[float] = None,
                 event_type: Optional[str] = None, limit: int = 50,
                 newest_first: bool = True) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM memory_events WHERE 1=1"
        params: List[Any] = []
        if since is not None:
            sql += " AND ts >= ?"; params.append(since)
        if until is not None:
            sql += " AND ts <= ?"; params.append(until)
        if event_type:
            sql += " AND event_type = ?"; params.append(event_type)
        sql += f" ORDER BY ts {'DESC' if newest_first else 'ASC'} LIMIT ?"
        params.append(limit)
        return [_row_to_dict(r) for r in self._be.query(sql, tuple(params))]

    # ── search: dimensional history ──────────────────────────────────────────
    def _history(self, column: str, value: str, limit: int,
                 event_type: Optional[str]) -> List[Dict[str, Any]]:
        sql = f"SELECT * FROM memory_events WHERE {column} = ?"
        params: List[Any] = [(value or "").lower()]
        if event_type:
            sql += " AND event_type = ?"; params.append(event_type)
        sql += " ORDER BY ts DESC LIMIT ?"; params.append(limit)
        return [_row_to_dict(r) for r in self._be.query(sql, tuple(params))]

    def device_history(self, device, limit=50, event_type=None):
        return self._history("device", device, limit, event_type)

    def interface_history(self, interface, limit=50, event_type=None):
        return self._history("interface", interface, limit, event_type)

    def site_history(self, site, limit=50, event_type=None):
        return self._history("site", site, limit, event_type)

    def protocol_history(self, protocol, limit=50, event_type=None):
        return self._history("protocol", protocol, limit, event_type)

    def by_signature(self, signature, outcome=None, limit=10) -> List[Dict[str, Any]]:
        if not signature:
            return []
        sql = "SELECT * FROM memory_events WHERE signature = ?"
        params: List[Any] = [signature]
        if outcome:
            sql += " AND outcome = ?"; params.append(outcome)
        sql += " ORDER BY ts DESC LIMIT ?"; params.append(limit)
        return [_row_to_dict(r) for r in self._be.query(sql, tuple(params))]

    def recurring_failures(self, min_count: int = 2, limit: int = 20) -> List[Dict[str, Any]]:
        """Signatures that have failed >= min_count times — the patterns worth fixing."""
        rows = self._be.query("""
            SELECT signature, COUNT(*) c, MAX(ts) last_ts,
                   MAX(intent) intent, MAX(protocol) protocol
            FROM memory_events
            WHERE outcome='failure' AND signature != ''
            GROUP BY signature HAVING c >= ?
            ORDER BY c DESC, last_ts DESC LIMIT ?
        """, (min_count, limit))
        return [{"signature": r["signature"], "count": r["c"],
                 "last_ts": r["last_ts"], "intent": r["intent"],
                 "protocol": r["protocol"]} for r in rows]

    # ── capability-registry surface ──────────────────────────────────────────
    def health(self) -> Dict[str, Any]:
        n = self.count()
        return {"status": "active" if n > 0 else "partial",
                "detail": f"{n} operational events remembered" if n
                          else "Memory service ready; no events yet",
                "events": n}

    def metrics(self) -> Dict[str, Any]:
        by_type = {r["event_type"]: r["c"] for r in self._be.query(
            "SELECT event_type, COUNT(*) c FROM memory_events GROUP BY event_type")}
        span = self._be.query(
            "SELECT MIN(ts) a, MAX(ts) b FROM memory_events")[0]
        return {
            "total_events": self.count(),
            "by_type": by_type,
            "recurring_failure_signatures": len(self.recurring_failures(min_count=2, limit=1000)),
            "oldest_ts": span["a"], "newest_ts": span["b"],
            "embedding_enabled": bool(self._embedder_obj()),
        }

    def count(self) -> int:
        return self._be.query("SELECT COUNT(*) c FROM memory_events")[0]["c"]


def _signature(intent: str, protocol: str, failed_conditions: List[str]) -> str:
    """Stable recurrence key: protocol + normalized intent + failed-condition set."""
    import hashlib, re
    norm_intent = re.sub(r"\d+", "#", (intent or "").lower())
    fc = "|".join(sorted(c.lower() for c in failed_conditions))
    raw = f"{(protocol or '').lower()}::{norm_intent}::{fc}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _row_to_dict(r: sqlite3.Row) -> Dict[str, Any]:
    d = dict(r)
    d.pop("embedding", None)
    for k in ("related_ids", "extra"):
        try:
            d[k] = json.loads(d.get(k) or ("[]" if k == "related_ids" else "{}"))
        except Exception:
            pass
    return d


# ── singleton + registry binding ────────────────────────────────────────────
_memory: Optional[OperationalMemory] = None


def get_operational_memory() -> OperationalMemory:
    global _memory
    if _memory is None:
        _memory = OperationalMemory()
    return _memory


def bind_memory_capability() -> None:
    """Plug Operational Memory into the Capability Registry's 'memory' pillar."""
    try:
        from core.intelligence.capability_model import (
            get_capability_registry, CapabilityHealth, CapabilityStatus)
    except Exception:
        return

    def _probe():
        try:
            m = get_operational_memory()
            h = m.health()
            status = (CapabilityStatus.ACTIVE if h["status"] == "active"
                      else CapabilityStatus.PARTIAL)
            return CapabilityHealth(status, h["detail"], metrics=m.metrics())
        except Exception as exc:
            return CapabilityHealth(CapabilityStatus.PARTIAL, f"memory: {exc}")

    get_capability_registry().bind_probe("memory", _probe)
