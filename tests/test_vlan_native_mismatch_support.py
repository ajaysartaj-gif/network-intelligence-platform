"""
Tests for VLAN native-mismatch detection (Phase 6c of the 6-protocol
roadmap, completing the roadmap). Same reactive, no-FSM shape as ACL/NAT
(tests/test_acl_nat_support.py) -- see compile_vlan_native_mismatch_
signature()'s docstring (core/knowledge/compiler/failure_signatures.py)
for why this reads a direct CDP %CDP-4-NATIVE_VLAN_MISMATCH syslog line
instead of going through the existing cross-device Mismatch Investigation
machinery (which fundamentally requires a protocol-neighbor table to pair
devices, and a physical trunk link has none).
"""
import json
import sys
import types
from pathlib import Path

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.knowledge.compiler.failure_signatures import compile_vlan_native_mismatch_signature
from core.knowledge.compiler.reasoning_artifact_compiler import ReasoningArtifactCompiler
from core.vendor import VendorGateway, Op, Operation, VendorProfile
from core.vendor.adapters.cisco_ios_like import IosLikeAdapter
from core.vendor.models import NormalizedObject
from core.troubleshooting import TroubleshootingEngine, TSConfig
from core.troubleshooting.engine import TroubleshootingEngine as Engine
from core.troubleshooting.hypotheses import HypothesisManager, ConfidenceCalculator
from core.troubleshooting.models import Session, Goal


class Dev:
    def __init__(self, ip, hostname="R1"):
        self.ip, self.hostname, self.device_type = ip, hostname, "cisco_ios"


_MISMATCH_LOG = (
    "*Mar  1 00:15:23.456: %CDP-4-NATIVE_VLAN_MISMATCH: Native VLAN mismatch "
    "discovered on GigabitEthernet0/1 (1), with Switch2 GigabitEthernet0/1 (10).\n"
)


# ── adapter parsing ──────────────────────────────────────────────────────
def test_adapter_parses_cdp_native_vlan_mismatch_log_line():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    objs = adapter.parse_output(Operation(Op.COLLECT_EVIDENCE, {"protocol": "vlan"}),
                                {"show logging | include NATIVE_VLAN": _MISMATCH_LOG}, profile)
    o = next(o for o in objs if o.type == "vlan_native_mismatch")
    assert o.attributes == {
        "local_interface": "GigabitEthernet0/1", "local_vlan": "1",
        "remote_device": "Switch2", "remote_interface": "GigabitEthernet0/1",
        "remote_vlan": "10",
    }


def test_adapter_finds_nothing_when_no_mismatch_logged():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    objs = adapter.parse_output(Operation(Op.COLLECT_EVIDENCE, {"protocol": "vlan"}),
                                {"show logging | include NATIVE_VLAN": ""}, profile)
    assert not any(o.type == "vlan_native_mismatch" for o in objs)


def test_command_uses_collect_evidence_op():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    cmd = adapter.build_command(Operation(Op.COLLECT_EVIDENCE, {"protocol": "vlan"}), profile)
    assert cmd == ["show logging | include NATIVE_VLAN"]


# ── failure signature ────────────────────────────────────────────────────
def test_compile_vlan_native_mismatch_signature_reads_cdp_directly():
    objs = [NormalizedObject(type="vlan_native_mismatch", id="Gi0/1-Switch2", device="10.0.0.1",
                             attributes={"local_interface": "Gi0/1", "local_vlan": "1",
                                        "remote_device": "Switch2", "remote_interface": "Gi0/1",
                                        "remote_vlan": "10"})]
    sigs = compile_vlan_native_mismatch_signature(objs)
    assert len(sigs) == 1
    assert sigs[0].confidence == 0.95  # highest of the reactive (no-FSM) signatures
    assert "Switch2" in sigs[0].likely_cause


def test_vlan_native_mismatch_has_no_remediation_intent_by_design():
    assert ReasoningArtifactCompiler().compile_remediation("vlan") == []


# ── engine-level reactive binding (unit) ─────────────────────────────────
def test_engine_binds_vlan_mismatch_evidence_reactively():
    eng = Engine.__new__(Engine)
    eng.graph = type("G", (), {"add_observation": lambda self, o: None})()
    session = Session(goal=Goal(query="q", objective="o"))
    hmgr = HypothesisManager(session)
    conf = ConfidenceCalculator()
    output = ("vlan_native_mismatch[Gi0/1-Switch2]@10.0.0.1 {local_interface=Gi0/1, "
             "local_vlan=1, remote_device=Switch2, remote_interface=Gi0/1, remote_vlan=10}")
    eng._bind_vlan_native_mismatch_evidence(output, "10.0.0.1", "show logging", session, hmgr, conf)
    assert len(session.hypotheses) == 1
    assert session.hypotheses[0].confidence > 0.95


# ── end-to-end ────────────────────────────────────────────────────────────
def _make_ai():
    calls = {"n": 0}

    def ai(prompt: str) -> str:
        if "Restate this network troubleshooting" in prompt:
            return "Investigate the VLAN native VLAN mismatch on the trunk."
        if "candidate ROOT CAUSES" in prompt:
            return json.dumps([])
        if "normalized diagnostic OPERATION" in prompt:
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps([{"device": "all", "operation": "collect_evidence",
                                    "params": {"protocol": "vlan"}, "purpose": "diag",
                                    "tests_hypotheses": [], "value": 0.9}])
            return json.dumps([])
        if "Interpret this device output" in prompt:
            return json.dumps({"facts": [], "impacts": []})
        return ""
    return ai


def test_vlan_mismatch_identifies_cause_end_to_end_but_proposes_no_auto_fix():
    """High confidence (CDP's OWN detection, not our inference) but
    deliberately no auto-remediation -- which side is misconfigured is a
    judgment call that stays with a human, same principle as ACL/NAT/
    STP's ErrDisabled."""
    devices = [Dev("10.0.0.1")]
    gw = VendorGateway(send=lambda d, cmds: {c: _MISMATCH_LOG for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai(), devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why is there a VLAN native vlan mismatch on the trunk")
    s = report.session
    top = s.top()
    assert top is not None
    assert top.confidence >= 0.9
    assert "Switch2" in top.statement
    assert s.fix is None
    assert any("VLAN signature" in src for src in s.knowledge_sources)


def test_vlan_healthy_no_mismatch_logged_seeds_nothing():
    devices = [Dev("10.0.0.1")]
    gw = VendorGateway(send=lambda d, cmds: {c: "" for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai(), devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why is there a VLAN native vlan mismatch on the trunk")
    assert report.session.top() is None
