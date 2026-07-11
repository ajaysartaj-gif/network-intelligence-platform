"""
Tests for VRRP support (Phase 5 of the 6-protocol roadmap, following the
OSPF/BGP/LACP/HSRP pattern): compiled protocol model, failure signatures,
adapter parsing of real "show vrrp brief" output, and end-to-end
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


_VRRP_BRIEF_HEADER = "Interface  Grp Pri Time  Own Pre State   Master addr     Group addr\n"


# ── protocol model ────────────────────────────────────────────────────────
def test_vrrp_protocol_model_round_trips_initialize_to_master():
    model = build_protocol_model("vrrp")
    assert model is not None
    assert model.states == ["Initialize", "Backup", "Master"]
    assert model.is_valid_transition("Initialize", "Master")
    assert model.is_valid_transition("Backup", "Master")
    assert model.is_valid_transition("Master", "Backup")  # preemption regression edge
    assert model.is_valid_transition("Initialize", "Backup")
    assert not model.is_valid_transition("Master", "Master")  # no self-loop modeled


# ── failure signatures ───────────────────────────────────────────────────
def test_vrrp_signatures_two_states_honest_confidence():
    sigs = compile_failure_signatures("vrrp")
    by_state = {s.stuck_state: s for s in sigs}
    assert set(by_state) == {"Initialize", "Backup"}
    assert by_state["Backup"].confidence > by_state["Initialize"].confidence
    # "no preempt" is well-documented enough to match BGP's Active / LACP's
    # Individual / HSRP's Standby confidence tier.
    assert by_state["Backup"].confidence >= 0.7


# ── adapter parsing (adversarial: Own/Pre Y/N columns, header never misparsed) ──
def test_adapter_parses_vrrp_brief_own_and_preempt_columns():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    text = (_VRRP_BRIEF_HEADER +
           "Gi0/1      1   150 3609  N   N   Backup  10.0.0.9        10.0.0.10\n"
           "Gi0/2      2   100 3609  N   Y   Master  local            10.0.0.11\n")
    objs = adapter.parse_output(Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "vrrp"}),
                                {"show vrrp brief": text}, profile)
    members = {o.id: o.attributes for o in objs if o.type == "neighbor"}
    assert members["Gi0/1:1"]["state"] == "BACKUP"
    assert members["Gi0/1:1"]["preempt_enabled"] == "false"
    assert members["Gi0/2:2"]["state"] == "MASTER"
    assert members["Gi0/2:2"]["preempt_enabled"] == "true"


def test_adapter_header_row_never_misparsed_as_a_group():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    text = _VRRP_BRIEF_HEADER + "Gi0/1      1   150 3609  N   N   Backup  10.0.0.9        10.0.0.10\n"
    objs = adapter.parse_output(Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "vrrp"}),
                                {"show vrrp brief": text}, profile)
    ids = {o.id for o in objs if o.type == "neighbor"}
    assert ids == {"Gi0/1:1"}


def test_adapter_vrrp_remediation_recipe():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    intent = RemediationIntent(name="enable_vrrp_preempt",
                               params={"protocol": "vrrp", "neighbor_ip": "Gi0/1:1"})
    assert adapter.build_fix(intent, profile) == ["interface Gi0/1", "vrrp 1 preempt"]
    assert adapter.build_rollback(intent, profile) == ["interface Gi0/1", "no vrrp 1 preempt"]
    assert adapter.build_verification(intent, profile) == ["show vrrp brief"]
    assert adapter.supports_intent("enable_vrrp_preempt", profile)


# ── end-to-end: VRRP stuck in Backup converges to a real fix ────────────
def _make_ai(query_state_word):
    calls = {"n": 0}

    def ai(prompt: str) -> str:
        if "Restate this network troubleshooting" in prompt:
            return f"Resolve the VRRP router stuck in {query_state_word} state and not taking over."
        if "candidate ROOT CAUSES" in prompt:
            return json.dumps([])
        if "normalized diagnostic OPERATION" in prompt:
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps([{"device": "all", "operation": "get_interface_details",
                                    "params": {"protocol": "vrrp"}, "purpose": "diag",
                                    "tests_hypotheses": [], "value": 0.9}])
            return json.dumps([])
        if "Interpret this device output" in prompt:
            return json.dumps({"facts": [], "impacts": []})
        return ""
    return ai


def test_vrrp_backup_converges_to_real_vendor_fix_end_to_end():
    """Mirrors the OSPF/BGP/LACP/HSRP validation methodology: reproduces a
    live 'VRRP stuck in Backup, not taking over' scenario through the real
    TroubleshootingEngine, proving seeding -> evidence-binding -> confidence
    convergence -> compiled remediation lookup -> real vendor-syntax fix
    all work together."""
    devices = [Dev("10.0.0.1")]
    backup_text = (_VRRP_BRIEF_HEADER +
                  "Gi0/1      1   150 3609  N   N   Backup  10.0.0.9        10.0.0.10\n")
    gw = VendorGateway(send=lambda d, cmds: {c: backup_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai("Backup"), devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why is the VRRP router stuck in Backup state and not taking over")
    s = report.session

    assert s.status == ResolutionStatus.RESOLVED_PENDING_APPROVAL, s.status
    top = s.top()
    assert top.confidence >= 0.8
    assert "preempt" in top.statement
    assert s.fix is not None
    assert s.fix.config_commands == ["interface Gi0/1", "vrrp 1 preempt"]
    assert s.fix.rollback_commands == ["interface Gi0/1", "no vrrp 1 preempt"]
    assert s.verification.commands == ["show vrrp brief"]
    assert any("vrrp/Backup" in src for src in s.knowledge_sources)


def test_vrrp_initialize_stays_below_convergence_threshold_honest_uncertainty():
    """Initialize has no mapped remediation intent (too many possible
    causes -- interface down, VRRP disabled, no usable IP -- to safely
    auto-fix), matching the same honest partial-coverage scoping every
    other protocol in this package uses."""
    devices = [Dev("10.0.0.1")]
    init_text = (_VRRP_BRIEF_HEADER +
                "Gi0/1      1   100 3609  N   Y   Initialize unknown        10.0.0.10\n")
    gw = VendorGateway(send=lambda d, cmds: {c: init_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai("Initialize"), devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why is the VRRP router stuck in Initialize state")
    s = report.session
    assert s.fix is None
