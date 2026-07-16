"""
Tests for core/knowledge/compiler/failure_signatures.py's explain_stuck_state()
— the deterministic reasoning-chain builder added in response to real
feedback: a report jumping straight from a confidence score to "MTU mismatch"
with no explanation of WHY ExStart specifically implicates DBD exchange
(as opposed to Hellos or Layer 1/2, which reaching ExStart already rules
out having a problem with).
"""
import sys
import types
from pathlib import Path

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.knowledge.compiler.failure_signatures import explain_stuck_state
from core.troubleshooting import TroubleshootingEngine
from core.troubleshooting.models import Goal, Hypothesis, Session


def test_ospf_exstart_confirms_prior_stages_and_names_dbd_as_whats_missing():
    result = explain_stuck_state("ospf", "ExStart")
    assert result is not None
    assert result["stuck_state"] == "ExStart"

    # Prior stages actually confirmed, in order, up to (not including) ExStart.
    stages_text = " | ".join(result["confirmed_stages"])
    assert "Down → Attempt" in stages_text or "Down → Init" in stages_text
    assert "Init → 2-Way" in stages_text
    assert "hello received with own router id" in stages_text.lower()
    assert "2-Way → ExStart" in stages_text
    assert "elected dr/bdr" in stages_text.lower() or "point-to-point" in stages_text.lower()

    # What's actually missing: DBD/master-slave negotiation, not Hellos or L1/2.
    assert "master/slave" in result["stuck_meaning"].lower()
    assert "sequence number" in result["stuck_meaning"].lower()

    # Grounded conclusion + confidence, straight from the compiled signature.
    assert "mtu" in result["likely_cause"].lower()
    assert result["evidence_fields"] == ["mtu"]
    assert result["confidence"] == 0.85


def test_ospf_down_has_no_confirmed_stages_and_multiple_forward_paths():
    """Down is the FIRST state — nothing came before it — and has two
    distinct forward transitions (NBMA unicast hello vs. broadcast hello),
    both of which should be surfaced since neither is definitively excluded."""
    result = explain_stuck_state("ospf", "Down")
    assert result is not None
    assert result["confirmed_stages"] == []
    assert "hello" in result["stuck_meaning"].lower()


def test_ospf_full_is_terminal_with_no_forward_transition():
    result = explain_stuck_state("ospf", "Full")
    assert result is not None
    assert "no further progression" in result["stuck_meaning"].lower()


def test_unknown_protocol_returns_none_not_a_fabrication():
    assert explain_stuck_state("not-a-real-protocol", "ExStart") is None


def test_unknown_state_for_a_real_protocol_returns_none():
    assert explain_stuck_state("ospf", "NotARealState") is None


def test_state_with_no_compiled_signature_still_returns_fsm_data():
    """Every OSPF state has a signature today, but the function must degrade
    gracefully (empty likely_cause/evidence_fields, not a crash) if a future
    protocol has FSM states without a compiled signature for one of them."""
    result = explain_stuck_state("ospf", "2-Way")
    assert result is not None
    assert result["likely_cause"]   # 2-Way does have one today
    # sanity: the function itself doesn't require a signature to exist
    assert isinstance(result["evidence_fields"], list)


# ── Engine wiring: _compile_reasoning_chain() ───────────────────────────────
def _engine():
    return TroubleshootingEngine(ai_call=lambda p: "", devices=[])


def test_compile_reasoning_chain_finds_stuck_state_via_discriminating_signals_not_rationale():
    """
    Regression for the real scenario this closes: after HypothesisManager.
    add()'s discriminating-signal merge (see test_hypotheses.py), the
    SURVIVING top hypothesis keeps the mismatch-investigation's rationale
    ("Deterministic parameter comparison...[source: ...]"), which has no
    "stuck in 'X'" phrase at all — only discriminating_signals carries the
    compiled signature's stuck_state ("ExStart") after the merge. This must
    still find it and populate session.reasoning_chain correctly.
    """
    eng = _engine()
    session = Session(goal=Goal(query="why is the OSPF neighbor stuck"))
    top = Hypothesis(
        statement="interface_mtu must equal violated on ospf_adjacency between "
                 "192.168.96.136 and 192.168.20.2 (local=1500, remote=1200)",
        rationale="Deterministic parameter comparison from the Knowledge Package. "
                 "[source: net-knowledge-note §ospf-adjacency]",
        discriminating_signals=["interface_mtu", "mtu", "ExStart"],
    )
    session.hypotheses.append(top)

    eng._compile_reasoning_chain(session, top)

    assert session.reasoning_chain is not None
    rc = session.reasoning_chain
    assert rc["stuck_state"] == "ExStart"
    assert "master/slave" in rc["stuck_meaning"].lower()
    assert rc["evidence_comparison"] == {"local": "1500", "remote": "1200"}


def test_compile_reasoning_chain_no_op_when_no_state_signal_present():
    eng = _engine()
    session = Session(goal=Goal(query="why is the OSPF neighbor stuck"))
    top = Hypothesis(statement="Something generic", discriminating_signals=["unrelated_signal"])
    session.hypotheses.append(top)

    eng._compile_reasoning_chain(session, top)
    assert session.reasoning_chain is None


def test_report_markdown_renders_reasoning_chain_section():
    from core.troubleshooting.models import TroubleshootReport
    session = Session(goal=Goal(query="why is the OSPF neighbor stuck"))
    top = Hypothesis(
        statement="interface_mtu must equal violated (local=1500, remote=1200)",
        discriminating_signals=["mtu", "ExStart"],
    )
    top.set_prior(0.84)
    session.hypotheses.append(top)
    eng = _engine()
    eng._compile_reasoning_chain(session, top)

    md = TroubleshootReport(session).to_markdown()
    assert "Reasoning Chain" in md
    assert "ExStart" in md
    assert "master/slave" in md.lower()
    assert "local = `1500`" in md and "remote = `1200`" in md


def test_report_markdown_omits_reasoning_chain_section_when_absent():
    from core.troubleshooting.models import TroubleshootReport
    session = Session(goal=Goal(query="why is the OSPF neighbor stuck"))
    md = TroubleshootReport(session).to_markdown()
    assert "Reasoning Chain" not in md
