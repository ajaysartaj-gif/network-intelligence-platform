"""
Tests for expanded STP support (Phase 6a of the 6-protocol roadmap):
real "show spanning-tree" / "show interfaces status" adapter parsing,
closing a real pre-existing gap where STP's compiled signatures were
declared but unreachable (intent_engine.py's _detect_scenario() never
had "stp" in its keyword tuple, and no adapter ever parsed spanning-tree
output at all), plus a new, well-grounded ErrDisabled/BPDU-Guard
signature.
"""
import json
import sys
import types
from pathlib import Path

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.intent_engine import IntentEngine
from core.knowledge.compiler.failure_signatures import compile_failure_signatures
from core.knowledge.compiler.reasoning_artifact_compiler import ReasoningArtifactCompiler
from core.vendor import VendorGateway, Op, Operation, VendorProfile
from core.vendor.adapters.cisco_ios_like import IosLikeAdapter
from core.troubleshooting import TroubleshootingEngine, TSConfig, ResolutionStatus


class Dev:
    def __init__(self, ip, hostname="R1"):
        self.ip, self.hostname, self.device_type = ip, hostname, "cisco_ios"


_STP_TABLE = (
    "Interface        Role Sts Cost      Prio.Nbr Type\n"
    "---------------- ---- --- --------- -------- --------------------------------\n"
)
_STATUS_HEADER = "Port      Name               Status       Vlan       Duplex  Speed Type\n"


# ── keyword detection (the actual pre-existing bug this phase fixes) ────
def test_stp_is_a_detectable_scenario_keyword():
    """Regression test for a real, pre-existing bug: _detect_scenario()
    never had "stp" in its keyword tuple, so every STP compiled signature
    was unreachable via the live TroubleshootingEngine (which always goes
    through IntentEngine in production) despite being fully seeded in
    protocol_models.py/failure_signatures.py since the original NKC
    integration."""
    ie = IntentEngine.__new__(IntentEngine)
    assert ie._detect_scenario("why is the STP port stuck in Blocking state") == "stp"
    assert ie._detect_scenario("STP port err-disabled by BPDU guard") == "stp"


# ── failure signatures ───────────────────────────────────────────────────
def test_stp_signatures_include_blocking_and_errdisabled():
    sigs = compile_failure_signatures("stp")
    by_state = {s.stuck_state: s for s in sigs}
    assert set(by_state) == {"Blocking", "ErrDisabled"}
    # ErrDisabled is directly observed (an unambiguous status string), not
    # inferred like Blocking (which could legitimately be a healthy
    # redundant-path block) -- it earns higher confidence.
    assert by_state["ErrDisabled"].confidence > by_state["Blocking"].confidence


def test_stp_has_no_remediation_intent_for_errdisabled_by_design():
    """Deliberate safety scoping: blindly clearing a BPDU-Guard err-disable
    (shut/no-shut) could reintroduce a real bridging loop if a switch/hub
    really was plugged into an access port -- this stays a human decision,
    same principle as the platform's deliberate exclusion of auto-enabled
    debug/packet-capture."""
    templates = ReasoningArtifactCompiler().compile_remediation("stp")
    assert templates == []


# ── adapter parsing ──────────────────────────────────────────────────────
def test_adapter_parses_spanning_tree_roles_and_states():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    text = _STP_TABLE + "Gi0/1            Root FWD 4         128.1    P2p\nGi0/2            Desg BLK 4         128.2    P2p\n"
    objs = adapter.parse_output(Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "stp"}),
                                {"show spanning-tree": text}, profile)
    members = {o.id: o.attributes for o in objs if o.type == "neighbor"}
    assert members["Gi0/1"]["state"] == "FORWARDING"
    assert members["Gi0/1"]["role"] == "Root"
    assert members["Gi0/2"]["state"] == "BLOCKING"


def test_adapter_header_row_never_misparsed_as_a_port():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    text = _STP_TABLE + "Gi0/1            Root FWD 4         128.1    P2p\n"
    objs = adapter.parse_output(Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "stp"}),
                                {"show spanning-tree": text}, profile)
    ids = {o.id for o in objs if o.type == "neighbor"}
    assert ids == {"Gi0/1"}


def test_adapter_detects_errdisabled_only_from_interfaces_status():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    text = (_STATUS_HEADER +
           "Gi0/1                        connected    1          a-full  a-100 10/100/1000BaseTX\n"
           "Gi0/2                        notconnect   1          auto    auto  10/100/1000BaseTX\n"
           "Gi0/3                        err-disabled 10         auto    auto  10/100/1000BaseTX\n")
    objs = adapter.parse_output(Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "stp"}),
                                {"show interfaces status": text}, profile)
    members = {o.id: o.attributes for o in objs if o.type == "neighbor"}
    assert members == {"Gi0/3": {"protocol": "stp", "state": "ERRDISABLED"}}


# ── end-to-end ────────────────────────────────────────────────────────────
def _make_ai(query_state_word):
    calls = {"n": 0}

    def ai(prompt: str) -> str:
        if "Restate this network troubleshooting" in prompt:
            return f"Resolve the STP port stuck in {query_state_word} state."
        if "candidate ROOT CAUSES" in prompt:
            return json.dumps([])
        if "normalized diagnostic OPERATION" in prompt:
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps([{"device": "all", "operation": "get_interface_details",
                                    "params": {"protocol": "stp"}, "purpose": "diag",
                                    "tests_hypotheses": [], "value": 0.9}])
            return json.dumps([])
        if "Interpret this device output" in prompt:
            return json.dumps({"facts": [], "impacts": []})
        return ""
    return ai


def test_stp_errdisabled_identifies_cause_but_proposes_no_auto_fix():
    """High-confidence detection (a directly observed status, not an
    inference) but deliberately NO auto-remediation -- proves the
    end-to-end pipeline (seeding -> evidence-binding -> confidence) works
    for STP for the first time (it was unreachable before this phase),
    while also proving the safety scoping holds even at high confidence."""
    devices = [Dev("10.0.0.1")]
    status_text = (_STATUS_HEADER +
                   "Gi0/3                        err-disabled 10         auto    auto  10/100/1000BaseTX\n")
    gw = VendorGateway(send=lambda d, cmds: {c: status_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai("ErrDisabled"), devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why is the STP port err-disabled by BPDU guard")
    s = report.session
    top = s.top()
    assert top is not None
    assert top.confidence >= 0.8
    assert "BPDU Guard" in top.statement
    assert s.fix is None
    assert any("stp/ErrDisabled" in src for src in s.knowledge_sources)


def test_stp_blocking_now_reachable_via_real_evidence():
    """Regression test proving Blocking's compiled signature -- seeded
    since the original NKC integration but NEVER reachable because no
    adapter parsed "show spanning-tree" at all -- now genuinely binds to
    observed evidence."""
    devices = [Dev("10.0.0.1")]
    stp_text = _STP_TABLE + "Gi0/2            Desg BLK 4         128.2    P2p\n"
    gw = VendorGateway(send=lambda d, cmds: {c: stp_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai("Blocking"), devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why is the STP port stuck in Blocking state")
    s = report.session
    top = s.top()
    assert top is not None
    assert any(d.reason.startswith("deterministic-state-match") for d in top.deltas)
