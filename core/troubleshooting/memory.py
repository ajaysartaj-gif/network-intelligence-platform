"""
Troubleshooting Engine — memory
===============================
ExecutedCommandsMemory  → never run the same (device, command) twice; reuse output.
SessionMemory           → serialize/restore a whole investigation so it can resume.

These are what stop the "ran the same read-only check 5 times" failure mode: the
Command Planner consults ExecutedCommandsMemory and the Evidence Collector reuses
stored output instead of re-executing.
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

from .models import ExecutedCommand, Session


_MARKER = re.compile(r"^\[(exec|config|rollback|next)\]\s*", re.I)
_ON = re.compile(r"^\(on [^)]+\)\s*", re.I)


def normalize_command(command: str) -> str:
    """Canonical form for dedup: strip tags/'(on X)' prefixes, collapse spaces, lower."""
    c = (command or "").strip()
    c = _MARKER.sub("", c)
    c = _ON.sub("", c)
    c = re.sub(r"\s+", " ", c)
    return c.strip().lower()


class ExecutedCommandsMemory:
    """Keyed by (device_ip, normalized_command)."""

    def __init__(self) -> None:
        self._store: Dict[Tuple[str, str], ExecutedCommand] = {}

    def key(self, device: str, command: str) -> Tuple[str, str]:
        return (device or "", normalize_command(command))

    def has(self, device: str, command: str) -> bool:
        return self.key(device, command) in self._store

    def get(self, device: str, command: str) -> Optional[ExecutedCommand]:
        return self._store.get(self.key(device, command))

    def record(self, device: str, command: str, output: str, purpose: str,
               reused: bool = False) -> ExecutedCommand:
        norm = normalize_command(command)
        ec = ExecutedCommand(device=device, command=command, normalized=norm,
                             purpose=purpose, output=output, reused=reused)
        self._store[(device or "", norm)] = ec
        return ec

    def all_normalized(self) -> set:
        return {k[1] for k in self._store}

    def seen_on(self, device: str) -> set:
        return {k[1] for k in self._store if k[0] == (device or "")}


class SessionMemory:
    """Persist/restore a Session. Backend is pluggable; defaults to in-memory dict.

    A production deployment can pass a `store` object exposing get(key)->str and
    set(key, str) — e.g. the platform MemoryStore — to survive restarts.
    """

    def __init__(self, store: Optional[object] = None) -> None:
        self._mem: Dict[str, str] = {}
        self._store = store

    def _set(self, key: str, val: str) -> None:
        if self._store is not None and hasattr(self._store, "set"):
            self._store.set(key, val)  # type: ignore[attr-defined]
        else:
            self._mem[key] = val

    def _get(self, key: str) -> Optional[str]:
        if self._store is not None and hasattr(self._store, "get"):
            try:
                return self._store.get(key)  # type: ignore[attr-defined]
            except Exception:
                return None
        return self._mem.get(key)

    def save(self, session: Session) -> None:
        self._set(f"ts_session::{session.id}", json.dumps(_session_to_dict(session)))

    def load(self, session_id: str) -> Optional[dict]:
        raw = self._get(f"ts_session::{session_id}")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None


def _session_to_dict(s: Session) -> dict:
    """Best-effort serialization used for resume/audit (not a full ORM)."""
    return {
        "id": s.id,
        "goal": {"query": s.goal.query, "objective": s.goal.objective,
                 "devices": s.goal.devices} if s.goal else None,
        "status": s.status.value,
        "steps_taken": s.steps_taken,
        "hypotheses": [
            {"id": h.id, "statement": h.statement, "state": h.state.value,
             "confidence": h.confidence, "evidence_ids": h.evidence_ids}
            for h in s.hypotheses
        ],
        "observations": [
            {"id": o.id, "device": o.device, "subject": o.subject,
             "attribute": o.attribute, "value": o.value} for o in s.observations
        ],
        "executed": [
            {"device": c.device, "command": c.command, "purpose": c.purpose,
             "reused": c.reused} for c in s.executed
        ],
        "best_confidence_history": s.best_confidence_history,
    }
