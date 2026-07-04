"""AI Configuration Engine — audit trail & session persistence."""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from .models import ConfigSession


class SessionStore:
    """Pluggable persistence for full config sessions (resume + audit)."""

    def __init__(self, backend: Optional[object] = None) -> None:
        self._mem: Dict[str, str] = {}
        self._backend = backend

    def save(self, session: ConfigSession) -> None:
        payload = json.dumps(_session_digest(session))
        if self._backend is not None and hasattr(self._backend, "set"):
            self._backend.set(f"cfg_session::{session.id}", payload)
        else:
            self._mem[session.id] = payload

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
