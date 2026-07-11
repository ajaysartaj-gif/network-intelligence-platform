"""
Tests for HSRP support (Phase 4 of the 6-protocol roadmap, following the
OSPF/BGP/LACP pattern): compiled protocol model, failure signatures,
adapter parsing of real "show standby brief" output, and end-to-end
remediation via the live TroubleshootingEngine.
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


_STANDBY_BRIEF_HEADER = (
    "                     P indicates configured to preempt.\n"
    "                     |\n"
    "Interface   Grp Prio P State   Active address  Standby address Group addr\n"
)


# ── protocol model ────────────────────────────────────────────────────────
def test_hsrp_protocol_model_round_trips_init_to_active():
    model = build_protocol_model("hsrp")
    assert model is not None
    assert model.states == ["Init", "Learn", "Listen", "Speak", "Standby", "Active"]
    assert model.is_valid_transition("Listen", "Speak")
    assert model.is_valid_transition("Speak", "Active")
    assert model.is_valid_transition("Standby", "Active")
    assert not model.is_valid_transition("Init", "Active")  # no direct jump


# ── failure signatures ───────────────────────────────────────────────────
def test_hsrp_signatures_four_states_honest_confidence():
    sigs = compile_failure_signatures("hsrp")
    by_state = {s.stuck_state: s for s in sigs}
    assert set(by_state) == {"Init", "Listen", "Speak", "Standby"}
    # Listen (VLAN/ACL blocking hellos -- the most commonly cited real
    # cause of a router that never even hears a peer) must outrank the
    # generic Init.
    assert by_state["Listen"].confidence > by_state["Init"].confidence
    # Standby's "missing preempt" cause is well-documented enough to match
    # BGP's Active / LACP's Individual confidence tier.
    assert by_state["Standby"].confidence >= 0.7


# ── adapter parsing (adversarial: optional "P" column shifts alignment) ──
def test_adapter_parses_standby_brief_with_and_without_preempt_flag():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    text = (_STANDBY_BRIEF_HEADER +
           "Gi0/1       1   110  P Active  local           10.0.0.2        10.0.0.254\n"
           "Gi0/2       2   100    Standby 10.0.0.1        local            10.0.0.253\n")
    objs = adapter.parse_output(Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "hsrp"}),
                                {"show standby brief": text}, profile)
    members = {o.id: o.attributes for o in objs if o.type == "neighbor"}
    assert members["Gi0/1:1"]["state"] == "ACTIVE"
    assert members["Gi0/1:1"]["preempt_configured"] == "true"
    assert members["Gi0/2:2"]["state"] == "STANDBY"
    assert members["Gi0/2:2"]["preempt_configured"] == "false"


def test_adapter_header_and_comment_rows_never_misparsed_as_a_group():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    text = _STANDBY_BRIEF_HEADER + "Gi0/1       1   110  P Active  local           10.0.0.2        10.0.0.254\n"
    objs = adapter.parse_output(Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "hsrp"}),
                                {"show standby brief": text}, profile)
    ids = {o.id for o in objs if o.type == "neighbor"}
    assert ids == {"Gi0/1:1"}


def test_adapter_hsrp_remediation_recipe():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    intent = RemediationIntent(name="add_hsrp_preempt",
                               params={"protocol": "hsrp", "neighbor_ip": "Gi0/2:2"})
    assert adapter.build_fix(intent, profile) == ["interface Gi0/2", "standby 2 preempt"]
    assert adapter.build_rollback(intent, profile) == ["interface Gi0/2", "no standby 2 preempt"]
    assert adapter.build_verification(intent, profile) == ["show standby brief"]
    assert adapter.supports_intent("add_hsrp_preempt", profile)


# ── end-to-end: HSRP stuck in Standby converges to a real fix ───────────
def _make_ai(query_state_word):
    calls = {"n": 0}

    def ai(prompt: str) -> str:
        if "Restate this network troubleshooting" in prompt:
            return f"Resolve the HSRP router stuck in {query_state_word} state and not taking over."
        if "candidate ROOT CAUSES" in prompt:
            return json.dumps([])
        if "normalized diagnostic OPERATION" in prompt:
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps([{"device": "all", "operation": "get_interface_details",
                                    "params": {"protocol": "hsrp"}, "purpose": "diag",
                                    "tests_hypotheses": [], "value": 0.9}])
            return json.dumps([])
        if "Interpret this device output" in prompt:
            return json.dumps({"facts": [], "impacts": []})
        return ""
    return ai


def test_hsrp_standby_converges_to_real_vendor_fix_end_to_end():
    """Mirrors the OSPF/BGP/LACP validation methodology: reproduces a live
    'HSRP stuck in Standby, not taking over' scenario through the real
    TroubleshootingEngine, proving seeding -> evidence-binding -> confidence
    convergence -> compiled remediation lookup -> real vendor-syntax fix
    all work together."""
    devices = [Dev("10.0.0.1")]
    standby_text = (_STANDBY_BRIEF_HEADER +
                    "Gi0/1       1   100    Standby 10.0.0.9        local            10.0.0.254\n")
    gw = VendorGateway(send=lambda d, cmds: {c: standby_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai("Standby"), devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why is the HSRP router stuck in Standby state and not taking over")
    s = report.session

    assert s.status == ResolutionStatus.RESOLVED_PENDING_APPROVAL, s.status
    top = s.top()
    assert top.confidence >= 0.8
    assert "preempt" in top.statement
    assert s.fix is not None
    assert s.fix.config_commands == ["interface Gi0/1", "standby 1 preempt"]
    assert s.fix.rollback_commands == ["interface Gi0/1", "no standby 1 preempt"]
    assert s.verification.commands == ["show standby brief"]
    assert any("hsrp/Standby" in src for src in s.knowledge_sources)


def test_hsrp_listen_stays_below_convergence_threshold_honest_uncertainty():
    """Listen has no mapped remediation intent at all (too many possible
    causes -- VLAN, trunk, ACL -- to safely auto-fix without more specific
    evidence), matching the same honest partial-coverage scoping every
    other protocol in this package uses."""
    devices = [Dev("10.0.0.1")]
    listen_text = (_STANDBY_BRIEF_HEADER +
                   "Gi0/1       1   100    Listen  unknown         unknown          10.0.0.254\n")
    gw = VendorGateway(send=lambda d, cmds: {c: listen_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai("Listen"), devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why is the HSRP router stuck in Listen state")
    s = report.session
    assert s.fix is None
