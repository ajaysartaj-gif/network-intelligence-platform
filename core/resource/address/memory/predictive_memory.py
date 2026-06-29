"""
NRIE · Memory · Predictive Memory (Layer 6)
===========================================
Stores predictions and their realized outcomes — the learning data for future AI
(no prediction MODEL is implemented here; this is storage + accuracy bookkeeping).
REUSES the MemoryStore base. Context is taken from the bundle.
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
    PREDICTION_GENERATED, IntelligenceEvent, get_event_publisher,
)

PREDICTION_KINDS = (
    "capacity", "pool_exhaustion", "growth_forecast",
    "optimization_suggestion", "route_aggregation",
)


@dataclass
class PredictionRecord:
    prediction_id: str
    resource_id: str
    kind: str
    predicted_value: Any = None
    actual_value: Any = None
    accuracy: Optional[float] = None
    variance: Optional[float] = None
    feedback: str = ""
    model_confidence: float = 0.0
    enterprise_context: Dict[str, Any] = field(default_factory=dict)  # FROM bundle
    ts: float = field(default_factory=time.time)


class _PredictiveStore(MemoryStore):
    table = "nrie_predictive_memory"
    semantic = False
    columns = (("resource_id", "TEXT"), ("kind", "TEXT"))


class PredictiveMemory:
    def __init__(self, store: Optional[_PredictiveStore] = None, publisher=None):
        self._s = store or _PredictiveStore()
        self._pub = publisher or get_event_publisher()

    def record(self, *, kind: str, bundle: ResourceContextBundle,
               predicted_value: Any, model_confidence: float = 0.0) -> PredictionRecord:
        if kind not in PREDICTION_KINDS:
            raise ValueError(f"unknown prediction kind: {kind}")
        rec = PredictionRecord(
            prediction_id="pred-" + uuid.uuid4().hex[:12],
            resource_id=bundle.resource.resource_id, kind=kind,
            predicted_value=predicted_value, model_confidence=model_confidence,
            enterprise_context=bundle.enterprise.__dict__)
        self._persist(rec)
        self._pub.publish(IntelligenceEvent(
            type=PREDICTION_GENERATED, resource_id=rec.resource_id,
            payload={"prediction_id": rec.prediction_id, "kind": kind}))
        return rec

    def record_outcome(self, prediction_id: str, actual_value: float,
                       feedback: str = "") -> Optional[PredictionRecord]:
        row = self._s._by_key(prediction_id)
        if not row:
            return None
        rec = _to_pred(row)
        rec.actual_value = actual_value
        rec.feedback = feedback
        try:
            pv = float(rec.predicted_value)
            rec.variance = round(float(actual_value) - pv, 4)
            denom = abs(float(actual_value)) or 1.0
            rec.accuracy = round(max(0.0, 1.0 - abs(rec.variance) / denom), 4)
        except (TypeError, ValueError):
            rec.variance = rec.accuracy = None
        self._persist(rec)
        return rec

    def _persist(self, rec: PredictionRecord) -> None:
        self._s.learn(rec.prediction_id, f"{rec.kind}", confidence=rec.model_confidence,
                      extra={"record": rec.__dict__}, resource_id=rec.resource_id, kind=rec.kind)

    def by_resource(self, resource_id: str) -> List[PredictionRecord]:
        return [_to_pred(r) for r in self._s._be.query(
            f"SELECT * FROM {self._s.table} WHERE resource_id=?", (resource_id,))]

    def by_kind(self, kind: str) -> List[PredictionRecord]:
        return [_to_pred(r) for r in self._s._be.query(
            f"SELECT * FROM {self._s.table} WHERE kind=?", (kind,))]


def _to_pred(row: Dict[str, Any]) -> PredictionRecord:
    rec = json.loads(row.get("extra") or "{}").get("record", {})
    return PredictionRecord(**rec) if rec else PredictionRecord(
        prediction_id=row.get("k", ""), resource_id=row.get("resource_id", ""),
        kind=row.get("kind", ""))
