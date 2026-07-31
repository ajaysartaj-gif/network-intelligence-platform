"""Regression for DiagnosticPolicyEngine.select_capability and
request_evidence -- the decision layer that must never trigger a diagnostic
just because confidence is low, only when read-only evidence is genuinely
exhausted AND there are still competing hypotheses it could discriminate
between AND a capability is actually registered AND governance authorizes it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.diagnostics.policy import DiagnosticPolicyEngine, request_evidence


class _Hyp:
    def __init__(self, hid):
        self.id = hid


def _two_hypotheses():
    return [_Hyp("h1"), _Hyp("h2")]


def test_refuses_when_read_only_evidence_is_not_exhausted():
    engine = DiagnosticPolicyEngine()
    result = engine.select_capability(
        technology="ospf", vendor="ios-like", active_hypotheses=_two_hypotheses(),
        read_only_evidence_exhausted=False,
    )
    assert result is None


def test_refuses_when_fewer_than_two_competing_hypotheses_remain():
    engine = DiagnosticPolicyEngine()
    result = engine.select_capability(
        technology="ospf", vendor="ios-like", active_hypotheses=[_Hyp("h1")],
        read_only_evidence_exhausted=True,
    )
    assert result is None


def test_refuses_when_no_capability_registered_for_technology():
    engine = DiagnosticPolicyEngine()
    result = engine.select_capability(
        technology="bgp", vendor="ios-like", active_hypotheses=_two_hypotheses(),
        read_only_evidence_exhausted=True,
    )
    assert result is None


def test_refuses_when_no_action_spec_for_vendor():
    engine = DiagnosticPolicyEngine()
    result = engine.select_capability(
        technology="ospf", vendor="junos_like", active_hypotheses=_two_hypotheses(),
        read_only_evidence_exhausted=True,
    )
    assert result is None


def test_happy_path_returns_capability_and_spec():
    engine = DiagnosticPolicyEngine()
    result = engine.select_capability(
        technology="ospf", vendor="ios-like", active_hypotheses=_two_hypotheses(),
        read_only_evidence_exhausted=True,
    )
    assert result is not None
    cap, spec = result
    assert cap.technology == "ospf"
    assert spec.enable_commands == ["debug ip ospf adj"]


def test_request_evidence_returns_none_when_policy_does_not_select_anything():
    def send(commands):
        return {c: "" for c in commands}

    result = request_evidence(
        technology="bgp", vendor="ios-like", device="10.0.0.1", send=send,
        active_hypotheses=_two_hypotheses(), read_only_evidence_exhausted=True,
    )
    assert result is None


def test_request_evidence_refused_when_governance_denies(monkeypatch):
    import core.diagnostics.policy as policy_mod

    monkeypatch.setattr(policy_mod, "governance_gate",
                         lambda *a, **kw: (False, "compliance failure: destructive command"))

    def send(commands):
        return {c: "" for c in commands}

    result = request_evidence(
        technology="ospf", vendor="ios-like", device="10.0.0.1", send=send,
        active_hypotheses=_two_hypotheses(), read_only_evidence_exhausted=True,
    )
    assert result.refused
    assert "governance denied" in result.refusal_reason


def test_request_evidence_happy_path_runs_the_diagnostic(monkeypatch):
    import core.diagnostics.policy as policy_mod
    import core.diagnostics.executor as ex

    monkeypatch.setattr(policy_mod, "governance_gate", lambda *a, **kw: (True, "Approved."))
    monkeypatch.setattr(ex.time, "sleep", lambda s: None)

    responses = {
        "show processes cpu": "CPU utilization for five seconds: 5%/1%; one minute: 5%; five minutes: 5%",
        "show logging": "Buffered logging: level debugging, 3 messages logged",
    }

    def send(commands):
        return {c: responses.get(c, "") for c in commands}

    result = request_evidence(
        technology="ospf", vendor="ios-like", device="10.0.0.1", send=send,
        active_hypotheses=_two_hypotheses(), read_only_evidence_exhausted=True,
    )
    assert result is not None
    assert not result.refused
    assert result.cleanly_disabled is True
