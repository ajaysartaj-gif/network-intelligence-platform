"""
Tests for BGP support (Phase 1 of 6 protocols added following the OSPF
pattern): compiled protocol model, failure signatures, adapter parsing,
and end-to-end remediation via the live TroubleshootingEngine.
"""
import json
import re
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


_BGP_SUMMARY_TEXT = (
    "BGP router identifier 1.1.1.1, local AS number 65001\n"
    "BGP table version is 5, main routing table version 5\n\n"
    "Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ  Up/Down  State/PfxRcd\n"
    "10.0.0.2        4        65002       10       10        5    0    0 00:05:23        3\n"
    "10.0.0.3        4        65003        0        0        0    0    0 never    Active\n"
)


# ── protocol model ────────────────────────────────────────────────────────
def test_bgp_protocol_model_round_trips_idle_to_established():
    model = build_protocol_model("bgp")
    assert model is not None
    assert model.states == ["Idle", "Connect", "Active", "OpenSent", "OpenConfirm", "Established"]
    assert model.is_valid_transition("Idle", "Connect")
    assert model.is_valid_transition("OpenConfirm", "Established")
    assert not model.is_valid_transition("Idle", "Established")  # no direct jump


# ── failure signatures ───────────────────────────────────────────────────
def test_bgp_signatures_five_states_honest_confidence():
    sigs = compile_failure_signatures("bgp")
    by_state = {s.stuck_state: s for s in sigs}
    assert set(by_state) == {"Idle", "Connect", "Active", "OpenSent", "OpenConfirm"}
    # Active (repeated TCP failures -- the most commonly reported real cause)
    # must outrank Idle (genuinely ambiguous: admin shutdown vs no route).
    assert by_state["Active"].confidence > by_state["Idle"].confidence


# ── adapter parsing (adversarial: digit vs literal-state-name column) ────
def test_adapter_disambiguates_established_count_from_literal_state():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.1"})
    objs = adapter.parse_output(Operation(Op.GET_NEIGHBORS, {"protocol": "bgp"}),
                                {"show ip bgp summary": _BGP_SUMMARY_TEXT}, profile)
    neighbors = {o.id: o.attributes for o in objs if o.type == "neighbor"}
    assert neighbors["10.0.0.2"]["state"] == "ESTABLISHED"  # digit column (PfxRcd=3)
    assert neighbors["10.0.0.3"]["state"] == "ACTIVE"        # literal state name
    assert neighbors["10.0.0.2"]["remote_as"] == "65002"


def test_adapter_header_row_never_misparsed_as_a_neighbor():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.1"})
    objs = adapter.parse_output(Operation(Op.GET_NEIGHBORS, {"protocol": "bgp"}),
                                {"show ip bgp summary": _BGP_SUMMARY_TEXT}, profile)
    neighbor_ids = {o.id for o in objs if o.type == "neighbor"}
    assert "Neighbor" not in neighbor_ids
    assert len(neighbor_ids) == 2


def test_adapter_bgp_remediation_recipes():
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.1"})
    intent = RemediationIntent(name="remove_bgp_neighbor_shutdown",
                               params={"protocol": "bgp", "neighbor_ip": "10.0.0.3"})
    fix = adapter.build_fix(intent, profile)
    assert fix == ["no neighbor 10.0.0.3 shutdown"]
    # rollback must RE-ASSERT the shutdown, not double-negate ("no no ...")
    assert adapter.build_rollback(intent, profile) == ["neighbor 10.0.0.3 shutdown"]

    intent2 = RemediationIntent(name="add_bgp_ebgp_multihop",
                                params={"protocol": "bgp", "neighbor_ip": "10.0.0.3", "hops": "3"})
    assert adapter.build_fix(intent2, profile) == ["neighbor 10.0.0.3 ebgp-multihop 3"]
    assert adapter.build_verification(intent2, profile) == ["show ip bgp summary"]


# ── end-to-end: BGP neighbor stuck in Active converges to a real fix ────
def _make_ai(query_state_word):
    calls = {"n": 0}

    def ai(prompt: str) -> str:
        if "Restate this network troubleshooting" in prompt:
            return f"Resolve the BGP neighbor stuck in {query_state_word} state."
        if "candidate ROOT CAUSES" in prompt:
            return json.dumps([])
        if "normalized diagnostic OPERATION" in prompt:
            calls["n"] += 1
            # Nothing on call 1 (engine.py's _observe_initial_state probes
            # BEFORE hypotheses are seeded — active_hypotheses() is empty
            # there, so any impact returned then has no hypothesis_id to
            # bind to). The real operation runs on call 2, inside the main
            # loop, once hypotheses exist — that's the analyze() call the
            # "Interpret this device output" branch below needs.
            if calls["n"] == 2:
                return json.dumps([{"device": "all", "operation": "get_neighbors",
                                    "params": {"protocol": "bgp"}, "purpose": "diag",
                                    "tests_hypotheses": [], "value": 0.9}])
            return json.dumps([])
        if "Interpret this device output" in prompt:
            # A genuine (non-tautological) reading of the collected output —
            # the engine's own deterministic state-match tautology alone is
            # no longer sufficient to reach RESOLVED_PENDING_APPROVAL (see
            # Hypothesis.has_grounded_evidence / RootCauseRanker.converged()).
            # A "fact" must accompany the impact — engine.py's _ingest_output
            # only processes "impacts" while iterating "facts" (each impact
            # is anchored to that round's Observation), so an empty facts
            # list silently drops any impacts alongside it.
            impacts = []
            # Gated on query_state_word — see the HSRP mock's comment: every
            # compiled BGP hypothesis is seeded regardless of scenario, and
            # Active's statement always contains "TCP connection failures",
            # so an ungated search would wrongly ground it even while
            # testing e.g. Idle.
            if query_state_word == "Active":
                m = re.search(r"\[(hyp_[0-9a-f]+)\][^\n]*TCP connection failures", prompt)
                if m:
                    impacts.append({"hypothesis_id": m.group(1), "effect": "support",
                                    "weight": 0.6,
                                    "reason": "show ip bgp summary shows repeated Active with 0 in/out packets"})
            facts = [{"subject": "bgp.neighbor", "attribute": "state", "value": "ACTIVE"}]
            return json.dumps({"facts": facts, "impacts": impacts})
        return ""
    return ai


def test_bgp_active_converges_to_real_vendor_fix_end_to_end():
    """Mirrors the OSPF ExStart validation methodology: reproduces a live
    'BGP neighbor stuck in Active' scenario through the real
    TroubleshootingEngine, proving seeding -> evidence-binding -> confidence
    convergence -> compiled remediation lookup -> real vendor-syntax fix
    all work together, not just that a signature dict has the right shape."""
    devices = [Dev("10.0.0.1")]
    active_text = (
        "BGP router identifier 1.1.1.1, local AS number 65001\n\n"
        "Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ  Up/Down  State/PfxRcd\n"
        "10.0.0.2        4        65002        0        0        0    0    0 never    Active\n"
    )
    gw = VendorGateway(send=lambda d, cmds: {c: active_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai("Active"), devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why is the BGP neighbor stuck in Active state")
    s = report.session

    assert s.status == ResolutionStatus.RESOLVED_PENDING_APPROVAL, s.status
    top = s.top()
    assert top.confidence >= 0.8
    assert "TCP connection failures" in top.statement
    assert s.fix is not None
    assert s.fix.config_commands == ["neighbor 10.0.0.2 ebgp-multihop 2"]
    assert s.fix.rollback_commands == ["no neighbor 10.0.0.2 ebgp-multihop 2"]
    assert s.verification.commands == ["show ip bgp summary"]
    assert any("bgp/Active" in src for src in s.knowledge_sources)


def test_bgp_idle_stays_below_convergence_threshold_honest_uncertainty():
    """Idle's compiled confidence (0.50) is deliberately lower than Active's
    (0.70) because it's genuinely ambiguous (admin shutdown vs no route) --
    even with direct confirming evidence, a single observation shouldn't
    push an ambiguous cause over the 80% auto-confirm threshold. This is
    the SAME honest-uncertainty calibration OSPF's own low-confidence
    signatures (Attempt, Exchange, Loading) already rely on."""
    devices = [Dev("10.0.0.1")]
    idle_text = (
        "BGP router identifier 1.1.1.1, local AS number 65001\n\n"
        "Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ  Up/Down  State/PfxRcd\n"
        "10.0.0.3        4        65003        0        0        0    0    0 never    Idle\n"
    )
    gw = VendorGateway(send=lambda d, cmds: {c: idle_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai("Idle"), devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why is the BGP neighbor stuck in Idle state")
    s = report.session
    assert s.status == ResolutionStatus.LIKELY_CAUSE_PRESENT, s.status
    assert s.fix is None
