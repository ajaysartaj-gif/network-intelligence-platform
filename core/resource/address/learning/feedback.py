"""
NRIE · Learning · Learning Feedback (closes the loop)
=====================================================
After execution, feeds outcomes back into the REUSED PR-002 memory layers:
Decision Memory (outcome status), Operational Memory (operational result) and
Predictive Memory (actual value → accuracy). Publishes LearningUpdated. No new
memory engine is introduced.
"""
from __future__ import annotations

from typing import Optional

from ..context.models import ResourceContextBundle
from ..events.domain_events import (
    LEARNING_UPDATED, IntelligenceEvent, get_event_publisher,
)
from ..memory.decision_memory import DecisionMemory
from ..memory.operational_memory import OperationalMemory
from ..memory.predictive_memory import PredictiveMemory
from .outcome_tracker import Outcome


class LearningFeedback:
    def __init__(self, *, decision: Optional[DecisionMemory] = None,
                 operational: Optional[OperationalMemory] = None,
                 predictive: Optional[PredictiveMemory] = None, publisher=None):
        self._decision = decision or DecisionMemory()
        self._operational = operational or OperationalMemory()
        self._predictive = predictive or PredictiveMemory()
        self._pub = publisher or get_event_publisher()

    def capture(self, *, bundle: ResourceContextBundle, outcome: Outcome,
                decision_id: str = "") -> Outcome:
        # Decision Memory ← outcome status
        if decision_id:
            try:
                self._decision.set_outcome(
                    decision_id, "succeeded" if outcome.success else "failed")
            except Exception:
                pass
        # Operational Memory ← operational result (reused kinds)
        try:
            self._operational.record(
                kind="verification" if outcome.success else "rollback",
                bundle=bundle,
                detail=outcome.operational_outcome or
                       ("verified" if outcome.success else "failed"),
                deployment_ref=outcome.deployment_ref)
        except Exception:
            pass
        # Predictive Memory ← realized actual → accuracy/variance
        if outcome.prediction_id and outcome.prediction_actual is not None:
            try:
                self._predictive.record_outcome(
                    outcome.prediction_id, actual_value=outcome.prediction_actual,
                    feedback=outcome.user_feedback)
            except Exception:
                pass
        self._pub.publish(IntelligenceEvent(
            type=LEARNING_UPDATED, resource_id=bundle.resource.resource_id,
            payload={"success": outcome.success, "override": bool(outcome.user_override)}))
        return outcome
