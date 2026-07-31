"""
Regression for the "Plan" stage of the investigation loop: a real user
reported that the engine "often chose generic commands instead of targeted
ones." Root cause in the gateway/operations path
(TroubleshootingEngine._next_evidence_via_gateway):

1. The LLM is asked to return a "value" (0-1 usefulness) and
   "tests_hypotheses" for each candidate operation -- exactly like the
   raw-command path already scores with _pick_command -- but this method
   took the FIRST usable candidate unconditionally, discarding that signal
   entirely. A generic, low-value operation listed first by the LLM would
   always win over a more specific, higher-value one listed second.

2. The prompt schema labeled "protocol" as optional inside `params`. When
   the LLM omitted it, core.vendor.adapters.cisco_ios_like.py's
   build_command() silently falls back to 3 hardcoded GENERIC commands
   (show ip interface brief / show ip route / show running-config) instead
   of this protocol's real, targeted ones -- a direct, concrete mechanism
   for "generic instead of targeted."

Fix: score every usable candidate the same way _pick_command does
(value + 0.1*len(tests_hypotheses)), and default params["protocol"] from
the engine's own already-detected protocol whenever the LLM leaves it out.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.troubleshooting import TroubleshootingEngine, TSConfig
from core.troubleshooting.models import Goal, Session


class FakeDevice:
    def __init__(self, ip, hostname):
        self.ip = ip
        self.hostname = hostname
        self.device_type = "cisco_ios"


class FakeGateway:
    """Records every Operation actually dispatched via collect(), so tests
    can inspect exactly which operation+params won the scoring, without
    depending on any real vendor adapter parsing."""

    def __init__(self):
        self.dispatched = []

    def supports_operation(self, device, opname):
        return True

    def collect(self, device, operation):
        self.dispatched.append((device.ip, operation.name, dict(operation.params)))
        return [], None


def _engine(gateway, plan_operations_result, query="why is ospf down"):
    eng = TroubleshootingEngine(ai_call=lambda p: "", devices=[FakeDevice("10.0.0.1", "R1")],
                                gateway=gateway, config=TSConfig(max_steps=1))
    eng.reasoner.plan_operations = lambda *a, **kw: plan_operations_result
    return eng


def _session(query):
    return Session(goal=Goal(query=query, objective=query))


def test_highest_scored_candidate_wins_not_the_first_listed():
    gw = FakeGateway()
    candidates = [
        {"device": "10.0.0.1", "operation": "get_configuration", "params": {"protocol": "ospf"},
         "purpose": "generic sweep", "tests_hypotheses": [], "value": 0.2},
        {"device": "10.0.0.1", "operation": "get_neighbors", "params": {"protocol": "ospf"},
         "purpose": "targeted", "tests_hypotheses": ["h1"], "value": 0.9},
    ]
    eng = _engine(gw, candidates)
    session = _session("why is ospf down")

    outputs = eng._next_evidence_via_gateway(session, [], "", [], ["10.0.0.1"])

    assert outputs is not None
    assert gw.dispatched, "no operation was ever dispatched"
    _, opname, _ = gw.dispatched[0]
    assert opname == "get_neighbors", gw.dispatched


def test_a_candidate_scored_zero_is_not_silently_promoted_to_default():
    """The `0 or 0.5` falsy bug: a candidate the LLM explicitly scored 0
    must stay ranked below one scored 0.1, never get bumped up to 0.5."""
    gw = FakeGateway()
    candidates = [
        {"device": "10.0.0.1", "operation": "get_configuration", "params": {"protocol": "ospf"},
         "purpose": "worthless", "tests_hypotheses": [], "value": 0},
        {"device": "10.0.0.1", "operation": "get_neighbors", "params": {"protocol": "ospf"},
         "purpose": "barely useful but still better", "tests_hypotheses": [], "value": 0.1},
    ]
    eng = _engine(gw, candidates)
    session = _session("why is ospf down")

    eng._next_evidence_via_gateway(session, [], "", [], ["10.0.0.1"])

    _, opname, _ = gw.dispatched[0]
    assert opname == "get_neighbors", gw.dispatched


def test_missing_protocol_param_is_defaulted_from_detected_protocol():
    gw = FakeGateway()
    candidates = [
        {"device": "10.0.0.1", "operation": "get_interface_details", "params": {},
         "purpose": "check interfaces", "tests_hypotheses": [], "value": 0.8},
    ]
    eng = _engine(gw, candidates)
    session = _session("why is ospf down")

    eng._next_evidence_via_gateway(session, [], "", [], ["10.0.0.1"])

    assert gw.dispatched, "no operation was ever dispatched"
    _, _, params = gw.dispatched[0]
    assert params.get("protocol") == "ospf", params


def test_explicit_protocol_param_from_the_llm_is_never_overridden():
    gw = FakeGateway()
    candidates = [
        {"device": "10.0.0.1", "operation": "get_interface_details", "params": {"protocol": "hsrp"},
         "purpose": "check HSRP interfaces even though query mentions ospf",
         "tests_hypotheses": [], "value": 0.8},
    ]
    eng = _engine(gw, candidates)
    session = _session("why is ospf down")

    eng._next_evidence_via_gateway(session, [], "", [], ["10.0.0.1"])

    _, _, params = gw.dispatched[0]
    assert params.get("protocol") == "hsrp", params
