"""AI Design Engine — Design Memory (own memory, independent of other engines)."""
from __future__ import annotations

import json
import os
import threading
from typing import Dict, List, Optional

from .models import DesignSession


class JSONFileBackend:
    """Local JSON-file persistence, same pattern as core/device_discovery.py's
    DeviceLogStore — an explicit, opt-in backend so DesignMemory can survive
    across requests/process restarts when the caller wants that (e.g. wire one
    shared instance in copilot_engine.py). NOT the default: a class shouldn't
    silently write files to disk just because no backend argument was passed
    — that surprises every test/caller that never asked for persistence, and
    risks concurrent-write corruption under parallel execution (pytest-xdist)."""

    def __init__(self, path: str = ".netbrain_design_memory.json") -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: Dict[str, str] = self._load()

    def _load(self) -> Dict[str, str]:
        try:
            if os.path.exists(self._path):
                with open(self._path) as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save(self) -> None:
        try:
            with open(self._path, "w") as f:
                json.dump(self._data, f, indent=2, default=str)
        except Exception:
            pass

    def set(self, key: str, value: str) -> None:
        with self._lock:
            self._data[key] = value
            self._save()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            return self._data.get(key)


class _InMemoryBackend:
    def __init__(self) -> None:
        self._data: Dict[str, str] = {}

    def set(self, key: str, value: str) -> None:
        self._data[key] = value

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)


class DesignMemory:
    """Maintains requirements, constraints, generated + rejected designs, decisions,
    lessons and history. Pluggable backend; defaults to a safe in-memory dict —
    pass backend=JSONFileBackend(...) explicitly (e.g. one shared instance in
    copilot_engine.py) for persistence across requests."""

    def __init__(self, backend: Optional[object] = None) -> None:
        self._backend = backend if backend is not None else _InMemoryBackend()

    def save(self, session: DesignSession) -> None:
        payload = json.dumps(_digest(session))
        self._backend.set(f"design_session::{session.id}", payload)

    def load(self, session_id: str) -> Optional[dict]:
        try:
            raw = self._backend.get(f"design_session::{session_id}")
        except Exception:
            raw = None
        return json.loads(raw) if raw else None


def _digest(s: DesignSession) -> dict:
    return {
        "id": s.id,
        "query": s.query,
        "status": s.status.value,
        "requirements": [{"kind": r.kind, "detail": r.detail} for r in s.requirements],
        "constraints": [{"kind": c.kind, "detail": c.detail} for c in s.constraints],
        "options": [{"name": o.name, "score": o.weighted_total, "recommended": o.recommended}
                    for o in s.options],
        "rejected": s.rejected,
        "recommended": (s.recommended().name if s.recommended() else ""),
        "confidence": s.confidence,
        "history": s.history,
    }
