"""
Regression for a real production report: "Hypothesis management regressed
-- initially 92% MTU mismatch, after a failed verification 20% Duplicate
Router ID, with no intermediate reasoning explaining why MTU was discarded
or why Duplicate Router ID became the leading hypothesis." Eliminated
hypotheses simply vanished from the report with zero trace of why, making
a demotion to a different leading hypothesis look arbitrary.

Fix: TroubleshootReport now renders a "Ruled Out" section (to_markdown())
and an "eliminated_hypotheses" list (to_dict()) listing every ELIMINATED
hypothesis together with its last-known confidence and the reason it was
eliminated -- recovered via _elimination_reason(), which reads whichever
trace the engine already leaves behind: a deterministic-state-contradiction
ConfidenceDelta's reason, or the "[Already applied..." rationale note left
by _eliminate_excluded_causes() for a cause already confirmed not to work.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.troubleshooting import TroubleshootReport
from core.troubleshooting.models import (
    ConfidenceDelta, Effect, Goal, Hypothesis, HypothesisState, Session,
)


def _session():
    return Session(goal=Goal(query="why OSPF stuck in EXSTART"))


def test_ruled_out_section_absent_when_nothing_eliminated():
    session = _session()
    h = Hypothesis(statement="MTU mismatch between OSPF neighbors")
    h.set_prior(0.6)
    session.hypotheses.append(h)

    md = TroubleshootReport(session).to_markdown()
    assert "Ruled Out" not in md

    d = TroubleshootReport(session).to_dict()
    assert d["eliminated_hypotheses"] == []


def test_ruled_out_section_shows_state_contradiction_reason():
    session = _session()
    h = Hypothesis(statement="MTU mismatch between OSPF neighbors")
    h.set_prior(0.92)
    h.deltas.append(ConfidenceDelta(
        evidence_id="ev_1", effect=Effect.CONTRADICT, weight=0.6, log_odds_change=-1.0,
        reason="deterministic-state-match: observed state 'Down' rules out this signature",
    ))
    h.state = HypothesisState.ELIMINATED
    session.hypotheses.append(h)

    md = TroubleshootReport(session).to_markdown()
    assert "### ❌ Ruled Out" in md
    assert "MTU mismatch between OSPF neighbors" in md.split("Ruled Out")[1]
    assert "observed state 'Down' rules out this signature" in md

    d = TroubleshootReport(session).to_dict()
    assert len(d["eliminated_hypotheses"]) == 1
    entry = d["eliminated_hypotheses"][0]
    assert entry["statement"] == "MTU mismatch between OSPF neighbors"
    assert entry["last_confidence"] == h.confidence
    assert "rules out this signature" in entry["reason"]


def test_ruled_out_section_shows_excluded_cause_reason():
    session = _session()
    h = Hypothesis(statement="MTU mismatch between OSPF neighbors")
    h.set_prior(0.85)
    h.rationale = (
        "[Already applied and confirmed NOT to have resolved this issue in "
        "a prior attempt on this target — excluded without new evidence.]"
    )
    h.state = HypothesisState.ELIMINATED
    session.hypotheses.append(h)

    md = TroubleshootReport(session).to_markdown()
    assert "### ❌ Ruled Out" in md
    assert "already applied and confirmed not to resolve this issue" in md.lower()

    d = TroubleshootReport(session).to_dict()
    assert "already applied" in d["eliminated_hypotheses"][0]["reason"].lower()


def test_ruled_out_section_lists_multiple_eliminated_hypotheses_and_excludes_active_ones():
    session = _session()
    active = Hypothesis(statement="Duplicate Router ID between neighbors")
    active.set_prior(0.2)
    session.hypotheses.append(active)

    eliminated1 = Hypothesis(statement="MTU mismatch between OSPF neighbors")
    eliminated1.set_prior(0.92)
    eliminated1.state = HypothesisState.ELIMINATED
    session.hypotheses.append(eliminated1)

    eliminated2 = Hypothesis(statement="Authentication mismatch")
    eliminated2.set_prior(0.4)
    eliminated2.state = HypothesisState.ELIMINATED
    session.hypotheses.append(eliminated2)

    md = TroubleshootReport(session).to_markdown()
    ruled_out_block = md.split("### ❌ Ruled Out")[1].split("### 🔍 Evidence Summary")[0]
    assert "MTU mismatch between OSPF neighbors" in ruled_out_block
    assert "Authentication mismatch" in ruled_out_block
    assert "Duplicate Router ID between neighbors" not in ruled_out_block

    d = TroubleshootReport(session).to_dict()
    eliminated_statements = {e["statement"] for e in d["eliminated_hypotheses"]}
    assert eliminated_statements == {"MTU mismatch between OSPF neighbors", "Authentication mismatch"}
    active_statements = {a["statement"] for a in d["active_hypotheses"]}
    assert active_statements == {"Duplicate Router ID between neighbors"}
