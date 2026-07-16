"""
Regression for a real production report: the header showed 97% confidence
while the Reasoning Chain, three lines down, showed "compiled signature
confidence: 55%" with no explanation for the gap. The math itself was
correct (a compiled baseline raised by real evidence deltas) but nothing in
the report showed the calculation — a user is left guessing how 55% became
97%. Hypothesis.prior_confidence (set alongside set_prior()) plus
TroubleshootReport.to_dict()/to_markdown()'s new confidence_trace close
this: the report now states the baseline, the final score, and how many
evidence updates bridged them.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.troubleshooting.models import (
    ConfidenceDelta, Effect, Goal, Hypothesis, Session, TroubleshootReport,
)


def _session_with_top(prior: float, deltas):
    h = Hypothesis(statement="No hello packets exchanged")
    h.set_prior(prior)
    for i, (effect, weight, log_odds) in enumerate(deltas):
        d = ConfidenceDelta(evidence_id=f"ev{i}", effect=effect, weight=weight, log_odds_change=log_odds)
        h.apply(d, f"ev{i}")
    session = Session(goal=Goal(query="why OSPF stuck"))
    session.hypotheses.append(h)
    return session, h


def test_prior_confidence_is_recorded_separately_from_final_confidence():
    h = Hypothesis(statement="x")
    h.set_prior(0.55)
    assert h.prior_confidence == 0.55
    h.apply(ConfidenceDelta(evidence_id="e1", effect=Effect.SUPPORT, weight=0.6, log_odds_change=0.69), "e1")
    # confidence moved, prior_confidence (the compiled baseline) did not
    assert h.prior_confidence == 0.55
    assert h.confidence > 0.55


def test_report_confidence_trace_present_when_evidence_moved_confidence():
    session, h = _session_with_top(0.55, [
        (Effect.SUPPORT, 0.6, 0.69), (Effect.SUPPORT, 0.5, 0.5),
        (Effect.SUPPORT, 0.5, 0.5), (Effect.SUPPORT, 0.5, 0.5),
    ])
    report = TroubleshootReport(session)
    d = report.to_dict()
    assert d["confidence_trace"] is not None
    assert d["confidence_trace"]["prior"] == 0.55
    assert d["confidence_trace"]["final"] == h.confidence
    assert d["confidence_trace"]["evidence_updates"] == 4

    md = report.to_markdown()
    assert "Compiled baseline 55%" in md
    assert "evidence update(s)" in md


def test_report_confidence_trace_absent_when_no_deltas_applied():
    session, h = _session_with_top(0.85, [])
    report = TroubleshootReport(session)
    d = report.to_dict()
    assert d["confidence_trace"] is None
    md = report.to_markdown()
    assert "Compiled baseline" not in md


def test_report_confidence_trace_absent_when_confidence_barely_moved():
    """A negligible net change (e.g. one support + one roughly offsetting
    contradiction) isn't worth calling out as an explainable "jump"."""
    session, h = _session_with_top(0.55, [
        (Effect.SUPPORT, 0.1, 0.02), (Effect.CONTRADICT, 0.1, -0.02),
    ])
    report = TroubleshootReport(session)
    d = report.to_dict()
    assert d["confidence_trace"] is None
