"""
Regression for a real production report: a re-investigation targeting a
specific OSPF neighbor found zero surviving hypotheses (its own
target-scoping correctly refused to bind evidence for a DIFFERENT,
unrelated neighbor, and correctly declined to raise a goal-mismatch banner
without real evidence for the named target) — and _finish() converted
"no hypothesis survived" into "🟢 No fault found — system appears healthy",
even though the SAME session's own Evidence Summary plainly showed a
different neighbor stuck in EXSTART (not OSPF's healthy terminal state,
Full). "No hypothesis" and "confirmed healthy" are not the same fact.

_finish() now checks whether any neighbor/protocol observation the session
actually gathered contradicts a healthy conclusion before reporting one —
if so, it escalates with an honest reason instead.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.troubleshooting import ResolutionStatus, TroubleshootingEngine
from core.troubleshooting.hypotheses import RootCauseRanker
from core.troubleshooting.models import Goal, Observation, Session


def _engine():
    return TroubleshootingEngine(ai_call=lambda p: "", devices=[])


def _stub_supply_chain(monkeypatch):
    """_finish() -> _record_ambiguous_outcome() reaches the real
    NetworkIntelligenceSupplyChain -> real embedding model, which is
    unrelated to what these tests check and fails in some dev environments
    (torch/numpy version mismatch) -- stub it out, same pattern already
    used by test_troubleshooting_engine.py's own ESCALATE test."""
    class _Stub:
        def record_failed_resolution(self, *a, **kw):
            return []
        def record_resolution(self, *a, **kw):
            return []
    import core.knowledge.compiler.supply_chain as sc_mod
    monkeypatch.setattr(sc_mod, "NetworkIntelligenceSupplyChain", _Stub)


def test_no_hypotheses_but_contradicting_evidence_escalates_not_healthy(monkeypatch):
    _stub_supply_chain(monkeypatch)
    eng = _engine()
    session = Session(goal=Goal(query="why is the OSPF neighbor 192.168.20.2 stuck in EXSTART"))
    # No hypotheses survived (e.g. target-scoping correctly refused to bind
    # evidence for a different neighbor) -- but the session DID observe a
    # real, non-full OSPF state elsewhere.
    session.observations.append(Observation(
        device="192.168.20.2", subject="neighbor.192.168.21.1",
        attribute="state", value="EXSTART"))

    report = eng._finish(session, RootCauseRanker())
    s = report.session

    assert s.status == ResolutionStatus.ESCALATE, s.status
    assert s.escalation_reason and "EXSTART" in s.escalation_reason


def test_no_hypotheses_and_no_contradicting_evidence_stays_healthy():
    eng = _engine()
    session = Session(goal=Goal(query="why is the OSPF neighbor 192.168.20.2 stuck in EXSTART"))
    session.observations.append(Observation(
        device="192.168.20.2", subject="neighbor.192.168.21.1",
        attribute="state", value="Full"))

    report = eng._finish(session, RootCauseRanker())
    s = report.session

    assert s.status == ResolutionStatus.HEALTHY, s.status


def test_no_observations_at_all_falls_through_to_escalate_unchanged():
    """No observations at all never hits the healthy branch (its own guard
    requires session.observations to be truthy) -- unchanged prior
    behavior, not part of this fix."""
    eng = _engine()
    session = Session(goal=Goal(query="why is the OSPF neighbor stuck in EXSTART"))

    report = eng._finish(session, RootCauseRanker())
    s = report.session

    assert s.status == ResolutionStatus.ESCALATE, s.status
