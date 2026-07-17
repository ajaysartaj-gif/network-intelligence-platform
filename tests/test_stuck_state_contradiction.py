"""
Regression for a real production report: a merged hypothesis (compiled
ExStart signature + Mismatch Investigation interface_mtu Finding) stayed at
92% confidence and kept winning even in a session whose REAL, current
evidence never showed any neighbor in ExStart at all — the Question vs.
Evidence Mismatch banner correctly said so, but the Active Hypotheses /
Reasoning Chain / Likely Root Cause sections of the SAME report proceeded
to confidently diagnose ExStart/MTU anyway, directly contradicting the
banner three sections above.

Root cause: TroubleshootingEngine._bind_compiled_signature_evidence()
identified "which state does this hypothesis explain" by regex-searching
hyp.rationale for a literal "stuck in 'X'" phrase. After
HypothesisManager.add()'s discriminating-signal merge, the SURVIVING
hypothesis keeps whichever rationale was seeded first — for this exact
scenario, the Mismatch Investigation's own prose ("adjacency hangs in
EXSTART/EXCHANGE because the database-description exchange fails..."),
which never contains that literal phrase. The regex silently found
nothing, so this merged hypothesis was skipped entirely by the ONE
mechanism that would have deterministically contradicted (and eventually
eliminated) it once the observed state stopped matching what it claims to
explain — leaving it uncontradicted, at full confidence, indefinitely.

_hypothesis_stuck_state() fixes this by checking discriminating_signals
FIRST (unioned across every merge, so the compiled signature's own state
name survives even when the rationale text doesn't), falling back to the
rationale regex only when no protocol model is available.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.topology.knowledge_graph_bridge as kgb
from core.knowledge.compiler.protocol_models import build_protocol_model
from core.troubleshooting import ResolutionStatus, TroubleshootingEngine, TSConfig
from core.troubleshooting.hypotheses import ConfidenceCalculator, HypothesisManager
from core.troubleshooting.models import Goal, HypothesisState, Observation, Session
from core.vendor import VendorGateway

from tests.test_ospf_exstart_end_to_end import (
    FakeDevice, _no_real_topology, _ospf_interface_text, _show_interface_text,
)


def _engine():
    return TroubleshootingEngine(ai_call=lambda p: "", devices=[])


# ── unit: _hypothesis_stuck_state() itself ──────────────────────────────────
def test_hypothesis_stuck_state_found_via_discriminating_signals_when_rationale_has_no_phrase():
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck"))
    hmgr = HypothesisManager(session)
    h = hmgr.add(
        "interface_mtu must equal violated on ospf_adjacency (local=1500, remote=1200)",
        rationale="adjacency hangs in EXSTART/EXCHANGE because the database-description "
                 "exchange fails [source: net-knowledge-note §ospf-adjacency]",
        discriminating_signals=["interface_mtu", "mtu", "ExStart"], prior=0.92,
    )
    model = build_protocol_model("ospf")
    assert eng._hypothesis_stuck_state(h, model) == "ExStart"


def test_hypothesis_stuck_state_falls_back_to_rationale_regex_without_a_model():
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck"))
    hmgr = HypothesisManager(session)
    h = hmgr.add("some cause", rationale="Compiled failure signature: ospf stuck in 'Down' (confidence 0.55).",
                discriminating_signals=[], prior=0.55)
    assert eng._hypothesis_stuck_state(h, None) == "Down"


# ── unit: _bind_compiled_signature_evidence() now contradicts merged hypotheses ──
def test_bind_compiled_signature_evidence_contradicts_a_merged_hypothesis_via_signals():
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck in ExStart"))
    hmgr = HypothesisManager(session)
    conf = ConfidenceCalculator()
    h = hmgr.add(
        "interface_mtu must equal violated on ospf_adjacency (local=1500, remote=1200)",
        rationale="adjacency hangs in EXSTART/EXCHANGE because the database-description "
                 "exchange fails [source: net-knowledge-note §ospf-adjacency]",
        discriminating_signals=["interface_mtu", "mtu", "ExStart"], prior=0.92,
    )
    # The REAL, current observation: a healthy Full neighbor, not ExStart.
    obs = Observation(device="192.168.96.136", subject="neighbor.192.168.21.2",
                      attribute="state", value="Full")
    session.observations.append(obs)

    eng._bind_compiled_signature_evidence(session, hmgr, conf)

    assert any("rules out this signature" in (d.reason or "") for d in h.deltas), h.deltas
    assert h.confidence < 0.92   # contradicted, not left at its full compiled prior


def test_bind_compiled_signature_evidence_still_confirms_a_merged_hypothesis_that_matches():
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck in ExStart"))
    hmgr = HypothesisManager(session)
    conf = ConfidenceCalculator()
    h = hmgr.add(
        "interface_mtu must equal violated on ospf_adjacency (local=1500, remote=1200)",
        rationale="adjacency hangs in EXSTART/EXCHANGE because the database-description "
                 "exchange fails [source: net-knowledge-note §ospf-adjacency]",
        discriminating_signals=["interface_mtu", "mtu", "ExStart"], prior=0.85,
    )
    obs = Observation(device="192.168.96.136", subject="neighbor.192.168.20.2",
                      attribute="state", value="ExStart")
    session.observations.append(obs)

    eng._bind_compiled_signature_evidence(session, hmgr, conf)

    assert any("confirms this signature" in (d.reason or "") for d in h.deltas), h.deltas
    assert h.confidence > 0.85


# ── end-to-end: the full reported scenario, via reap()'s existing rule ────
def test_reap_eliminates_the_merged_hypothesis_once_contradicted_by_real_evidence():
    """reap() already eliminates outright (regardless of residual
    confidence) any hypothesis carrying a "...rules out this signature"
    delta — this proves that existing rule now actually reaches a MERGED
    hypothesis too, closing the loop end to end."""
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck in ExStart"))
    hmgr = HypothesisManager(session)
    conf = ConfidenceCalculator()
    h = hmgr.add(
        "interface_mtu must equal violated on ospf_adjacency (local=1500, remote=1200)",
        rationale="adjacency hangs in EXSTART/EXCHANGE because the database-description "
                 "exchange fails [source: net-knowledge-note §ospf-adjacency]",
        discriminating_signals=["interface_mtu", "mtu", "ExStart"], prior=0.92,
    )
    session.observations.append(Observation(device="192.168.96.136", subject="neighbor.192.168.21.2",
                                            attribute="state", value="Full"))

    eng._bind_compiled_signature_evidence(session, hmgr, conf)
    hmgr.reap()

    assert h.state == HypothesisState.ELIMINATED
    assert h not in session.active_hypotheses()
    assert h not in session.ranked()


# ── real end-to-end: the exact reported scenario, real adapter/gateway ─────
def _ospf_neighbor_text_full(neighbor_router_id, neighbor_addr):
    return (
        "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
        f"{neighbor_router_id}       0   FULL/BDR        00:00:33    {neighbor_addr}       GigabitEthernet0/0\n"
    )


def _build_gateway_healthy_but_mtu_still_differs():
    """The adjacency is genuinely healthy (FULL on both sides) — but the
    interfaces' underlying hardware MTU still, independently, differs
    (1500 vs 1200; the Mismatch Investigation compares raw interface MTU
    regardless of current adjacency state). This is exactly the real
    reported shape: real MTU evidence exists, but it does NOT mean the
    neighbor is currently stuck in ExStart — asking "why stuck in ExStart"
    against this evidence must not silently proceed to diagnose ExStart."""
    r1 = FakeDevice("192.168.96.136", "R1")
    r2 = FakeDevice("192.168.20.2", "R2")
    responses = {
        ("192.168.96.136", "show ip ospf interface"): _ospf_interface_text("0", "1.1.1.1", prefix_ip="192.168.96.136"),
        ("192.168.96.136", "show ip ospf neighbor"): _ospf_neighbor_text_full("2.2.2.2", "192.168.20.2"),
        ("192.168.96.136", "show interface"): _show_interface_text(1500),
        ("192.168.96.136", "show running-config | section ^interface"): "",
        ("192.168.20.2", "show ip ospf interface"): _ospf_interface_text("0", "2.2.2.2", prefix_ip="192.168.20.2"),
        ("192.168.20.2", "show ip ospf neighbor"): _ospf_neighbor_text_full("1.1.1.1", "192.168.96.136"),
        ("192.168.20.2", "show interface"): _show_interface_text(1200),
        ("192.168.20.2", "show running-config | section ^interface"): "",
    }

    def send(device, cmds):
        return {c: responses.get((device.ip, c), "") for c in cmds}

    def hint_provider(device):
        return {"device_type": device.device_type, "hostname": device.hostname}

    gw = VendorGateway(send=send, hint_provider=hint_provider)
    ip_to_dev = {r1.ip: r1, r2.ip: r2}
    return gw, ip_to_dev


def test_asked_exstart_with_stale_mtu_evidence_does_not_confidently_diagnose_exstart(monkeypatch):
    _no_real_topology(monkeypatch)
    gw, ip_to_dev = _build_gateway_healthy_but_mtu_still_differs()
    devices = list(ip_to_dev.values())

    eng = TroubleshootingEngine(ai_call=lambda p: "", devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why OSPF stuck in ExStart")
    s = report.session

    # The mismatch banner must fire, with real per-neighbor states shown.
    assert s.goal_mismatch is not None
    assert s.goal_mismatch["asked_state"] == "ExStart"
    assert s.goal_mismatch["neighbor_states"], "must show concrete per-neighbor states, not a coarse flag"
    assert all(ns["value"].upper().startswith("FULL") for ns in s.goal_mismatch["neighbor_states"])

    # The merged MTU/ExStart hypothesis (real MTU evidence exists) must be
    # contradicted and eliminated — it explains a state that wasn't observed.
    mtu_hyp = next((h for h in s.hypotheses if "mtu" in " ".join(h.discriminating_signals).lower()), None)
    assert mtu_hyp is not None, "the real MTU evidence should still have been seeded"
    assert mtu_hyp.state == HypothesisState.ELIMINATED, mtu_hyp.state

    # No reasoning chain contradicting the banner, and no confident
    # RESOLVED_PENDING_APPROVAL built around the unconfirmed ExStart claim.
    if s.reasoning_chain is not None:
        assert s.reasoning_chain.get("stuck_state", "").upper() != "EXSTART"
    assert s.status != ResolutionStatus.RESOLVED_PENDING_APPROVAL, s.status
    md = report.to_markdown()
    assert "Question vs. Evidence Mismatch" in md
