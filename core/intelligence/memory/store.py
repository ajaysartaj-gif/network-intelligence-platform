"""
core/intelligence/memory/store.py
==================================
Shared substrate for every *derived* memory subsystem.

The existing OperationalMemory is the platform's EPISODIC log: it remembers
raw events as they happen. An experienced engineer does not reason from a flat
list of every event they ever saw — they CONSOLIDATE experience into durable,
weighted, decaying higher-order memories (facts, procedures, patterns, scars,
expectations, preferences). Those are what this package adds.

Every derived memory subsystem is a MemoryStore: one durable, reinforceable,
forgetting, optionally-semantic table living in the SAME brain as the episodic
log (the shared SQLite/Postgres backend), so local and cloud instances share
one accumulating mind. The rich per-memory logic lives in the subclasses; the
mechanics every memory needs — durable upsert, reinforcement, recency/decay,
similarity recall, temporal recall, health/metrics — live here once.
"""
from __future__ import annotations

import json
import logging
import math
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("NetBrain.Intelligence.Memory.Store")

# Reuse the episodic memory's backend + cosine so derived memories live in the
# very same store (same DSN / same SQLite file) and share its dialect handling.
try:
    from core.intelligence.operational_memory import _Backend, _DB_PATH, _cosine
except Exception:  # pragma: no cover - extremely defensive
    _Backend = None       # type: ignore
    _DB_PATH = ".netbrain_memory.sqlite"

    def _cosine(a, b):     # type: ignore
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0


# One backend, shared by every derived memory store in the process, so they all
# write into the one brain and we open a single connection.
_SHARED_BE = None


def _backend():
    global _SHARED_BE
    if _SHARED_BE is None:
        if _Backend is None:
            raise RuntimeError("memory backend unavailable")
        import os
        dsn = os.environ.get("NETBRAIN_MEMORY_DSN", "")
        try:
            _SHARED_BE = _Backend(dsn=dsn, sqlite_path=_DB_PATH)
        except Exception as exc:
            logger.warning(f"shared memory backend: Postgres unavailable ({exc}); using SQLite.")
            _SHARED_BE = _Backend(dsn="", sqlite_path=_DB_PATH)
    return _SHARED_BE


def _now() -> float:
    return time.time()


def _embedder():
    try:
        from core.knowledge.rag.embedder import get_embedder
        return get_embedder()
    except Exception:
        return None


class MemoryStore:
    """
    Base class for a single derived-memory table.

    Subclasses declare:
      • table      — the table name (unique per memory type)
      • columns    — extra typed columns beyond the shared spine
      • semantic   — whether rows carry an embedding for similarity recall

    The shared spine every derived memory has:
      id, ts (first learned), updated_ts, key (a stable de-dup signature),
      summary (embedded text), strength (reinforcement count, +decay),
      confidence [0,1], extra (json), embedding (json text).

    'Learning' the same thing again does not append a duplicate — it REINFORCES
    the existing row (strength↑, confidence updated, recency refreshed). That is
    what turns a stream of episodes into a small set of strong, trusted beliefs.
    """
    table: str = "memory_generic"
    columns: Tuple[Tuple[str, str], ...] = ()   # (name, sql_type)
    semantic: bool = True

    # half-life (seconds) for recency weighting in recall; ~120 days default.
    half_life_s: float = 120 * 24 * 3600

    def __init__(self):
        self._be = _backend()
        self._emb = None
        self._emb_tried = False
        self._init_schema()

    # ── schema ───────────────────────────────────────────────────────────────
    def _init_schema(self) -> None:
        ts_type = "DOUBLE PRECISION" if self._be.is_postgres else "REAL"
        cols = [
            "id TEXT PRIMARY KEY",
            f"ts {ts_type}",
            f"updated_ts {ts_type}",
            "k TEXT",
            "summary TEXT",
            f"strength {ts_type}",
            f"confidence {ts_type}",
            "extra TEXT",
            "embedding TEXT",
        ]
        cols += [f"{n} {t}" for n, t in self.columns]
        self._be.execute(f"CREATE TABLE IF NOT EXISTS {self.table} ({', '.join(cols)})")
        self._be.execute(f"CREATE INDEX IF NOT EXISTS idx_{self.table}_k ON {self.table}(k)")
        self._be.execute(f"CREATE INDEX IF NOT EXISTS idx_{self.table}_ts ON {self.table}(updated_ts)")
        for n, _ in self.columns:
            self._be.execute(f"CREATE INDEX IF NOT EXISTS idx_{self.table}_{n} ON {self.table}({n})")
        self._be.commit()

    def _emb_obj(self):
        if not self._emb_tried:
            self._emb_tried = True
            self._emb = _embedder() if self.semantic else None
        return self._emb

    # ── reinforce-or-insert (the core of consolidation) ──────────────────────
    def learn(self, key: str, summary: str, *, confidence: float = 0.6,
              extra: Optional[Dict[str, Any]] = None, **fields) -> str:
        """
        Consolidate one belief. If `key` already exists, reinforce it; else
        insert. Returns the row id. Confidence is blended toward the new value,
        weighted by accumulated strength (older, stronger beliefs move slowly).
        """
        existing = self._by_key(key)
        extra = extra or {}
        if existing:
            new_strength = float(existing.get("strength") or 1.0) + 1.0
            # strength-weighted confidence update: a 50th confirmation barely
            # moves a settled belief; an early one moves it a lot.
            w = 1.0 / new_strength
            blended = (1 - w) * float(existing.get("confidence") or confidence) + w * confidence
            merged_extra = {}
            try:
                merged_extra = json.loads(existing.get("extra") or "{}")
            except Exception:
                merged_extra = {}
            merged_extra.update(extra)
            sets = ["updated_ts=?", "summary=?", "strength=?", "confidence=?", "extra=?"]
            params: List[Any] = [_now(), summary, new_strength, round(blended, 4),
                                  json.dumps(merged_extra)]
            for n, _ in self.columns:
                if n in fields:
                    sets.append(f"{n}=?")
                    params.append(fields[n])
            params.append(existing["id"])
            self._be.execute(
                f"UPDATE {self.table} SET {', '.join(sets)} WHERE id=?", tuple(params))
            self._be.commit()
            return existing["id"]

        rid = uuid.uuid4().hex[:16]
        emb_json = ""
        emb = self._emb_obj()
        if emb:
            try:
                emb_json = json.dumps(emb.embed_one(summary))
            except Exception:
                emb_json = ""
        base_cols = ["id", "ts", "updated_ts", "k", "summary", "strength",
                     "confidence", "extra", "embedding"]
        base_vals: List[Any] = [rid, _now(), _now(), key, summary, 1.0,
                                 round(confidence, 4), json.dumps(extra), emb_json]
        extra_cols = [n for n, _ in self.columns if n in fields]
        all_cols = base_cols + extra_cols
        all_vals = base_vals + [fields[n] for n in extra_cols]
        ph = ", ".join(["?"] * len(all_vals))
        self._be.execute(
            f"INSERT INTO {self.table} ({', '.join(all_cols)}) VALUES ({ph})",
            tuple(all_vals))
        self._be.commit()
        return rid

    def _by_key(self, key: str) -> Optional[Dict[str, Any]]:
        rows = self._be.query(f"SELECT * FROM {self.table} WHERE k=? LIMIT 1", (key,))
        return rows[0] if rows else None

    # ── recall ───────────────────────────────────────────────────────────────
    def _decay(self, row: Dict[str, Any]) -> float:
        """A memory's live weight = confidence · strength-saturation · recency."""
        strength = float(row.get("strength") or 1.0)
        conf = float(row.get("confidence") or 0.5)
        age = max(0.0, _now() - float(row.get("updated_ts") or _now()))
        recency = math.exp(-age / self.half_life_s) if self.half_life_s else 1.0
        sat = strength / (strength + 3.0)          # diminishing returns on repeats
        return conf * (0.4 + 0.6 * sat) * (0.3 + 0.7 * recency)

    def recall_similar(self, query: str, top_k: int = 5,
                       min_weight: float = 0.0, **where) -> List[Dict[str, Any]]:
        emb = self._emb_obj()
        rows = self._where(**where)
        if emb:
            try:
                qv = emb.embed_one(query)
            except Exception:
                qv = None
        else:
            qv = None
        scored = []
        ql = (query or "").lower()
        for r in rows:
            if qv is not None and r.get("embedding"):
                try:
                    sim = _cosine(qv, json.loads(r["embedding"]))
                except Exception:
                    sim = 0.0
            else:
                # lexical fallback so recall still works with no embedder
                sim = 1.0 if ql and ql in (r.get("summary") or "").lower() else 0.0
            w = self._decay(r) * (0.5 + 0.5 * sim)
            if w >= min_weight:
                d = self._clean(r)
                d["relevance"] = round(sim, 4)
                d["weight"] = round(w, 4)
                scored.append(d)
        scored.sort(key=lambda x: x["weight"], reverse=True)
        return scored[:top_k]

    def _where(self, **where) -> List[Dict[str, Any]]:
        sql = f"SELECT * FROM {self.table}"
        clauses, params = [], []
        for col, val in where.items():
            if val is None:
                continue
            clauses.append(f"{col}=?")
            params.append(val)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return self._be.query(sql, tuple(params))

    def top(self, limit: int = 20, **where) -> List[Dict[str, Any]]:
        rows = [self._clean(r) | {"weight": round(self._decay(r), 4)}
                for r in self._where(**where)]
        rows.sort(key=lambda x: x["weight"], reverse=True)
        return rows[:limit]

    def recent(self, limit: int = 20, **where) -> List[Dict[str, Any]]:
        rows = self._where(**where)
        rows.sort(key=lambda r: float(r.get("updated_ts") or 0), reverse=True)
        return [self._clean(r) for r in rows[:limit]]

    @staticmethod
    def _clean(r: Dict[str, Any]) -> Dict[str, Any]:
        d = dict(r)
        d.pop("embedding", None)
        try:
            d["extra"] = json.loads(d.get("extra") or "{}")
        except Exception:
            d["extra"] = {}
        return d

    # ── housekeeping ─────────────────────────────────────────────────────────
    def reinforce(self, key: str, by: float = 1.0,
                  confidence: Optional[float] = None) -> None:
        ex = self._by_key(key)
        if not ex:
            return
        strength = float(ex.get("strength") or 1.0) + by
        conf = ex.get("confidence")
        if confidence is not None:
            w = 1.0 / strength
            conf = (1 - w) * float(ex.get("confidence") or confidence) + w * confidence
        self._be.execute(
            f"UPDATE {self.table} SET strength=?, confidence=?, updated_ts=? WHERE id=?",
            (strength, round(float(conf), 4), _now(), ex["id"]))
        self._be.commit()

    def count(self, **where) -> int:
        return len(self._where(**where))

    def health(self) -> Dict[str, Any]:
        n = self.count()
        return {"status": "active" if n else "partial",
                "detail": f"{n} consolidated memories" if n else "ready; nothing consolidated yet",
                "count": n}

    def metrics(self) -> Dict[str, Any]:
        rows = self._be.query(
            f"SELECT COUNT(*) c, AVG(confidence) ac, MAX(strength) ms FROM {self.table}")
        r = rows[0] if rows else {}
        return {"count": r.get("c", 0),
                "avg_confidence": round(float(r.get("ac") or 0), 3),
                "max_strength": float(r.get("ms") or 0),
                "semantic": bool(self._emb_obj())}
