"""
NRIE · Memory · Operational Memory (Layer 5)
============================================
Operational history per resource → a complete timeline. REUSES the MemoryStore
base. This is the NRIE *resource* operational history (allocation/reservation/
capacity/…); it is a distinct bounded context from the platform's autonomy
operational memory and does not duplicate it. Context is taken from the bundle.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.intelligence.memory.store import MemoryStore
from ..context.models import ResourceContextBundle
from ..events.domain_events import (
    OPERATIONAL_HISTORY_UPDATED, IntelligenceEvent, get_event_publisher,
)

OPERATIONAL_KINDS = (
    "allocation", "reservation", "capacity_change", "expansion", "shrinking",
    "migration", "rollback", "configuration_change", "verification",
    "deployment_ref", "incident_ref",
)


@dataclass
class OperationalEvent:
    event_id: str
    resource_id: str
    kind: str
    detail: str = ""
    deployment_ref: str = ""
    incident_ref: str = ""
    enterprise_context: Dict[str, Any] = field(default_factory=dict)  # FROM bundle
    ts: float = field(default_factory=time.time)


class _OperationalStore(MemoryStore):
    table = "nrie_operational_memory"
    semantic = False
    columns = (("resource_id", "TEXT"), ("kind", "TEXT"))


class OperationalMemory:
    def __init__(self, store: Optional[_OperationalStore] = None, publisher=None):
        self._s = store or _OperationalStore()
        self._pub = publisher or get_event_publisher()

    def record(self, *, kind: str, bundle: ResourceContextBundle, detail: str = "",
               deployment_ref: str = "", incident_ref: str = "") -> OperationalEvent:
        if kind not in OPERATIONAL_KINDS:
            raise ValueError(f"unknown operational kind: {kind}")
        ev = OperationalEvent(
            event_id="op-" + uuid.uuid4().hex[:12], resource_id=bundle.resource.resource_id,
            kind=kind, detail=detail, deployment_ref=deployment_ref,
            incident_ref=incident_ref, enterprise_context=bundle.enterprise.__dict__)
        self._s.learn(ev.event_id, f"{kind}:{detail[:40]}", extra={"record": ev.__dict__},
                      resource_id=ev.resource_id, kind=kind)
        self._pub.publish(IntelligenceEvent(
            type=OPERATIONAL_HISTORY_UPDATED, resource_id=ev.resource_id,
            payload={"event_id": ev.event_id, "kind": kind}))
        return ev

    def timeline(self, resource_id: str) -> List[OperationalEvent]:
        rows = self._s._be.query(
            f"SELECT * FROM {self._s.table} WHERE resource_id=?", (resource_id,))
        evs = [_to_op(r) for r in rows]
        return sorted(evs, key=lambda e: e.ts)

    def by_kind(self, kind: str) -> List[OperationalEvent]:
        return [_to_op(r) for r in self._s._be.query(
            f"SELECT * FROM {self._s.table} WHERE kind=?", (kind,))]


def _to_op(row: Dict[str, Any]) -> OperationalEvent:
    rec = json.loads(row.get("extra") or "{}").get("record", {})
    return OperationalEvent(**rec) if rec else OperationalEvent(
        event_id=row.get("k", ""), resource_id=row.get("resource_id", ""),
        kind=row.get("kind", ""))
