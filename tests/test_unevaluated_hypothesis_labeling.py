"""
Regression: a hypothesis that never received any evidence (never disproven,
simply never tested this session) must be clearly distinguished in the
report from a genuinely evidence-backed one sitting at similar confidence --
not silently identical, as if both were equally considered.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.troubleshooting.hypotheses import ConfidenceCalculator
from core.troubleshooting.models import (
    Effect, Evidence, Goal, Observation, Session, TroubleshootReport,
)


def _session_with_one_tested_one_untested_hypothesis():
    session = Session(goal=Goal(query="why is ospf down", objective="why is ospf down"))
    from core.troubleshooting.hypotheses import HypothesisManager
    hmgr = HypothesisManager(session)
    conf = ConfidenceCalculator()

    tested = hmgr.add("MTU mismatch between OSPF neighbors", prior=0.3)
    untested = hmgr.add("Duplicate router ID between R1 and R2", prior=0.2)

    obs = Observation(device="10.0.0.1", subject="interface.Gi1/0", attribute="mtu", value="1300")
    session.observations.append(obs)
    ev = Evidence(observation_id=obs.id, hypothesis_id=tested.id, effect=Effect.SUPPORT,
                 weight=0.6, reason="mtu differs")
    session.evidence.append(ev)
    conf.update(tested, ev, obs)

    return session, tested, untested


def test_to_dict_marks_zero_evidence_hypothesis_as_not_evaluated():
    session, tested, untested = _session_with_one_tested_one_untested_hypothesis()
    d = TroubleshootReport(session=session).to_dict()

    by_statement = {h["statement"]: h for h in d["active_hypotheses"]}
    assert by_statement[tested.statement]["evaluated"] is True
    assert by_statement[tested.statement]["evidence_count"] == 1
    assert by_statement[untested.statement]["evaluated"] is False
    assert by_statement[untested.statement]["evidence_count"] == 0


def test_markdown_labels_untested_hypothesis_distinctly_not_as_evidence_zero():
    session, tested, untested = _session_with_one_tested_one_untested_hypothesis()
    md = TroubleshootReport(session=session).to_markdown()

    assert f"⬜" in md
    assert "not evaluated — no evidence collected this session" in md
    assert f"{tested.statement} _(evidence: 1)_" in md
    # The untested one must NOT be rendered with the misleading "evidence: 0"
    # phrasing that reads as "a real, if weak, signal was checked."
    assert f"{untested.statement} _(evidence: 0)_" not in md
    assert f"— {untested.statement} _(not evaluated" in md


def _active_hypotheses_section(md: str) -> str:
    start = md.index("### 🧪 Active Hypotheses")
    end = md.index("\n### ", start + 1)
    return md[start:end]


def test_markdown_still_uses_traffic_light_bars_for_evidence_backed_hypotheses():
    session, tested, untested = _session_with_one_tested_one_untested_hypothesis()
    section = _active_hypotheses_section(TroubleshootReport(session=session).to_markdown())

    tested_line = next(l for l in section.splitlines()
                      if l.strip().startswith("-") and tested.statement in l)
    assert tested_line.strip().startswith(("- 🟩", "- 🟨", "- 🟥"))

    untested_line = next(l for l in section.splitlines()
                         if l.strip().startswith("-") and untested.statement in l)
    assert untested_line.strip().startswith("- ⬜")


def test_if_not_try_these_also_labels_untested_alternatives():
    """The operator-facing 'If Not, Try These' section is more prominent
    than the collapsed diagnostic appendix -- an alternative that was never
    tested must not be listed there at face value either."""
    session, tested, untested = _session_with_one_tested_one_untested_hypothesis()
    md = TroubleshootReport(session=session).to_markdown()
    start = md.index("### 🔁 If Not, Try These")
    section = md[start:]

    assert f"{untested.statement} _(not evaluated — no evidence collected)_" in section
