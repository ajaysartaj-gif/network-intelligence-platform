"""
NRIE · API · Planning & Allocation API (PR-003)
===============================================
Facade over the Phase-3 autonomous-planning capabilities. Every method is driven
by the ResourceContextBundle (single source of context). NRIE plans, allocates,
validates, recommends, optimizes, explains and learns — it never generates
configuration or deploys (existing deployment components own execution).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..allocation.allocator import AddressDemand, Allocation, IntelligentAllocator
from ..context.models import ResourceContextBundle
from ..lifecycle.lifecycle_manager import LifecycleManager
from ..lifecycle.state_machine import LifecycleState
from ..memory.operational_memory import OperationalMemory
from ..optimization.optimizer import Optimizer
from ..planning.planning_service import PlanningOutcome, PlanningService
from ..learning.feedback import LearningFeedback
from ..learning.outcome_tracker import Outcome


class NRIEPlanningAPI:
    def __init__(self):
        self._planning = PlanningService()
        self._allocator = IntelligentAllocator()
        self._optimizer = Optimizer()
        self._lifecycle = LifecycleManager(operational_memory=OperationalMemory())
        self._feedback = LearningFeedback()

    # ── planning (plan + validate + recommend + explain) ─────────────────────
    def plan(self, *, bundle: ResourceContextBundle, intent: str,
             demands: List[AddressDemand], address_space: str = "10.40.0.0/16") -> PlanningOutcome:
        return self._planning.plan(bundle=bundle, intent=intent, demands=demands,
                                   address_space=address_space)

    # ── single allocation ────────────────────────────────────────────────────
    def allocate(self, *, bundle: ResourceContextBundle, demand: AddressDemand,
                 pool_cidr: str, existing_cidrs: Optional[List[str]] = None) -> Allocation:
        return self._allocator.allocate(
            bundle=bundle, demand=demand, pool_id=f"pool:{demand.vrf or demand.purpose}",
            pool_cidr=pool_cidr, existing_cidrs=existing_cidrs or [])

    # ── validation / recommendations / explanation (from a planning outcome) ─
    def validate(self, outcome: PlanningOutcome) -> Dict[str, Any]:
        return outcome.validation.to_dict()

    def recommendations(self, outcome: PlanningOutcome) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in outcome.recommendations]

    def explanation(self, outcome: PlanningOutcome) -> Optional[Dict[str, Any]]:
        return outcome.explanation.to_dict() if outcome.explanation else None

    # ── optimization ─────────────────────────────────────────────────────────
    def optimize(self, *, bundle: ResourceContextBundle, address_space: str,
                 allocated_cidrs: List[str], utilization_pct: float = 0.0) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in self._optimizer.analyze(
            bundle=bundle, address_space=address_space,
            allocated_cidrs=allocated_cidrs, utilization_pct=utilization_pct)]

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def transition(self, *, bundle: ResourceContextBundle, to_state: str,
                   trigger: str = "", actor: str = "ai", reason: str = "",
                   deployment_ref: str = "", change_ref: str = ""):
        return self._lifecycle.transition(
            bundle=bundle, to_state=LifecycleState(to_state), trigger=trigger,
            actor=actor, reason=reason, deployment_ref=deployment_ref, change_ref=change_ref)

    def lifecycle_history(self, resource_id: str):
        return self._lifecycle.history(resource_id)

    # ── learning feedback ────────────────────────────────────────────────────
    def learn(self, *, bundle: ResourceContextBundle, outcome: Outcome,
              decision_id: str = "") -> Dict[str, Any]:
        return self._feedback.capture(bundle=bundle, outcome=outcome,
                                      decision_id=decision_id).as_dict()


_PLANNING_API: Optional[NRIEPlanningAPI] = None


def get_planning_api() -> NRIEPlanningAPI:
    global _PLANNING_API
    if _PLANNING_API is None:
        _PLANNING_API = NRIEPlanningAPI()
    return _PLANNING_API
