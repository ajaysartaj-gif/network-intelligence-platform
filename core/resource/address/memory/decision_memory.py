"""
NRIE · Memory · Decision Memory (Layer 4)
=========================================
Persistent engineering-decision record, queryable. REUSES the platform Memory
Platform base (MemoryStore, dual-backend). Enterprise context is taken from the
supplied ResourceContextBundle — this layer NEVER reconstructs context.
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
    DECISION_RECORDED, IntelligenceEvent, get_event_publisher,
)


@dataclass
class DecisionRecord:
    decision_id: str
    decision_type: str
    resource_id: str = ""
    business_intent_ref: str = ""
    enterprise_context: Dict[str, Any] = field(default_factory=dict)  # FROM bundle
    alternatives_considered: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    evidence_used: List[str] = field(default_factory=list)
    reasoning_summary: str = ""
    confidence_score: float = 0.0
    final_decision: str = ""
    user_override: str = ""
    outcome_status: str = "pending"      # pending|succeeded|failed|reverted
    ts: float = field(default_factory=time.time)


class _DecisionStore(MemoryStore):
    table = "nrie_decision_memory"
    semantic = False
    columns = (("resource_id", "TEXT"), ("decision_type", "TEXT"), ("outcome", "TEXT"))


class DecisionMemory:
    def __init__(self, store: Optional[_DecisionStore] = None, publisher=None):
        self._s = store or _DecisionStore()
        self._pub = publisher or get_event_publisher()

    def record(self, *, decision_type: str, bundle: ResourceContextBundle,
               business_intent_ref: str = "", alternatives: Optional[List[str]] = None,
               constraints: Optional[List[str]] = None, evidence: Optional[List[str]] = None,
               reasoning_summary: str = "", confidence: float = 0.0,
               final_decision: str = "", user_override: str = "",
               outcome_status: str = "pending") -> DecisionRecord:
        rec = DecisionRecord(
            decision_id="dec-" + uuid.uuid4().hex[:12], decision_type=decision_type,
            resource_id=bundle.resource.resource_id,
            business_intent_ref=business_intent_ref,
            enterprise_context=bundle.enterprise.__dict__,   # context comes from the bundle
            alternatives_considered=alternatives or [], constraints=constraints or [],
            evidence_used=evidence or [], reasoning_summary=reasoning_summary,
            confidence_score=confidence, final_decision=final_decision,
            user_override=user_override, outcome_status=outcome_status)
        self._s.learn(rec.decision_id, f"{decision_type}:{rec.final_decision}",
                      confidence=confidence, extra={"record": rec.__dict__},
                      resource_id=rec.resource_id, decision_type=decision_type,
                      outcome=outcome_status)
        self._pub.publish(IntelligenceEvent(
            type=DECISION_RECORDED, resource_id=rec.resource_id,
            payload={"decision_id": rec.decision_id, "decision_type": decision_type}))
        return rec

    def set_outcome(self, decision_id: str, outcome_status: str) -> None:
        self._s.learn(decision_id, decision_id, outcome=outcome_status)

    # ── queries (read-only) ──────────────────────────────────────────────────
    def get(self, decision_id: str) -> Optional[DecisionRecord]:
        row = self._s._by_key(decision_id)
        return _to_decision(row) if row else None

    def by_resource(self, resource_id: str) -> List[DecisionRecord]:
        return [_to_decision(r) for r in self._s._be.query(
            f"SELECT * FROM {self._s.table} WHERE resource_id=?", (resource_id,))]

    def by_type(self, decision_type: str) -> List[DecisionRecord]:
        return [_to_decision(r) for r in self._s._be.query(
            f"SELECT * FROM {self._s.table} WHERE decision_type=?", (decision_type,))]

    def all(self) -> List[DecisionRecord]:
        return [_to_decision(r) for r in self._s._be.query(f"SELECT * FROM {self._s.table}")]


def _to_decision(row: Dict[str, Any]) -> DecisionRecord:
    rec = json.loads(row.get("extra") or "{}").get("record", {})
    return DecisionRecord(**rec) if rec else DecisionRecord(
        decision_id=row.get("k", ""), decision_type=row.get("decision_type", ""))
