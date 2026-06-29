"""
NRIE · API · Intelligence Read API (PR-002)
===========================================
Read-only facade over the Phase-2 intelligence layers. Every method takes (or
operates on) the ResourceContextBundle from the Context Builder — the single
source of contextual truth. No allocation, planning, or deployment.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..context.models import ResourceContextBundle
from ..cognition.context_builder import ResourceCognition, ResourceCognitionResult
from ..dependency.dependency_engine import DependencyAnalysis, DependencyEngine
from ..memory.decision_memory import DecisionMemory, DecisionRecord
from ..memory.operational_memory import OperationalEvent, OperationalMemory
from ..memory.predictive_memory import PredictionRecord, PredictiveMemory
from ..policy.policy_evaluator import PolicyEvaluation, PolicyEvaluator


class NRIEIntelligenceAPI:
    """Single read surface for NRIE intelligence (PR-002)."""

    def __init__(self, *, decision: Optional[DecisionMemory] = None,
                 operational: Optional[OperationalMemory] = None,
                 predictive: Optional[PredictiveMemory] = None,
                 cognition: Optional[ResourceCognition] = None,
                 policy: Optional[PolicyEvaluator] = None,
                 dependency: Optional[DependencyEngine] = None):
        self.decisions = decision or DecisionMemory()
        self.operational = operational or OperationalMemory()
        self.predictive = predictive or PredictiveMemory()
        self.cognition = cognition or ResourceCognition()
        self.policy = policy or PolicyEvaluator()
        self.dependency = dependency or DependencyEngine()

    # ── history reads ────────────────────────────────────────────────────────
    def decision_history(self, resource_id: str) -> List[DecisionRecord]:
        return self.decisions.by_resource(resource_id)

    def operational_history(self, resource_id: str) -> List[OperationalEvent]:
        return self.operational.timeline(resource_id)

    def prediction_history(self, resource_id: str) -> List[PredictionRecord]:
        return self.predictive.by_resource(resource_id)

    # ── context-driven reads (consume the bundle) ────────────────────────────
    def resource_context(self, bundle: ResourceContextBundle) -> ResourceCognitionResult:
        return self.cognition.comprehend(bundle)

    def policy_evaluation(self, bundle: ResourceContextBundle) -> PolicyEvaluation:
        return self.policy.evaluate(bundle)

    def dependency_graph(self, bundle: ResourceContextBundle) -> DependencyAnalysis:
        return self.dependency.discover(bundle)


_API: Optional[NRIEIntelligenceAPI] = None


def get_intelligence_api() -> NRIEIntelligenceAPI:
    global _API
    if _API is None:
        _API = NRIEIntelligenceAPI()
    return _API
