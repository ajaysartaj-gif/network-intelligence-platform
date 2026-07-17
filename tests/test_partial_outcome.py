"""
Regression for the missing "Evaluate result" branch: today a fix's outcome
is binary — _record_ts_outcome(success: bool) either confirms a hypothesis
or fully excludes its root cause via excluded_causes, forcing a full
restart on the next-best hypothesis. A fix that genuinely helped (resolved
1 of 2 broken neighbors, or moved a neighbor closer to FULL without quite
reaching it) was indistinguishable from one that did nothing at all — both
collapsed into _target_neighbor_still_broken()'s single bool, and both
permanently barred the tried root cause from ever being reconsidered.

This adds the missing third branch: "partial". A partially-correct
hypothesis survives with reduced confidence (core.troubleshooting.engine's
_apply_partial_refinements) instead of being thrown out
(_eliminate_excluded_causes), while a genuinely useless fix is still fully
excluded exactly as before.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import copilot_engine
from core.troubleshooting import ResolutionStatus, TroubleshootingEngine, TSConfig
from core.troubleshooting.hypotheses import ConfidenceCalculator, HypothesisManager
from core.troubleshooting.models import Goal, HypothesisState, Hypothesis, Session

from tests.test_governed_fix_apply import FakeDevice as GovFakeDevice, _pending_state
from tests.test_ospf_exstart_end_to_end import (
    FakeDevice, _build_gateway_with_mtu_mismatch, _no_real_topology,
)


def _engine():
    return TroubleshootingEngine(ai_call=lambda p: "", devices=[])


# ── unit: _classify_verification_outcome() ──────────────────────────────────
def test_classify_resolved_when_nothing_left_broken():
    pending = _pending_state(["ip ospf mtu-ignore"],
                             root_cause="MTU mismatch between OSPF neighbors")
    pending["verification_targets"] = {}
    assert copilot_engine._classify_verification_outcome(pending) == "resolved"


def test_classify_resolved_for_named_pair_even_when_unrelated_neighbor_elsewhere_still_broken():
    pending = _pending_state(
        ["ip ospf mtu-ignore"],
        root_cause="interface_mtu must equal violated on ospf_adjacency between "
                   "10.0.0.1 and 10.0.0.2")
    pending["pre_fix_targets"] = {
        "10.0.0.1": [{"ip": "10.0.0.2", "state": "EXSTART", "interface": "Gi0/0"}],
    }
    # only partially scoped here — imagine a second, unrelated neighbor
    # elsewhere was also broken pre-fix, but the NAMED pair itself improved
    pending["pre_fix_targets"]["10.0.0.1"].append(
        {"ip": "10.0.0.9", "state": "DOWN", "interface": "Gi0/1"})
    pending["verification_targets"] = {
        "10.0.0.1": [{"ip": "10.0.0.9", "state": "DOWN", "interface": "Gi0/1"}],
    }
    # named pair (10.0.0.1/10.0.0.2) no longer appears in verification_targets
    # at all -> scoped to the named pair, nothing is left broken -> resolved
    # for THIS root cause specifically (matches _target_neighbor_still_broken's
    # own scoping precedent: only the named pair matters to this classification).
    assert copilot_engine._classify_verification_outcome(pending) == "resolved"


def test_classify_partial_multi_target_no_named_pair():
    """No 'between A and B' in root_cause (unscoped) -- 2 neighbors broken
    pre-fix, only 1 remains -> partial."""
    pending = _pending_state(["ip ospf mtu-ignore"],
                             root_cause="MTU mismatch across multiple OSPF neighbors")
    pending["pre_fix_targets"] = {
        "10.0.0.1": [
            {"ip": "10.0.0.2", "state": "EXSTART", "interface": "Gi0/0"},
            {"ip": "10.0.0.3", "state": "EXSTART", "interface": "Gi0/1"},
        ],
    }
    pending["verification_targets"] = {
        "10.0.0.1": [{"ip": "10.0.0.3", "state": "EXSTART", "interface": "Gi0/1"}],
    }
    assert copilot_engine._classify_verification_outcome(pending) == "partial"


def test_classify_failed_when_no_improvement_at_all():
    pending = _pending_state(
        ["ip ospf mtu-ignore"],
        root_cause="interface_mtu must equal violated on ospf_adjacency between "
                   "10.0.0.1 and 10.0.0.2")
    pending["pre_fix_targets"] = {
        "10.0.0.1": [{"ip": "10.0.0.2", "state": "EXSTART", "interface": "Gi0/0"}],
    }
    pending["verification_targets"] = {
        "10.0.0.1": [{"ip": "10.0.0.2", "state": "EXSTART", "interface": "Gi0/0"}],
    }
    assert copilot_engine._classify_verification_outcome(pending) == "failed"


def test_classify_falls_back_to_binary_without_a_pre_fix_baseline():
    """No pre_fix_targets captured at all (e.g. an older code path) ->
    never "partial", degrades to resolved/failed exactly like the old
    _target_neighbor_still_broken()-only behavior."""
    pending = _pending_state(["ip ospf mtu-ignore"],
                             root_cause="MTU mismatch between OSPF neighbors")
    pending["verification_targets"] = {
        "10.0.0.1": [{"ip": "10.0.0.2", "state": "EXSTART", "interface": "Gi0/0"}],
    }
    assert copilot_engine._classify_verification_outcome(pending) == "failed"


def test_classify_no_evidence_at_all_defers_to_operator_claim():
    """No verification_targets and no pre_fix_targets (nothing was ever
    re-collected) -- must not silently invent "resolved" when the operator
    explicitly reported the issue is still broken."""
    pending = _pending_state(["ip ospf mtu-ignore"], root_cause="some cause")
    assert copilot_engine._classify_verification_outcome(
        pending, default_when_no_evidence="failed") == "failed"
    assert copilot_engine._classify_verification_outcome(
        pending, default_when_no_evidence="resolved") == "resolved"


# ── unit: _pre_fix_targets() ─────────────────────────────────────────────────
def test_pre_fix_targets_scoped_to_target_devices_and_most_recent_state():
    from core.troubleshooting.models import Observation
    session = Session(goal=Goal(query="why OSPF stuck"))
    session.observations.append(Observation(device="10.0.0.1", subject="neighbor.10.0.0.2",
                                            attribute="state", value="Down"))
    # a later, more recent observation for the SAME neighbor supersedes it
    session.observations.append(Observation(device="10.0.0.1", subject="neighbor.10.0.0.2",
                                            attribute="state", value="ExStart"))
    session.observations.append(Observation(device="10.0.0.1", subject="neighbor.10.0.0.2",
                                            attribute="interface", value="Gi0/0"))
    # unrelated device, must be excluded by target_ips scoping
    session.observations.append(Observation(device="10.0.0.9", subject="neighbor.10.0.0.8",
                                            attribute="state", value="Down"))

    out = copilot_engine._pre_fix_targets(session, "ospf", ["10.0.0.1"])
    assert out == {"10.0.0.1": [{"ip": "10.0.0.2", "state": "EXSTART", "interface": "Gi0/0"}]}


def test_pre_fix_targets_empty_for_non_ospf_or_missing_session():
    assert copilot_engine._pre_fix_targets(None, "ospf", ["10.0.0.1"]) == {}
    assert copilot_engine._pre_fix_targets(Session(), "bgp", ["10.0.0.1"]) == {}


# ── unit: engine._apply_partial_refinements() ────────────────────────────────
def test_apply_partial_refinements_penalizes_but_does_not_eliminate():
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck"))
    h = Hypothesis(statement="MTU mismatch between OSPF neighbors")
    h.set_prior(0.7)
    session.hypotheses.append(h)
    before = h.confidence

    eng._partial_causes = {"MTU mismatch between OSPF neighbors":
                           "resolved 1 of 2 targeted neighbors"}
    eng._apply_partial_refinements(session)

    assert h.state == HypothesisState.ACTIVE
    assert h.confidence < before
    assert "partially confirmed" in h.rationale.lower()


def test_apply_partial_refinements_is_a_no_op_with_nothing_partial():
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck"))
    h = Hypothesis(statement="MTU mismatch between OSPF neighbors")
    h.set_prior(0.7)
    session.hypotheses.append(h)
    before = h.confidence

    eng._partial_causes = {}
    eng._apply_partial_refinements(session)
    assert h.confidence == before


def test_apply_partial_refinements_does_not_double_penalize_same_run():
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck"))
    h = Hypothesis(statement="MTU mismatch between OSPF neighbors")
    h.set_prior(0.7)
    session.hypotheses.append(h)

    eng._partial_causes = {"MTU mismatch between OSPF neighbors": "reason"}
    eng._apply_partial_refinements(session)
    once = h.confidence
    eng._apply_partial_refinements(session)   # called again, same run (mirrors the 3 call sites)
    assert h.confidence == once


def test_partial_penalty_can_push_an_already_weak_hypothesis_below_reap_floor():
    """reap()'s existing confidence floor (ELIMINATE_BELOW) must still
    retire a hypothesis that receives a partial-outcome penalty on top of
    other real contradicting evidence gathered in the same run — no new
    elimination path is needed, the ordinary floor check does the work."""
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck"))
    h = Hypothesis(statement="MTU mismatch between OSPF neighbors")
    h.set_prior(0.07)   # already weak from this run's other evidence
    h.evidence_ids.append("seed")   # reap()'s floor check requires evidence_ids
    session.hypotheses.append(h)

    eng._partial_causes = {"MTU mismatch between OSPF neighbors": "reason"}
    eng._apply_partial_refinements(session)
    HypothesisManager(session).reap()

    assert h.state == HypothesisState.ELIMINATED


# ── end-to-end: engine.run(partial_causes=...) survives with lower confidence ──
def test_partial_cause_survives_reinvestigation_with_reduced_confidence(monkeypatch):
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
    conf1 = top1.confidence

    # Simulate: the fix for top1.statement was deployed and PARTIALLY worked
    # (unlike test_excluded_causes.py's identical-failure reproduction).
    gw2, ip_to_dev2 = _build_gateway_with_mtu_mismatch()
    devices2 = list(ip_to_dev2.values())
    eng2 = TroubleshootingEngine(ai_call=ai, devices=devices2, gateway=gw2, config=TSConfig(max_steps=6))
    report2 = eng2.run("why is the OSPF neighbor stuck in EXSTART",
                      partial_causes={top1.statement: "resolved 1 of 2 targeted neighbors"})
    s2 = report2.session

    mtu_hyp = next((h for h in s2.hypotheses if h.statement == top1.statement), None)
    assert mtu_hyp is not None, "a partially-confirmed hypothesis must still be seeded"
    assert mtu_hyp.state != HypothesisState.ELIMINATED, \
        "partial credit must not fully eliminate the hypothesis like excluded_causes would"
    assert mtu_hyp.confidence < conf1, \
        "a partial outcome must measurably lower confidence, not leave it unchanged"
    assert top1.statement not in eng2._excluded_causes, \
        "a partial outcome must never land in excluded_causes -- that would fully bar it"


# ── copilot_engine: _continue_investigation_if_needed threads partial_causes ──
class _FakeFollowUpEngine:
    last_excluded_causes = None
    last_partial_causes = None
    report_to_return = None

    def __init__(self, ai_call, devices, gateway, config, session_store=None):
        pass

    def run(self, query, excluded_causes=None, partial_causes=None):
        _FakeFollowUpEngine.last_excluded_causes = excluded_causes
        _FakeFollowUpEngine.last_partial_causes = partial_causes
        return _FakeFollowUpEngine.report_to_return


class _FakeSession:
    def __init__(self, fix=None, verification=None, goal_devices=None):
        self.fix = fix
        self.verification = verification
        self.goal = types.SimpleNamespace(devices=goal_devices or [])


class _FakeReport:
    def __init__(self, markdown, session):
        self._markdown = markdown
        self.session = session

    def to_markdown(self):
        return self._markdown


def test_continue_investigation_routes_a_partial_outcome_into_partial_causes_not_excluded(monkeypatch):
    dev = GovFakeDevice("10.0.0.1", "R1")
    pending = _pending_state(
        ["ip ospf mtu-ignore"], verification=["show ip ospf neighbor"],
        root_cause="interface_mtu must equal violated on ospf_adjacency between "
                   "10.0.0.2 and 10.0.0.3")
    pending["devices"] = [dev]
    pending["pre_fix_targets"] = {
        "10.0.0.1": [
            {"ip": "10.0.0.2", "state": "EXSTART", "interface": "Gi0/0"},
            {"ip": "10.0.0.3", "state": "EXSTART", "interface": "Gi0/1"},
        ],
    }
    # only 10.0.0.2 remains broken -> partial (10.0.0.3 now fine)
    pending["verification_targets"] = {
        "10.0.0.1": [{"ip": "10.0.0.2", "state": "EXSTART", "interface": "Gi0/0"}],
    }

    session = _FakeSession(fix=None, verification=None, goal_devices=["10.0.0.1"])
    _FakeFollowUpEngine.report_to_return = _FakeReport("### follow-up", session)
    monkeypatch.setattr(copilot_engine, "_make_troubleshooting_gateway", lambda call_ai_fn, devices: object())
    import core.troubleshooting as ts_module
    monkeypatch.setattr(ts_module, "TroubleshootingEngine", _FakeFollowUpEngine)

    copilot_engine._continue_investigation_if_needed(None, pending)

    assert _FakeFollowUpEngine.last_excluded_causes == []
    assert pending["root_cause"] in _FakeFollowUpEngine.last_partial_causes
