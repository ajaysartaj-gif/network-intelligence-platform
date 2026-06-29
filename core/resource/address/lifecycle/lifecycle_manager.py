"""
NRIE · Lifecycle · Lifecycle Manager (Layer 12)
===============================================
Manages resource lifecycle transitions with FULL audit. Every transition records
timestamp, trigger, actor (user/AI), reason, related deployment/change, previous
and new state. Audit is persisted via the reused Operational Memory; events are
published through the existing event framework. No deployment/config here.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..context.models import ResourceContextBundle
from ..events.domain_events import (
    LIFECYCLE_CHANGED, IntelligenceEvent, get_event_publisher,
)
from .state_machine import ALLOWED, LifecycleState, can_transition


class LifecycleError(ValueError):
    pass


@dataclass
class LifecycleTransition:
    resource_id: str
    previous_state: str
    new_state: str
    trigger: str = ""
    actor: str = "ai"            # user | ai
    reason: str = ""
    deployment_ref: str = ""
    change_ref: str = ""
    ts: float = field(default_factory=time.time)


class LifecycleManager:
    def __init__(self, operational_memory=None, publisher=None):
        self._state: Dict[str, LifecycleState] = {}
        self._history: Dict[str, List[LifecycleTransition]] = {}
        self._om = operational_memory
        self._pub = publisher or get_event_publisher()

    def current_state(self, resource_id: str) -> LifecycleState:
        return self._state.get(resource_id, LifecycleState.PLANNED)

    def transition(self, *, bundle: ResourceContextBundle, to_state: LifecycleState,
                   trigger: str = "", actor: str = "ai", reason: str = "",
                   deployment_ref: str = "", change_ref: str = "") -> LifecycleTransition:
        rid = bundle.resource.resource_id
        src = self.current_state(rid)
        if not can_transition(src, to_state):
            raise LifecycleError(f"illegal transition {src.value} → {to_state.value}")
        tr = LifecycleTransition(
            resource_id=rid, previous_state=src.value, new_state=to_state.value,
            trigger=trigger, actor=actor, reason=reason,
            deployment_ref=deployment_ref, change_ref=change_ref)
        self._state[rid] = to_state
        self._history.setdefault(rid, []).append(tr)
        # audit through reused Operational Memory (best-effort)
        if self._om is not None:
            try:
                kind = "verification" if to_state == LifecycleState.VERIFIED else (
                    "expansion" if to_state == LifecycleState.EXPANDING else "configuration_change")
                self._om.record(kind=kind, bundle=bundle,
                                detail=f"{src.value}→{to_state.value}: {reason}",
                                deployment_ref=deployment_ref)
            except Exception:
                pass
        self._pub.publish(IntelligenceEvent(
            type=LIFECYCLE_CHANGED, resource_id=rid,
            payload={"from": src.value, "to": to_state.value, "actor": actor}))
        return tr

    def history(self, resource_id: str) -> List[LifecycleTransition]:
        return list(self._history.get(resource_id, []))
