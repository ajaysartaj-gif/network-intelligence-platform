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
import re
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
    assert set(by_state) == {"Blocking", "ErrDisabled", "ErrDisabledLinkIntegrity"}
    # ErrDisabled is directly observed (an unambiguous status string), not
    # inferred like Blocking (which could legitimately be a healthy
    # redundant-path block) -- it earns higher confidence.
    assert by_state["ErrDisabled"].confidence > by_state["Blocking"].confidence
    assert by_state["ErrDisabledLinkIntegrity"].confidence > by_state["Blocking"].confidence


def test_stp_has_no_remediation_intent_for_errdisabled_by_design():
    """Deliberate safety scoping: blindly clearing a BPDU-Guard err-disable
    (shut/no-shut) could reintroduce a real bridging loop if a switch/hub
    really was plugged into an access port -- this stays a human decision,
    same principle as the platform's deliberate exclusion of auto-enabled
    debug/packet-capture. ErrDisabledLinkIntegrity (UDLD/link-flap/PAgP-DTP
    flap) carries no such risk and DOES get a compiled remediation -- this
    proves the two stay separate, not that STP has zero fixes at all."""
    templates = ReasoningArtifactCompiler().compile_remediation("stp")
    assert len(templates) == 1
    assert templates[0].intent_name == "enable_errdisable_recovery"
    sigs = compile_failure_signatures("stp")
    errdisabled_cause = next(s.likely_cause for s in sigs if s.stuck_state == "ErrDisabled")
    assert templates[0].applicable_signature != errdisabled_cause


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


def test_adapter_categorizes_errdisable_reason_from_filtered_command():
    """The dedicated "show interfaces status err-disabled" command has a
    real Reason column -- UDLD/link-flap/PAgP-DTP-flap are safe to
    auto-recover (ERRDISABLEDLINKINTEGRITY); everything else (BPDU Guard,
    port-security violation, ...) stays the original, fix-less
    ERRDISABLED, preserving the existing safety scoping exactly."""
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    text = ("Port      Name               Status       Reason\n"
           "Gi0/1                        err-disabled udld\n"
           "Gi0/2                        err-disabled bpduguard\n"
           "Gi0/3                        err-disabled psecure-violation\n")
    objs = adapter.parse_output(Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "stp"}),
                                {"show interfaces status err-disabled": text}, profile)
    members = {o.id: o.attributes for o in objs if o.type == "neighbor"}
    assert members["Gi0/1"] == {"protocol": "stp", "state": "ERRDISABLEDLINKINTEGRITY",
                                "errdisable_reason": "udld"}
    assert members["Gi0/2"] == {"protocol": "stp", "state": "ERRDISABLED",
                                "errdisable_reason": "bpduguard"}
    assert members["Gi0/3"] == {"protocol": "stp", "state": "ERRDISABLED",
                                "errdisable_reason": "psecure-violation"}


def test_adapter_never_misreads_a_vlan_number_as_an_errdisable_reason():
    """Adversarial case: the PLAIN (unfiltered) "show interfaces status"
    command's Status column is followed by a VLAN NUMBER at the exact
    text position a reason would occupy in the filtered command's output.
    A bare "10" must never match the closed reason vocabulary -- if it
    did, a real vlan-tagged err-disabled port could be silently
    miscategorized as safe-to-auto-recover from a completely unrelated
    number."""
    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.5"})
    text = (_STATUS_HEADER +
           "Gi0/3                        err-disabled 10         auto    auto  10/100/1000BaseTX\n")
    objs = adapter.parse_output(Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "stp"}),
                                {"show interfaces status": text}, profile)
    members = {o.id: o.attributes for o in objs if o.type == "neighbor"}
    assert members["Gi0/3"]["state"] == "ERRDISABLED"
    assert "errdisable_reason" not in members["Gi0/3"]


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
            # Nothing on call 1 (engine.py's _observe_initial_state probes
            # BEFORE hypotheses are seeded — active_hypotheses() is empty
            # there, so any impact returned then has no hypothesis_id to
            # bind to). The real operation runs on call 2, inside the main
            # loop, once hypotheses exist — that's the analyze() call the
            # "Interpret this device output" branch below needs. The
            # deterministic-state-match tautology (which the BPDU Guard
            # test still relies on) fires just as well one round later,
            # once this op's output is ingested.
            if calls["n"] == 2:
                return json.dumps([{"device": "all", "operation": "get_interface_details",
                                    "params": {"protocol": "stp"}, "purpose": "diag",
                                    "tests_hypotheses": [], "value": 0.9}])
            return json.dumps([])
        if "Interpret this device output" in prompt:
            # A genuine (non-tautological) reading of the collected output —
            # the engine's own deterministic state-match tautology alone is
            # no longer sufficient to reach fix-eligible convergence (see
            # Hypothesis.has_grounded_evidence / RootCauseRanker.converged()).
            # A "fact" must accompany the impact — engine.py's _ingest_output
            # only processes "impacts" while iterating "facts" (each impact
            # is anchored to that round's Observation), so an empty facts
            # list silently drops any impacts alongside it. Only
            # ErrDisabledLinkIntegrity's (UDLD) test needs this to converge
            # to a fix; BPDU Guard deliberately must NOT auto-fix regardless
            # (no matching remediation template exists for it), and
            # Blocking's test only checks the deterministic delta itself.
            impacts = []
            # Gated on query_state_word: all 3 compiled STP hypotheses
            # (Blocking/ErrDisabled/ErrDisabledLinkIntegrity) are seeded
            # regardless of scenario, and ErrDisabledLinkIntegrity's own
            # statement always contains "UDLD" — an ungated search would
            # wrongly ground THAT hypothesis even while testing e.g.
            # ErrDisabled (BPDU Guard), risking it out-ranking the actually-
            # tested top hypothesis.
            if query_state_word == "ErrDisabledLinkIntegrity":
                m = re.search(r"\[(hyp_[0-9a-f]+)\][^\n]*UDLD", prompt)
                if m:
                    impacts.append({"hypothesis_id": m.group(1), "effect": "support",
                                    "weight": 0.6,
                                    "reason": "show interfaces status err-disabled reports reason: udld"})
            # subject/attribute must overlap the hypothesis's own declared
            # discriminating_signals (engine.py's evidence gate,
            # _obs_matches_signals) — ErrDisabledLinkIntegrity's signal is
            # "errdisable_reason" (see protocol_registry.py's
            # _STP_SIGNATURES), so a generic "status" fact never binds.
            facts = [{"subject": "stp.interface", "attribute": "errdisable_reason", "value": "udld"}]
            return json.dumps({"facts": facts, "impacts": impacts})
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


def test_stp_udld_errdisable_converges_to_real_auto_recovery_fix():
    """The one STP err-disable cause class that's actually safe to
    auto-recover: UDLD carries no bridging-loop risk (unlike BPDU Guard),
    so this must converge to a real, deployable Cisco fix -- proving the
    new safety-scoped remediation policy is genuinely reachable end to
    end, not just present in the compiled signature library."""
    devices = [Dev("10.0.0.1")]
    command_outputs = {
        "show spanning-tree": _STP_TABLE,
        "show interfaces status": (_STATUS_HEADER +
            "Gi0/1                        err-disabled 10         auto    auto  10/100/1000BaseTX\n"),
        "show interfaces status err-disabled": (
            "Port      Name               Status       Reason\n"
            "Gi0/1                        err-disabled udld\n"),
    }
    gw = VendorGateway(send=lambda d, cmds: {c: command_outputs.get(c, "") for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai("ErrDisabledLinkIntegrity"), devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why is the STP port err-disabled")
    s = report.session
    top = s.top()
    assert top is not None
    assert top.confidence >= 0.7
    assert s.fix is not None
    assert "errdisable recovery cause udld" in "\n".join(s.fix.config_commands)


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
