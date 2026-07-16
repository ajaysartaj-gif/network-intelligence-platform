"""Tests for core/troubleshooting/hypotheses.py's near-duplicate detection."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.troubleshooting.hypotheses import HypothesisManager, _similar, content_tokens
from core.troubleshooting.models import ConfidenceDelta, Effect, HypothesisState, Session


def test_distinct_timer_mismatches_are_not_merged_as_similar():
    """Regression: "OSPF hello timer mismatch between neighbors" vs "OSPF
    dead timer mismatch between neighbors" measured at Jaccard ~0.71 (above
    the 0.6 threshold) because domain-boilerplate words (ospf, mismatch,
    between, neighbors) dominated the token overlap, silently merging two
    genuinely DIFFERENT root causes into one and discarding the second
    entirely. Expanding the stop-word list to exclude these connector/
    protocol-name tokens fixes this without weakening real duplicate
    detection (two literal restatements of the SAME cause still merge)."""
    a = "OSPF hello timer mismatch between neighbors"
    b = "OSPF dead timer mismatch between neighbors"
    assert not _similar(a, b), (content_tokens(a), content_tokens(b))


def test_genuine_restatement_still_merges():
    a = "MTU mismatch between OSPF neighbors prevents DBD packet exchange"
    b = "MTU mismatch between OSPF neighbors blocks DBD packet exchange"
    assert _similar(a, b)


def test_exact_duplicate_merges():
    a = "OSPF authentication mismatch between neighbors"
    assert _similar(a, a)


# ── HypothesisManager.add(): discriminating-signal-based merge ─────────────
def test_mismatch_investigation_and_compiled_signature_hypotheses_merge_on_shared_parameter():
    """
    Regression for a real production report: a mismatch-investigation
    Finding produces a templated statement ("interface_mtu must equal
    violated on ospf_adjacency between 192.168.96.136 and 192.168.20.2
    (local=1500, remote=1200)", discriminating_signals=["interface_mtu"])
    and the compiled ExStart failure signature produces its own canned
    prose ("MTU mismatch between OSPF neighbors prevents DBD packet
    exchange", discriminating_signals=["mtu", "ExStart"] per
    protocol_registry.py's evidence_fields=["mtu"]). These share almost no
    free-text vocabulary, so _similar() alone never merges them — they
    end up competing (84% vs 68% in the real report) instead of combining,
    which starved the convergence margin and blocked a fix from ever being
    proposed despite the platform having a clear, well-grounded MTU
    diagnosis. Comparing discriminating_signals tokens (both contain "mtu"
    once "interface_mtu" is split on its underscore) must merge them.
    """
    session = Session()
    hmgr = HypothesisManager(session)

    h1 = hmgr.add(
        "interface_mtu must equal violated on ospf_adjacency between "
        "192.168.96.136 and 192.168.20.2 (local=1500, remote=1200)",
        discriminating_signals=["interface_mtu"], prior=0.84,
    )
    h2 = hmgr.add(
        "MTU mismatch between OSPF neighbors prevents DBD packet exchange",
        discriminating_signals=["mtu", "ExStart"], prior=0.85,
    )

    assert h1 is h2
    assert len(session.hypotheses) == 1
    assert "mtu" in h1.discriminating_signals or "interface_mtu" in h1.discriminating_signals


def test_different_fsm_states_sharing_a_contributing_factor_are_not_merged():
    """
    Regression for a real bug the merge fix above introduced: BGP's
    compiled Idle signature (evidence_fields=["admin_state",
    "route_to_peer"]) and Active signature (evidence_fields=["neighbor_ip",
    "route_to_peer", "acl"]) share the token "route_to_peer" -> {route,
    peer} — both descriptions mention route reachability as A contributing
    factor, but Idle ("never even attempts to connect") and Active
    ("repeated TCP connection failures") are genuinely different diagnoses.
    A shared evidence-field token must NOT merge two hypotheses that each
    name a DIFFERENT specific FSM state.
    """
    session = Session()
    hmgr = HypothesisManager(session)

    idle = hmgr.add(
        "Neighbor administratively shut down, or no route exists to the peer address",
        discriminating_signals=["admin_state", "route_to_peer", "Idle"], prior=0.5,
    )
    active = hmgr.add(
        "Repeated TCP connection failures to the peer address",
        discriminating_signals=["neighbor_ip", "route_to_peer", "acl", "Active"], prior=0.7,
    )

    assert idle is not active
    assert len(session.hypotheses) == 2


def test_unrelated_parameters_are_not_merged_via_discriminating_signals():
    """Guard against over-merging: a hello/dead-timer hypothesis and an
    MTU hypothesis share no discriminating-signal tokens and must remain
    two distinct hypotheses."""
    session = Session()
    hmgr = HypothesisManager(session)

    h1 = hmgr.add("Hello/dead interval or area ID mismatch between neighbors",
                  discriminating_signals=["timer_type", "areas"], prior=0.75)
    h2 = hmgr.add("MTU mismatch between OSPF neighbors prevents DBD packet exchange",
                  discriminating_signals=["mtu", "ExStart"], prior=0.85)

    assert h1 is not h2
    assert len(session.hypotheses) == 2


def test_add_without_discriminating_signals_falls_back_to_statement_only_dedup():
    """No discriminating_signals on the new hypothesis must not crash and
    must not spuriously merge against an unrelated existing one."""
    session = Session()
    hmgr = HypothesisManager(session)

    h1 = hmgr.add("MTU mismatch between OSPF neighbors prevents DBD packet exchange",
                  discriminating_signals=["mtu"], prior=0.85)
    h2 = hmgr.add("Completely unrelated statement about a power supply unit")

    assert h1 is not h2
    assert len(session.hypotheses) == 2


# ── reap(): deterministic state-contradiction eliminates outright ─────────
def _deterministically_ruled_out(h, obs_id="obs1"):
    """Simulates engine.py's _bind_compiled_signature_evidence() CONTRADICT
    branch: observed FSM state != this signature's own stuck_state."""
    delta = ConfidenceDelta(
        evidence_id="ev1", effect=Effect.CONTRADICT, weight=0.6,
        log_odds_change=-0.96,
        reason="deterministic-state-match: observed state 'EXSTART' rules out this signature",
    )
    h.apply(delta, "ev1")


def test_reap_eliminates_a_state_contradicted_hypothesis_regardless_of_residual_confidence():
    """
    Regression for real feedback: a report showed 6+ compiled-signature
    hypotheses for states OTHER than the one actually observed (Down 33%,
    Attempt 28%, Exchange 28%, Loading 28%, 2-Way 20%, ...) still cluttering
    'Active Hypotheses' even though each one had already been deterministically
    ruled out by the real observed state. The confidence math was correct
    (each number exactly matches its compiled prior minus the contradiction's
    log-odds penalty) — the gap was that demotion alone doesn't clear
    ELIMINATE_BELOW (0.05), so a hypothesis for an FSM state that cannot
    possibly be the current one lingered at 20-33% instead of being dropped
    outright, the way a human engineer would immediately discard it.
    """
    session = Session()
    hmgr = HypothesisManager(session)
    h = hmgr.add("No hello packets exchanged — Layer 1/2 connectivity issue",
                 discriminating_signals=["admin_state"], prior=0.55)
    _deterministically_ruled_out(h)
    assert h.confidence > 0.05   # demoted, but nowhere near the old ELIMINATE_BELOW floor

    hmgr.reap()
    assert h.state == HypothesisState.ELIMINATED
    assert h not in session.active_hypotheses()
    assert h not in session.ranked()


def test_reap_does_not_eliminate_a_hypothesis_without_a_state_contradiction():
    """Control: a hypothesis at similar confidence but with only ordinary
    (non-deterministic-contradiction) evidence must NOT be swept up by the
    new rule — it should still follow the normal ELIMINATE_BELOW threshold."""
    session = Session()
    hmgr = HypothesisManager(session)
    h = hmgr.add("Statically configured NBMA neighbor not responding",
                 discriminating_signals=["nbma"], prior=0.28)
    h.apply(ConfidenceDelta(evidence_id="ev2", effect=Effect.SUPPORT, weight=0.3,
                            log_odds_change=0.2, reason="show output confirms static config"),
           "ev2")

    hmgr.reap()
    assert h.state == HypothesisState.ACTIVE
    assert h in session.active_hypotheses()
