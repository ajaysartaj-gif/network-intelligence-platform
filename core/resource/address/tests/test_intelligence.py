"""
NRIE · PR-002 Intelligence & Reasoning · Unit Tests
===================================================
Every test drives the intelligence layers from a ResourceContextBundle produced
by the Context Builder (the single source of contextual truth). No intelligence
module reconstructs context.

Runnable: python -m core.resource.address.tests.test_intelligence
"""
from __future__ import annotations

import uuid

from core.resource.address.context import DefaultContextBuilder, ResourceContextBundle
from core.resource.address.domain.aggregates import Pool
from core.resource.address.domain.entities import (
    BusinessContext, EnterpriseEntity, NetworkResource, OrganizationalKnowledge,
)
from core.resource.address.domain.value_objects import (
    ArchitecturePattern, Criticality, EnterpriseLevel, Identifier, OperationalModel,
    Ownership, ResourceStatus, ResourceType, RiskClassification,
)
from core.resource.address.cognition.context_builder import ResourceCognition
from core.resource.address.dependency.dependency_engine import DependencyEngine
from core.resource.address.events.domain_events import IntelligenceEventPublisher
from core.resource.address.memory.decision_memory import DecisionMemory
from core.resource.address.memory.operational_memory import OperationalMemory
from core.resource.address.memory.predictive_memory import PredictiveMemory
from core.resource.address.policy.policy_evaluator import PolicyEvaluator
from core.resource.address.api.intelligence_api import NRIEIntelligenceAPI


def _bundle(purpose="ot", criticality=Criticality.HIGH, risk=RiskClassification.HIGH):
    """Build a context bundle via the Context Builder (single source of truth)."""
    b = DefaultContextBuilder()
    rid = "res-" + uuid.uuid4().hex[:8]
    site = EnterpriseEntity(id=Identifier.new("ent"), level=EnterpriseLevel.SITE,
                            name="PUNE-MFG", owner=Ownership(owner="netops"))
    org = EnterpriseEntity(id=Identifier.new("ent"), level=EnterpriseLevel.ORGANIZATION, name="Acme")
    res = NetworkResource(id=Identifier(rid), resource_type=ResourceType.SUBNET,
                          name=f"{purpose}-lan", purpose=purpose, status=ResourceStatus.PLANNED)
    bc = BusinessContext(id=Identifier.new("ctx"), attached_to=site.id,
                         business_capability="Manufacturing", business_service="WMS",
                         business_owner=Ownership(owner="plant-ops"),
                         operational_model=OperationalModel.CO_MANAGED,
                         architecture_pattern=ArchitecturePattern.SDWAN,
                         risk_classification=risk, criticality=criticality, compliance=["pci"])
    know = [OrganizationalKnowledge(id=Identifier.new(), kind="address_standard", title="RFC1918")]
    pool = Pool(id=Identifier.new("pool"), purpose="branch_lan"); pool.add_subnet(res)
    return b.for_resource(res, enterprise_node=site, ancestors=[org],
                          business_context=bc, knowledge=know, pool=pool)


# ── Decision Memory (Layer 4) ────────────────────────────────────────────────
def test_decision_memory_records_and_queries():
    pub = IntelligenceEventPublisher()
    dm = DecisionMemory(publisher=pub)
    bundle = _bundle()
    rec = dm.record(decision_type="resource_classification", bundle=bundle,
                    alternatives=["A", "B"], confidence=0.82, final_decision="A",
                    reasoning_summary="A best fits the secure OT zone")
    assert rec.decision_id and rec.enterprise_context.get("name") == "PUNE-MFG"
    got = dm.by_resource(bundle.resource.resource_id)
    assert any(d.decision_id == rec.decision_id for d in got)
    assert any(e["type"] == "nrie.DecisionRecorded" for e in pub.recorded)


# ── Operational Memory (Layer 5) ─────────────────────────────────────────────
def test_operational_memory_timeline():
    om = OperationalMemory(publisher=IntelligenceEventPublisher())
    bundle = _bundle()
    om.record(kind="allocation", bundle=bundle, detail="recorded allocation")
    om.record(kind="verification", bundle=bundle, detail="verified", deployment_ref="D-1")
    tl = om.timeline(bundle.resource.resource_id)
    assert [e.kind for e in tl] == ["allocation", "verification"]
    try:
        om.record(kind="not_a_kind", bundle=bundle)
        assert False
    except ValueError:
        pass


# ── Predictive Memory (Layer 6) ──────────────────────────────────────────────
def test_predictive_memory_accuracy():
    pm = PredictiveMemory(publisher=IntelligenceEventPublisher())
    bundle = _bundle()
    rec = pm.record(kind="capacity", bundle=bundle, predicted_value=80.0, model_confidence=0.7)
    updated = pm.record_outcome(rec.prediction_id, actual_value=76.0, feedback="close")
    assert updated.variance == -4.0 and 0.9 < updated.accuracy <= 1.0


# ── Resource Cognition (Layer 9) — consumes bundle ───────────────────────────
def test_resource_cognition_from_bundle():
    cog = ResourceCognition(publisher=IntelligenceEventPublisher())
    bundle = _bundle(purpose="ot")
    result = cog.comprehend(bundle)
    assert result.classification["category"] == "addressing"
    assert result.classification["purpose_class"] == "secure"
    assert result.criticality == "high"
    assert result.owner == "plant-ops"          # ownership resolved from bundle
    assert result.relationships                  # discovered via ontology
    assert result.context["domain"] == "address"  # echoes bundle, not rebuilt


# ── Policy Intelligence (Layer 10) — evaluate & report ───────────────────────
def test_policy_evaluation_reports():
    pe = PolicyEvaluator(publisher=IntelligenceEventPublisher())
    # high criticality → business_rule recommends review (a reported violation)
    ev = pe.evaluate(_bundle(criticality=Criticality.HIGH))
    assert not ev.passed and any("business_rule" in v for v in ev.violations)
    assert ev.applicable_standards and ev.evaluated_rules > 0
    # a compliant normal resource passes
    ev2 = pe.evaluate(_bundle(purpose="user_lan", criticality=Criticality.NORMAL,
                              risk=RiskClassification.LOW))
    assert ev2.passed


# ── Dependency Intelligence (Layer 11) — reuses Knowledge Graph ──────────────
def test_dependency_discovery_uses_graph():
    de = DependencyEngine(publisher=IntelligenceEventPublisher())
    analysis = de.discover(_bundle(purpose="subnet"))
    d = analysis.to_dict()
    assert set(d.keys()) == {"upstream", "downstream", "business", "routing", "security", "cloud"}
    assert d["downstream"] or d["upstream"]


# ── Read API ties it together (all bundle-driven) ────────────────────────────
def test_intelligence_api_readonly():
    api = NRIEIntelligenceAPI()
    bundle = _bundle()
    api.decisions.record(decision_type="t", bundle=bundle, final_decision="x")
    api.operational.record(kind="allocation", bundle=bundle)
    assert api.decision_history(bundle.resource.resource_id)
    assert api.operational_history(bundle.resource.resource_id)
    assert api.resource_context(bundle).resource_id == bundle.resource.resource_id
    assert api.policy_evaluation(bundle).evaluated_rules > 0
    assert "downstream" in api.dependency_graph(bundle).to_dict()


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nALL {len(fns)} PR-002 INTELLIGENCE TESTS PASSED")


if __name__ == "__main__":
    _run_all()
