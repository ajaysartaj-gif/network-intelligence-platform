"""
Regression for a real production report: after a deployed fix's own
post-apply verification confirmed the neighbor was STILL not FULL, the
platform re-investigated and proposed the EXACT SAME hypothesis and fix
again — repeating indefinitely, with confidence never moving and no record
that the fix had already been tried. The user's own diagnosis: "the engine
keeps treating symptoms instead of updating its belief" — a confirmed
failure should eliminate the hypothesis, not leave it to win again on its
unchanged compiled prior.

TroubleshootingEngine.run(excluded_causes=[...]) closes this: a root-cause
statement already confirmed (via a just-applied fix's own verification) NOT
to have resolved the issue is eliminated immediately after seeding, on every
seeding path (deterministic, LLM-generated, widened) — so it cannot win
again without genuinely new evidence. core/copilot_engine.py's
_continue_investigation_if_needed() threads the just-tried root_cause (plus
anything already excluded from earlier cycles in the same chain) into the
next run() call.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.topology.knowledge_graph_bridge as kgb
from core.troubleshooting import ResolutionStatus, TroubleshootingEngine, TSConfig
from core.troubleshooting.models import ConfidenceDelta, Effect, Goal, Hypothesis, HypothesisState, Session
from core.vendor import VendorGateway

from tests.test_ospf_exstart_end_to_end import (
    FakeDevice, _build_gateway_with_mtu_mismatch, _no_real_topology,
)


# ── unit: the elimination mechanism itself ─────────────────────────────────
def _engine():
    return TroubleshootingEngine(ai_call=lambda p: "", devices=[])


def test_eliminate_excluded_causes_marks_matching_active_hypothesis_eliminated():
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck"))
    h = Hypothesis(statement="MTU mismatch between OSPF neighbors")
    h.set_prior(0.85)
    session.hypotheses.append(h)

    eng._excluded_causes = {"MTU mismatch between OSPF neighbors"}
    eng._eliminate_excluded_causes(session)

    assert h.state == HypothesisState.ELIMINATED
    assert "already applied" in h.rationale.lower()


def test_eliminate_excluded_causes_leaves_unrelated_hypotheses_active():
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck"))
    h = Hypothesis(statement="Duplicate router ID between neighbors")
    h.set_prior(0.3)
    session.hypotheses.append(h)

    eng._excluded_causes = {"MTU mismatch between OSPF neighbors"}
    eng._eliminate_excluded_causes(session)

    assert h.state == HypothesisState.ACTIVE


def test_eliminate_excluded_causes_is_a_no_op_with_nothing_excluded():
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck"))
    h = Hypothesis(statement="MTU mismatch between OSPF neighbors")
    h.set_prior(0.85)
    session.hypotheses.append(h)

    eng._excluded_causes = set()
    eng._eliminate_excluded_causes(session)

    assert h.state == HypothesisState.ACTIVE


def test_run_resets_excluded_causes_between_calls():
    """One engine instance re-used for two separate run() calls must not
    leak an earlier call's exclusions into a later, unrelated one."""
    eng = _engine()
    report1 = eng.run("why OSPF stuck", excluded_causes=["some prior cause"])
    assert eng._excluded_causes == {"some prior cause"}
    report2 = eng.run("why OSPF stuck")
    assert eng._excluded_causes == set()


# ── end-to-end: the EXACT reported cycle, broken by exclusion ─────────────
def test_excluded_mtu_cause_does_not_win_again_on_a_second_investigation(monkeypatch):
    """Reproduces the reported loop directly: run the real OSPF ExStart/MTU
    scenario once (converges to the MTU fix, exactly like
    test_ospf_exstart_end_to_end.py already proves) — then simulate the
    fix having been deployed and its own verification confirming failure
    (still ExStart) by re-running the SAME scenario with that exact
    statement excluded. The MTU hypothesis must not reappear as the winning
    (ACTIVE, top-ranked) cause a second time."""
    _no_real_topology(monkeypatch)
    gw, ip_to_dev = _build_gateway_with_mtu_mismatch()
    devices = list(ip_to_dev.values())

    def ai(_prompt):
        return ""

    eng1 = TroubleshootingEngine(ai_call=ai, devices=devices, gateway=gw, config=TSConfig(max_steps=6))
    report1 = eng1.run("why is the OSPF neighbor stuck in EXSTART")
    s1 = report1.session
    assert s1.status == ResolutionStatus.RESOLVED_PENDING_APPROVAL
    top1 = s1.top()
    assert top1 is not None and "mtu" in top1.statement.lower()

    # Simulate: the fix for `top1.statement` was deployed, verification
    # re-ran, and the neighbor was STILL stuck (the report's own repeated
    # cycle) — the exact statement that failed gets excluded going forward.
    gw2, ip_to_dev2 = _build_gateway_with_mtu_mismatch()   # same still-broken evidence
    devices2 = list(ip_to_dev2.values())
    eng2 = TroubleshootingEngine(ai_call=ai, devices=devices2, gateway=gw2, config=TSConfig(max_steps=6))
    report2 = eng2.run("why is the OSPF neighbor stuck in EXSTART",
                      excluded_causes=[top1.statement])
    s2 = report2.session

    mtu_hyp = next((h for h in s2.hypotheses if h.statement == top1.statement), None)
    assert mtu_hyp is not None, "the excluded hypothesis should still be seeded, just eliminated"
    assert mtu_hyp.state == HypothesisState.ELIMINATED

    # The engine must not propose the SAME fix again for the SAME excluded
    # cause — either it escalates/presents an alternative, or a genuinely
    # different top hypothesis wins; it must never be the excluded one.
    top2 = s2.top()
    if top2 is not None:
        assert top2.statement != top1.statement
