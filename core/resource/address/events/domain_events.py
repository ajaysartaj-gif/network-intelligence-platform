"""
NRIE · Events · Domain Events (PR-002)
======================================
Intelligence-activity domain events + a thin publisher that REUSES the platform
Event Framework (core.event_engine.EventEngine). NRIE does not introduce a new
bus; it emits typed dicts to the existing engine when one is available and always
keeps a local, testable record. No business logic here.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


# ── event types ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class IntelligenceEvent:
    type: str
    resource_id: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    occurred_at: float = field(default_factory=time.time)

    def as_event(self) -> Dict[str, Any]:
        d = {"type": self.type, "resource_id": self.resource_id,
             "occurred_at": self.occurred_at}
        d.update(self.payload)
        return d


# canonical NRIE intelligence event type names
DECISION_RECORDED = "nrie.DecisionRecorded"
OPERATIONAL_HISTORY_UPDATED = "nrie.OperationalHistoryUpdated"
PREDICTION_GENERATED = "nrie.PredictionGenerated"
COGNITION_COMPLETED = "nrie.CognitionCompleted"
POLICY_EVALUATED = "nrie.PolicyEvaluated"
DEPENDENCY_DISCOVERED = "nrie.DependencyDiscovered"


class IntelligenceEventPublisher:
    """Publishes NRIE events through the existing EventEngine (reused).

    If no engine is supplied/available, events are still recorded locally so the
    intelligence layers remain fully testable without the platform running.
    """

    def __init__(self, event_engine: Optional[Any] = None):
        self._engine = event_engine
        self._recorded: List[Dict[str, Any]] = []

    def publish(self, event: IntelligenceEvent) -> Dict[str, Any]:
        record = event.as_event()
        self._recorded.append(record)
        try:
            if self._engine is not None and hasattr(self._engine, "emit_event"):
                self._engine.emit_event(record)
        except Exception:
            pass  # publishing must never break intelligence recording
        return record

    @property
    def recorded(self) -> List[Dict[str, Any]]:
        return list(self._recorded)


_PUBLISHER: Optional[IntelligenceEventPublisher] = None


def get_event_publisher(event_engine: Optional[Any] = None) -> IntelligenceEventPublisher:
    global _PUBLISHER
    if _PUBLISHER is None or event_engine is not None:
        _PUBLISHER = IntelligenceEventPublisher(event_engine)
    return _PUBLISHER


# ── PR-003: planning / allocation / lifecycle / optimization events ──────────
RESOURCE_PLANNED = "nrie.ResourcePlanned"
RESOURCE_ALLOCATED = "nrie.ResourceAllocated"
ALLOCATION_FAILED = "nrie.AllocationFailed"
LIFECYCLE_CHANGED = "nrie.LifecycleChanged"
OPTIMIZATION_SUGGESTED = "nrie.OptimizationSuggested"
RECOMMENDATION_GENERATED = "nrie.RecommendationGenerated"
VALIDATION_COMPLETED = "nrie.ValidationCompleted"
DEPLOYMENT_VERIFIED = "nrie.DeploymentVerified"
LEARNING_UPDATED = "nrie.LearningUpdated"
