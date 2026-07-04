"""AI Design Engine — Design Memory (own memory, independent of other engines)."""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from .models import DesignSession


class DesignMemory:
    """Maintains requirements, constraints, generated + rejected designs, decisions,
    lessons and history. Pluggable backend; defaults to in-memory."""

    def __init__(self, backend: Optional[object] = None) -> None:
        self._mem: Dict[str, str] = {}
        self._backend = backend

    def save(self, session: DesignSession) -> None:
        payload = json.dumps(_digest(session))
        if self._backend is not None and hasattr(self._backend, "set"):
            self._backend.set(f"design_session::{session.id}", payload)
        else:
            self._mem[session.id] = payload

    def load(self, session_id: str) -> Optional[dict]:
        if self._backend is not None and hasattr(self._backend, "get"):
            try:
                raw = self._backend.get(f"design_session::{session_id}")
            except Exception:
                raw = None
        else:
            raw = self._mem.get(session_id)
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
