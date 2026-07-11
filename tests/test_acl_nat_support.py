"""
Tests for ACL deny-hit and NAT interface-role detection (Phase 6b of the
6-protocol roadmap). Both are a deliberately DIFFERENT shape from every
FSM-based protocol above (BGP/LACP/HSRP/VRRP/STP): there's no protocol
state model for a firewall rule or a NAT role, so there's no "prior to
seed before evidence exists" -- the deny rule / missing NAT role IS the
evidence, reactively bound the moment real config output is observed
(engine.py's generic _bind_reactive_evidence). Neither
gets a remediation intent, by design: auto-editing a security ACL or
guessing which interface should be NAT inside/outside is a genuine safety
risk, the same principle behind STP's ErrDisabled having no auto-fix.
"""
import json
import sys
import types
from pathlib import Path

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.knowledge.compiler.failure_signatures import (
    compile_acl_deny_signature, compile_nat_role_signature,
)
from core.knowledge.compiler.protocol_registry import PROTOCOL_SPECS
from core.knowledge.compiler.reasoning_artifact_compiler import ReasoningArtifactCompiler
from core.vendor import VendorGateway, Op, Operation, VendorProfile
from core.vendor.adapters.cisco_ios_like import IosLikeAdapter
from core.vendor.models import NormalizedObject
from core.troubleshooting import TroubleshootingEngine, TSConfig, ResolutionStatus
from core.troubleshooting.engine import TroubleshootingEngine as Engine
from core.troubleshooting.hypotheses import HypothesisManager, ConfidenceCalculator
from core.troubleshooting.models import Session, Goal


class Dev:
    def __init__(self, ip, hostname="R1"):
        self.ip, self.hostname, self.device_type = ip, hostname, "cisco_ios"


# ── ACL adapter parsing ───────────────────────────────────────────────────
def test_adapter_parses_acl_deny_and_permit_rules():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    text = ("Extended IP access list ACL_IN\n"
           "    10 deny   ip 10.0.0.0 0.0.0.255 any (15 matches)\n"
           "    20 permit ip any any (1200 matches)\n")
    objs = adapter.parse_output(Operation(Op.GET_CONFIGURATION, {"protocol": "acl"}),
                                {"show access-lists": text}, profile)
    by_id = {o.id: o.attributes for o in objs if o.type == "acl"}
    assert by_id["ACL_IN-10"]["action"] == "deny"
    assert by_id["ACL_IN-20"]["action"] == "permit"


def test_adapter_acl_rule_comma_survives_summary_round_trip():
    """Standard ACL rule text legitimately contains a literal comma
    ("192.168.1.0, wildcard bits ..."), which would otherwise be silently
    truncated by NormalizedObject.summary()'s ", "-joined key=value text
    and its regex-based re-parse in engine.py's _bind_reactive_evidence."""
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    text = "Standard IP access list 10\n    10 deny 192.168.1.0, wildcard bits 0.0.0.255 (2 matches)\n"
    objs = adapter.parse_output(Operation(Op.GET_CONFIGURATION, {"protocol": "acl"}),
                                {"show access-lists": text}, profile)
    o = next(o for o in objs if o.type == "acl")
    assert "," not in o.attributes["rule"]  # normalized before it can ever reach summary()
    # round-trip through the SAME regex engine.py uses -- the rule's OWN
    # comma must not fragment across kv's ", "-joined pairs.
    m = Engine._GATEWAY_OBJ_LINE.match(o.summary())
    assert m is not None
    kv = dict(p.split("=", 1) for p in m.group("kv").split(", ") if "=" in p)
    assert "wildcard bits" in kv["rule"]


# ── ACL failure signature ─────────────────────────────────────────────────
def test_compile_acl_deny_signature_reads_deny_rules_directly():
    objs = [
        NormalizedObject(type="acl", id="ACL_IN-10", device="10.0.0.1",
                        attributes={"acl_name": "ACL_IN", "action": "deny", "rule": "ip any any"}),
        NormalizedObject(type="acl", id="ACL_IN-20", device="10.0.0.1",
                        attributes={"acl_name": "ACL_IN", "action": "permit", "rule": "ip any any"}),
    ]
    sigs = compile_acl_deny_signature(objs)
    assert len(sigs) == 1
    assert sigs[0].confidence == 0.9
    assert "ACL_IN" in sigs[0].likely_cause


def test_acl_has_no_remediation_intent_by_design():
    assert ReasoningArtifactCompiler().compile_remediation("acl") == []


# ── NAT adapter parsing ───────────────────────────────────────────────────
def test_adapter_parses_nat_statistics_both_roles_present():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    text = ("Total active translations: 3 (2 static, 1 dynamic; 0 extended)\n"
           "Outside interfaces:\n  GigabitEthernet0/0\n"
           "Inside interfaces:\n  GigabitEthernet0/1\n"
           "Hits: 245  Misses: 3\n")
    objs = adapter.parse_output(Operation(Op.GET_CONFIGURATION, {"protocol": "nat"}),
                                {"show ip nat statistics": text}, profile)
    nat_obj = next(o for o in objs if o.type == "nat")
    assert nat_obj.attributes == {"inside_count": 1, "outside_count": 1, "hits": "245", "misses": "3"}


def test_adapter_parses_nat_statistics_missing_inside_role():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    text = ("Total active translations: 0 (0 static, 0 dynamic; 0 extended)\n"
           "Outside interfaces:\n  GigabitEthernet0/0\n"
           "Inside interfaces:\n"
           "Hits: 0  Misses: 128\n")
    objs = adapter.parse_output(Operation(Op.GET_CONFIGURATION, {"protocol": "nat"}),
                                {"show ip nat statistics": text}, profile)
    nat_obj = next(o for o in objs if o.type == "nat")
    assert nat_obj.attributes["inside_count"] == 0
    assert nat_obj.attributes["outside_count"] == 1


# ── NAT failure signature ─────────────────────────────────────────────────
def test_compile_nat_role_signature_flags_missing_role_only():
    objs = [NormalizedObject(type="nat", id="nat", device="10.0.0.1",
                             attributes={"inside_count": 0, "outside_count": 1})]
    sigs = compile_nat_role_signature(objs)
    assert len(sigs) == 1
    assert sigs[0].stuck_state == "no_inside_interface"
    assert sigs[0].confidence == 0.85


def test_compile_nat_role_signature_healthy_config_flags_nothing():
    objs = [NormalizedObject(type="nat", id="nat", device="10.0.0.1",
                             attributes={"inside_count": 1, "outside_count": 1})]
    assert compile_nat_role_signature(objs) == []


def test_nat_has_no_remediation_intent_by_design():
    assert ReasoningArtifactCompiler().compile_remediation("nat") == []


# ── engine-level reactive binding (unit) ─────────────────────────────────
def test_engine_binds_acl_deny_evidence_reactively():
    eng = Engine.__new__(Engine)
    eng.graph = type("G", (), {"add_observation": lambda self, o: None})()
    session = Session(goal=Goal(query="q", objective="o"))
    hmgr = HypothesisManager(session)
    conf = ConfidenceCalculator()
    output = ("acl[ACL_IN-10]@10.0.0.1 {acl_name=ACL_IN, action=deny, rule=ip 10.0.0.0 0.0.0.255 any}\n"
             "acl[ACL_IN-20]@10.0.0.1 {acl_name=ACL_IN, action=permit, rule=ip any any}")
    eng._bind_reactive_evidence(PROTOCOL_SPECS["acl"], output, "10.0.0.1", "show access-lists",
                                session, hmgr, conf)
    assert len(session.hypotheses) == 1
    assert session.hypotheses[0].confidence > 0.9


def test_engine_binds_nat_role_evidence_reactively():
    eng = Engine.__new__(Engine)
    eng.graph = type("G", (), {"add_observation": lambda self, o: None})()
    session = Session(goal=Goal(query="q", objective="o"))
    hmgr = HypothesisManager(session)
    conf = ConfidenceCalculator()
    output = "nat[nat]@10.0.0.1 {inside_count=0, outside_count=1, hits=0, misses=128}"
    eng._bind_reactive_evidence(PROTOCOL_SPECS["nat"], output, "10.0.0.1", "show ip nat statistics",
                                session, hmgr, conf)
    assert len(session.hypotheses) == 1
    assert "ip nat inside" in session.hypotheses[0].statement


# ── end-to-end ────────────────────────────────────────────────────────────
def _make_ai(proto, restate):
    calls = {"n": 0}

    def ai(prompt: str) -> str:
        if "Restate this network troubleshooting" in prompt:
            return restate
        if "candidate ROOT CAUSES" in prompt:
            return json.dumps([])
        if "normalized diagnostic OPERATION" in prompt:
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps([{"device": "all", "operation": "get_configuration",
                                    "params": {"protocol": proto}, "purpose": "diag",
                                    "tests_hypotheses": [], "value": 0.9}])
            return json.dumps([])
        if "Interpret this device output" in prompt:
            return json.dumps({"facts": [], "impacts": []})
        return ""
    return ai


def test_acl_deny_identifies_cause_end_to_end_but_proposes_no_auto_fix():
    devices = [Dev("10.0.0.1")]
    acl_text = ("Extended IP access list ACL_IN\n"
               "    10 deny   ip 10.0.0.0 0.0.0.255 any (15 matches)\n"
               "    20 permit ip any any (1200 matches)\n")
    gw = VendorGateway(send=lambda d, cmds: {c: acl_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai("acl", "Investigate the ACL denying traffic."),
                                devices=devices, gateway=gw, config=TSConfig(max_steps=6))
    report = eng.run("why is traffic being denied, check the ACL")
    s = report.session
    top = s.top()
    assert top is not None
    assert "ACL_IN" in top.statement
    assert s.fix is None
    assert any("ACL deny signature" in src for src in s.knowledge_sources)


def test_acl_healthy_permit_only_seeds_nothing():
    devices = [Dev("10.0.0.1")]
    acl_text = "Extended IP access list ACL_IN\n    10 permit ip any any (1200 matches)\n"
    gw = VendorGateway(send=lambda d, cmds: {c: acl_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai("acl", "Investigate the ACL denying traffic."),
                                devices=devices, gateway=gw, config=TSConfig(max_steps=6))
    report = eng.run("why is traffic being denied, check the ACL")
    assert report.session.top() is None


def test_nat_missing_inside_role_identifies_cause_end_to_end_but_proposes_no_auto_fix():
    devices = [Dev("10.0.0.1")]
    nat_text = ("Total active translations: 0 (0 static, 0 dynamic; 0 extended)\n"
               "Outside interfaces:\n  GigabitEthernet0/0\n"
               "Inside interfaces:\n"
               "Hits: 0  Misses: 128\n")
    gw = VendorGateway(send=lambda d, cmds: {c: nat_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai("nat", "Investigate NAT translation."),
                                devices=devices, gateway=gw, config=TSConfig(max_steps=6))
    report = eng.run("why is NAT not translating traffic, check ip nat")
    s = report.session
    top = s.top()
    assert top is not None
    assert "ip nat inside" in top.statement
    assert s.fix is None


def test_nat_healthy_both_roles_seeds_nothing():
    devices = [Dev("10.0.0.1")]
    nat_text = ("Total active translations: 3 (2 static, 1 dynamic; 0 extended)\n"
               "Outside interfaces:\n  GigabitEthernet0/0\n"
               "Inside interfaces:\n  GigabitEthernet0/1\n"
               "Hits: 245  Misses: 3\n")
    gw = VendorGateway(send=lambda d, cmds: {c: nat_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai("nat", "Investigate NAT translation."),
                                devices=devices, gateway=gw, config=TSConfig(max_steps=6))
    report = eng.run("why is NAT not translating traffic, check ip nat")
    assert report.session.top() is None
