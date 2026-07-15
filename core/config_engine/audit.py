"""AI Configuration Engine — audit trail & session persistence."""
from __future__ import annotations

import json
import os
import threading
from typing import Dict, List, Optional

from .models import ConfigSession


class JSONFileBackend:
    """Local JSON-file persistence, same pattern as core/device_discovery.py's
    DeviceLogStore. Kept self-contained here (not shared with design_engine's
    own JSONFileBackend) per this codebase's "own memory, independent of other
    engines" principle. An explicit, opt-in backend — wire one shared instance
    in copilot_engine.py for the audit trail (spec items 22/23) to actually
    persist. NOT the default: a class shouldn't silently write files to disk
    just because no backend argument was passed."""

    def __init__(self, path: str = ".netbrain_config_sessions.json") -> None:
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


class SessionStore:
    """Pluggable persistence for full config sessions (resume + audit).
    Defaults to a safe in-memory dict — pass backend=JSONFileBackend(...)
    explicitly (e.g. one shared instance in copilot_engine.py) to persist
    across requests."""

    def __init__(self, backend: Optional[object] = None) -> None:
        self._backend = backend if backend is not None else _InMemoryBackend()

    def save(self, session: ConfigSession) -> None:
        payload = json.dumps(_session_digest(session))
        self._backend.set(f"cfg_session::{session.id}", payload)

    def load(self, session_id: str) -> Optional[dict]:
        try:
            raw = self._backend.get(f"cfg_session::{session_id}")
        except Exception:
            raw = None
        return json.loads(raw) if raw else None

    def audit_log(self, session: ConfigSession) -> List[dict]:
        return [{"step": a.step, "detail": a.detail, "at": a.at} for a in session.audit]


def _session_digest(s: ConfigSession) -> dict:
    return {
        "id": s.id,
        "goal": s.goal.objective if s.goal else "",
        "status": s.status.value,
        "intents": [{"name": i.name, "params": i.params, "devices": i.target_devices}
                    for i in s.intents],
        "risk": (s.risk.level.value if s.risk else None),
        "approvals": (s.approval.approved if s.approval else False),
        "audit": [{"step": a.step, "detail": a.detail, "at": a.at} for a in s.audit],
    }
