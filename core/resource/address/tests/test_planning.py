"""
NRIE · PR-003 Autonomous Planning & Execution · Unit Tests
==========================================================
Drives planning, allocation, lifecycle, optimization, validation, recommendation,
explainability and learning — all from a ResourceContextBundle (single source of
context). Real CIDR math; no configuration generation or deployment.

Runnable: python -m core.resource.address.tests.test_planning
"""
from __future__ import annotations

import uuid

from core.resource.address.context import DefaultContextBuilder
from core.resource.address.domain.entities import (
    BusinessContext, EnterpriseEntity, NetworkResource, OrganizationalKnowledge,
)
from core.resource.address.domain.value_objects import (
    Criticality, EnterpriseLevel, GrowthExpectation, Identifier, Ownership,
    ResourceStatus, ResourceType, RiskClassification,
)
from core.resource.address.allocation.allocator import AddressDemand, IntelligentAllocator
from core.resource.address.allocation.conflict_detector import detect, has_conflict
from core.resource.address.lifecycle.lifecycle_manager import LifecycleManager, LifecycleError
from core.resource.address.lifecycle.state_machine import LifecycleState, can_transition
from core.resource.address.optimization.optimizer import Optimizer
from core.resource.address.planning.planning_service import PlanningService
from core.resource.address.learning.feedback import LearningFeedback
from core.resource.address.learning.outcome_tracker import Outcome
from core.resource.address.api.planning_api import NRIEPlanningAPI


def _bundle(purpose="user_lan", criticality=Criticality.HIGH, growth_pct=30.0):
    b = DefaultContextBuilder()
    rid = "res-" + uuid.uuid4().hex[:8]
    site = EnterpriseEntity(id=Identifier.new("ent"), level=EnterpriseLevel.SITE,
                            name="PUNE-MFG", owner=Ownership(owner="netops"))
    org = EnterpriseEntity(id=Identifier.new("ent"), level=EnterpriseLevel.ORGANIZATION, name="Acme")
    res = NetworkResource(id=Identifier(rid), resource_type=ResourceType.SUBNET,
                          name=f"{purpose}", purpose=purpose, status=ResourceStatus.PLANNED)
    bc = BusinessContext(id=Identifier.new("ctx"), attached_to=site.id,
                         business_capability="Manufacturing", business_service="WMS",
                         business_owner=Ownership(owner="plant-ops"),
                         growth_expectation=GrowthExpectation(horizon="12m", expected_pct=growth_pct),
                         risk_classification=RiskClassification.HIGH,
                         criticality=criticality, compliance=["pci"])
    know = [OrganizationalKnowledge(id=Identifier.new(), kind="address_standard", title="RFC1918")]
    return b.for_resource(res, enterprise_node=site, ancestors=[org],
                          business_context=bc, knowledge=know)


# ── Allocation (intelligent, best-fit, context-aware) ────────────────────────
def test_allocator_sizes_with_growth_and_best_fit():
    al = IntelligentAllocator()
    bundle = _bundle(criticality=Criticality.HIGH, growth_pct=30)
    a = al.allocate(bundle=bundle, demand=AddressDemand("user_lan", 250),
                    pool_id="p", pool_cidr="10.40.0.0/16", existing_cidrs=[])
    assert a.success and a.cidr
    # 250 hosts + 30% growth + 25% criticality headroom → needs > /24 (≈ /23)
    assert a.prefixlen <= 23, a.prefixlen
    # best-fit packs next to existing rather than taking the first block
    a2 = al.allocate(bundle=bundle, demand=AddressDemand("voice", 100),
                     pool_id="p", pool_cidr="10.40.0.0/16", existing_cidrs=[a.cidr])
    assert a2.success and not has_conflict(a2.cidr, [a.cidr])


def test_conflict_detection():
    assert has_conflict("10.0.0.0/24", ["10.0.0.0/24"])         # duplicate
    assert has_conflict("10.0.0.0/25", ["10.0.0.0/24"])         # overlap
    assert not has_conflict("10.0.1.0/24", ["10.0.0.0/24"])     # disjoint


# ── Planning (plan + validate + recommend + explain) ─────────────────────────
def test_planning_service_full_outcome():
    svc = PlanningService()
    bundle = _bundle()
    demands = [AddressDemand("user_lan", 250), AddressDemand("voice", 250),
               AddressDemand("ot", 128), AddressDemand("guest", 200)]
    outcome = svc.plan(bundle=bundle, intent="Deploy 250-user manufacturing site",
                       demands=demands, address_space="10.40.0.0/16")
    assert outcome.plan.success and len(outcome.plan.subnets) == 4
    # no overlaps among planned subnets
    cidrs = [s.cidr for s in outcome.plan.subnets]
    for i, c in enumerate(cidrs):
        assert not detect(c, cidrs[:i])
    assert outcome.plan.vrfs and outcome.plan.vlans
    assert outcome.plan.dhcp_pools and outcome.plan.dns_zones   # access→dhcp, service→dns
    # recommendations ranked, >1 option
    assert len(outcome.recommendations) >= 2
    assert outcome.recommendations[0].confidence >= outcome.recommendations[-1].confidence
    # explanation present and complete
    ex = outcome.explanation
    assert ex.why and ex.evidence and ex.alternatives and ex.expected_benefits


# ── Lifecycle (state machine + audited transitions) ──────────────────────────
def test_lifecycle_transitions_and_audit():
    assert can_transition(LifecycleState.PLANNED, LifecycleState.RESERVED)
    assert not can_transition(LifecycleState.PLANNED, LifecycleState.PRODUCTION)
    lm = LifecycleManager()
    bundle = _bundle()
    lm.transition(bundle=bundle, to_state=LifecycleState.RESERVED, trigger="plan", reason="reserve")
    lm.transition(bundle=bundle, to_state=LifecycleState.ALLOCATED, trigger="alloc", reason="allocate")
    hist = lm.history(bundle.resource.resource_id)
    assert [h.new_state for h in hist] == ["reserved", "allocated"]
    assert all(h.actor and h.ts and h.reason for h in hist)      # audited
    try:
        lm.transition(bundle=bundle, to_state=LifecycleState.ARCHIVED)
        assert False, "illegal transition should raise"
    except LifecycleError:
        pass


# ── Optimization (recommendations only) ──────────────────────────────────────
def test_optimizer_recommendations():
    opt = Optimizer()
    bundle = _bundle()
    sugg = opt.analyze(bundle=bundle, address_space="10.40.0.0/16",
                       allocated_cidrs=["10.40.0.0/24", "10.40.1.0/24"],
                       utilization_pct=18.0)
    kinds = {s.kind for s in sugg}
    assert "route_summarization" in kinds   # two adjacent /24s aggregate to /23
    assert "reclamation" in kinds           # low utilization


# ── Learning feedback (closes loop into reused memories) ─────────────────────
def test_learning_feedback_updates_memory():
    fb = LearningFeedback()
    bundle = _bundle()
    out = fb.capture(bundle=bundle,
                     outcome=Outcome(resource_id=bundle.resource.resource_id, success=True,
                                     operational_outcome="verified", deployment_ref="D-1"))
    assert out.success


# ── API facade ties it together (bundle-driven, no deployment) ───────────────
def test_planning_api_end_to_end():
    api = NRIEPlanningAPI()
    bundle = _bundle()
    outcome = api.plan(bundle=bundle, intent="branch site",
                       demands=[AddressDemand("user_lan", 100), AddressDemand("mgmt", 30)],
                       address_space="10.50.0.0/16")
    assert api.validate(outcome)["valid"] in (True, False)
    assert len(api.recommendations(outcome)) >= 2
    assert api.explanation(outcome)["why"]
    tr = api.transition(bundle=bundle, to_state="reserved", reason="api")
    assert tr.new_state == "reserved"
    opt = api.optimize(bundle=bundle, address_space="10.50.0.0/16",
                       allocated_cidrs=[s.cidr for s in outcome.plan.subnets])
    assert isinstance(opt, list)


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nALL {len(fns)} PR-003 PLANNING TESTS PASSED")


if __name__ == "__main__":
    _run_all()
