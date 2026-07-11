"""
Tests for LACP support (Phase 3 of 6 protocols added following the OSPF/BGP
pattern): compiled protocol model, failure signatures, adapter parsing of
real "show etherchannel summary" output, and end-to-end remediation via the
live TroubleshootingEngine.
"""
import json
import sys
import types
from pathlib import Path

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.knowledge.compiler.protocol_models import build_protocol_model
from core.knowledge.compiler.failure_signatures import compile_failure_signatures
from core.vendor import VendorGateway, Op, Operation, VendorProfile
from core.vendor.adapters.cisco_ios_like import IosLikeAdapter
from core.vendor.operations import RemediationIntent
from core.troubleshooting import TroubleshootingEngine, TSConfig, ResolutionStatus


class Dev:
    def __init__(self, ip, hostname="R1"):
        self.ip, self.hostname, self.device_type = ip, hostname, "cisco_ios"


_ETHERCHANNEL_FLAGS_HEADER = (
    "Flags:  D - down        P - bundled in port-channel\n"
    "        I - stand-alone s - suspended\n"
    "        H - Hot-standby (LACP only)\n"
    "        R - Layer3      S - Layer2\n"
    "        U - in use      f - failed to allocate aggregator\n\n"
    "        M - not in use, minimum links not met\n"
    "        u - unsuitable for bundling\n"
    "        w - waiting to be aggregated\n"
    "        d - default port\n\n"
    "Number of channel-groups in use: 1\n"
    "Number of aggregators:           1\n\n"
    "Group  Port-channel  Protocol    Ports\n"
    "------+-------------+-----------+-----------------------------------------------\n"
)


# ── protocol model ────────────────────────────────────────────────────────
def test_lacp_protocol_model_round_trips_down_to_bundled():
    model = build_protocol_model("lacp")
    assert model is not None
    assert model.states == ["Down", "Individual", "Suspended", "Bundled"]
    assert model.is_valid_transition("Down", "Individual")
    assert model.is_valid_transition("Individual", "Bundled")
    assert model.is_valid_transition("Down", "Bundled")  # immediate successful negotiation
    assert not model.is_valid_transition("Suspended", "Down")  # not a modeled direct edge


# ── failure signatures ───────────────────────────────────────────────────
def test_lacp_signatures_three_states_honest_confidence():
    sigs = compile_failure_signatures("lacp")
    by_state = {s.stuck_state: s for s in sigs}
    assert set(by_state) == {"Individual", "Suspended", "Down"}
    # Individual (LACPDU/mode mismatch — the most commonly reported real
    # cause) must outrank Suspended, which must outrank the generic Down.
    assert by_state["Individual"].confidence > by_state["Suspended"].confidence
    assert by_state["Suspended"].confidence > by_state["Down"].confidence


# ── adapter parsing (adversarial: container flags vs member flags) ───────
def test_adapter_distinguishes_container_flags_from_member_flags():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    text = _ETHERCHANNEL_FLAGS_HEADER + "1      Po1(SU)         LACP      Gi0/1(P)    Gi0/2(I)\n"
    objs = adapter.parse_output(Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "lacp"}),
                                {"show etherchannel summary": text}, profile)
    members = {o.id: o.attributes["state"] for o in objs if o.type == "neighbor"}
    assert members == {"Gi0/1": "BUNDLED", "Gi0/2": "INDIVIDUAL"}
    # The Port-channel container itself ("Po1", multi-letter "SU" flags —
    # a DIFFERENT vocabulary, Layer2/in-use, not a member bundling state)
    # must never be misread as a member port.
    assert "Po1" not in members


def test_adapter_skips_unmodeled_flags_and_reads_multiple_groups():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    # Gi0/1(H) is Hot-standby — not in the observable Down/Individual/
    # Suspended/Bundled vocabulary this model scopes to — must be skipped,
    # not guessed at, same "never fabricate" discipline as every other
    # unmodeled-flag case in this adapter.
    text = (_ETHERCHANNEL_FLAGS_HEADER +
           "1      Po1(SU)         LACP      Gi0/1(H)    Gi0/2(s)\n"
           "2      Po2(SD)         LACP      Gi0/3(D)\n")
    objs = adapter.parse_output(Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "lacp"}),
                                {"show etherchannel summary": text}, profile)
    members = {o.id: o.attributes["state"] for o in objs if o.type == "neighbor"}
    assert members == {"Gi0/2": "SUSPENDED", "Gi0/3": "DOWN"}
    assert "Gi0/1" not in members


def test_adapter_lacp_remediation_recipe():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    intent = RemediationIntent(name="set_lacp_mode_active",
                               params={"protocol": "lacp", "neighbor_ip": "Gi0/1"})
    assert adapter.build_fix(intent, profile) == ["interface Gi0/1", "channel-group 1 mode active"]
    assert adapter.build_rollback(intent, profile) == ["interface Gi0/1", "no channel-group 1 mode active"]
    assert adapter.build_verification(intent, profile) == ["show etherchannel summary"]
    assert adapter.supports_intent("set_lacp_mode_active", profile)


# ── end-to-end: LACP port stuck in Individual converges to a real fix ────
def _make_ai(query_state_word):
    calls = {"n": 0}

    def ai(prompt: str) -> str:
        if "Restate this network troubleshooting" in prompt:
            return f"Resolve the LACP port stuck in {query_state_word} state."
        if "candidate ROOT CAUSES" in prompt:
            return json.dumps([])
        if "normalized diagnostic OPERATION" in prompt:
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps([{"device": "all", "operation": "get_interface_details",
                                    "params": {"protocol": "lacp"}, "purpose": "diag",
                                    "tests_hypotheses": [], "value": 0.9}])
            return json.dumps([])
        if "Interpret this device output" in prompt:
            return json.dumps({"facts": [], "impacts": []})
        return ""
    return ai


def test_lacp_individual_converges_to_real_vendor_fix_end_to_end():
    """Mirrors the OSPF/BGP validation methodology: reproduces a live 'LACP
    port stuck in Individual' scenario through the real
    TroubleshootingEngine, proving seeding -> evidence-binding -> confidence
    convergence -> compiled remediation lookup -> real vendor-syntax fix
    all work together, not just that a signature dict has the right shape."""
    devices = [Dev("10.0.0.1")]
    individual_text = (_ETHERCHANNEL_FLAGS_HEADER +
                       "1      Po1(SU)         LACP      Gi0/1(I)\n")
    gw = VendorGateway(send=lambda d, cmds: {c: individual_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai("Individual"), devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why is the LACP port stuck in Individual state")
    s = report.session

    assert s.status == ResolutionStatus.RESOLVED_PENDING_APPROVAL, s.status
    top = s.top()
    assert top.confidence >= 0.8
    assert "LACPDUs" in top.statement
    assert s.fix is not None
    assert s.fix.config_commands == ["interface Gi0/1", "channel-group 1 mode active"]
    assert s.fix.rollback_commands == ["interface Gi0/1", "no channel-group 1 mode active"]
    assert s.verification.commands == ["show etherchannel summary"]
    assert any("lacp/Individual" in src for src in s.knowledge_sources)


def test_lacp_suspended_stays_below_convergence_threshold_honest_uncertainty():
    """Suspended's compiled confidence (0.65) is deliberately lower than
    Individual's (0.75) because too many distinct parameters (VLAN/trunk/
    STP) could be mismatched to pin down without more specific evidence --
    and it has no mapped remediation intent at all, matching OSPF's/BGP's
    own honest partial-coverage scoping for ambiguous stuck states."""
    devices = [Dev("10.0.0.1")]
    suspended_text = (_ETHERCHANNEL_FLAGS_HEADER +
                      "1      Po1(SU)         LACP      Gi0/1(s)\n")
    gw = VendorGateway(send=lambda d, cmds: {c: suspended_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai("Suspended"), devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why is the LACP port stuck in Suspended state")
    s = report.session
    assert s.status == ResolutionStatus.LIKELY_CAUSE_PRESENT, s.status
    assert s.fix is None
