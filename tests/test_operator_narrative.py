"""
Regression for user feedback: the report read like an AI-debugging dump
("Compiled signature", "Governance", "Knowledge source", "Deterministic
anchor", "Reasoning chain", "Risk engine") instead of a TAC engineer's
explanation ("what's broken, why, how sure are you, what should I do").

TroubleshootReport.to_markdown() now prepends a plain-language narrative
(You Are Here -> What This Means -> Most Likely Cause -> Here's Why ->
Check This -> Fix This -> If Not, Try These -> Bottom Line) built from the
same session data, and moves every AI-instrumentation section (Active
Hypotheses detail, Ruled Out, Evidence Summary, Executed Commands, Next
Best Command, Confidence Score math, Reasoning Chain's compiled-signature
citation, Risk Assessment, Knowledge Sources Consulted) into a collapsed
<details> block — present verbatim for auditing, not interleaved with the
narrative an operator actually needs to act.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.troubleshooting.models import (
    Fix, Goal, Hypothesis, HypothesisState, Session, TroubleshootReport, VerificationPlan,
)

_NARRATIVE_HEADERS = [
    "### 📍 You Are Here", "### 🧭 Most Likely Cause", "### 🗣️ Here's Why",
    "### 🔍 Check This", "### 🛠️ Fix This", "### 🏁 Bottom Line",
]
_DIAGNOSTIC_HEADERS = [
    "### 🧪 Active Hypotheses", "### 🔍 Evidence Summary", "### 🖥️ Executed Commands",
    "### 📊 Confidence Score",
]


def _full_session():
    session = Session(goal=Goal(query="why is the OSPF neighbor stuck in EXSTART",
                                objective="Diagnose the stuck OSPF adjacency"))
    top = Hypothesis(statement="MTU mismatch between OSPF neighbors")
    top.rationale = "adjacency hangs in EXSTART because the DBD exchange fails"
    top.set_prior(0.85)
    session.hypotheses.append(top)

    alt = Hypothesis(statement="Timer mismatch between neighbors")
    alt.set_prior(0.3)
    session.hypotheses.append(alt)

    ruled_out = Hypothesis(statement="Hello/dead interval mismatch")
    ruled_out.set_prior(0.5)
    ruled_out.state = HypothesisState.ELIMINATED
    session.hypotheses.append(ruled_out)

    session.reasoning_chain = {
        "stuck_state": "ExStart", "stuck_meaning": "master/slave not yet negotiated",
        "confirmed_stages": ["Down -> Attempt: hello sent"],
        "likely_cause": "MTU mismatch prevents DBD exchange", "confidence": 0.85,
        "evidence_comparison": {"local": "1500", "remote": "1200"},
    }
    session.fix = Fix(root_cause=top.statement, config_commands=["ip ospf mtu-ignore"],
                      rollback_commands=["no ip ospf mtu-ignore"], explanation="Ignore MTU check")
    session.verification = VerificationPlan(commands=["show ip ospf neighbor"],
                                            success_criteria="Neighbor state is Full")
    session.risk = {"severity": "high", "probability": 0.85, "impact": "50 objects",
                    "mitigation_reference": "GovernanceEngine.govern()"}
    session.knowledge_sources = ["compiled failure signature: ospf/ExStart"]
    return session


def test_narrative_headers_appear_before_diagnostic_details_block():
    md = TroubleshootReport(_full_session()).to_markdown()
    details_pos = md.index("<details>")
    for h in _NARRATIVE_HEADERS:
        assert h in md, h
        assert md.index(h) < details_pos, f"{h} should appear before Diagnostic Details"
    for h in _DIAGNOSTIC_HEADERS:
        assert h in md, h
        assert md.index(h) > details_pos, f"{h} should appear inside Diagnostic Details"
    assert "</details>" in md
    assert md.index("<details>") < md.index("</details>")


def test_narrative_answers_the_four_operator_questions():
    md = TroubleshootReport(_full_session()).to_markdown()
    assert "The neighbor is stuck in **ExStart**" in md          # what's broken
    assert "master/slave not yet negotiated" in md                # why (what this means)
    assert "MTU mismatch between OSPF neighbors" in md           # most likely cause
    assert "**Confidence:** 85%" in md or "**Confidence:** 8" in md  # how sure
    assert "adjacency hangs in EXSTART because the DBD exchange fails" in md  # here's why
    assert "ip ospf mtu-ignore" in md                            # what to do


def test_narrative_omits_compiled_signature_citation_but_diagnostics_keeps_it():
    md = TroubleshootReport(_full_session()).to_markdown()
    narrative, diagnostics = md.split("<details>", 1)
    assert "compiled signature confidence" not in narrative.lower()
    assert "compiled signature confidence" in diagnostics.lower()


def test_if_not_try_these_lists_alternates_and_mentions_ruled_out():
    md = TroubleshootReport(_full_session()).to_markdown()
    narrative = md.split("<details>", 1)[0]
    assert "### 🔁 If Not, Try These" in narrative
    assert "Timer mismatch between neighbors" in narrative
    assert "Already ruled out: Hello/dead interval mismatch" in narrative


def test_old_standalone_headers_are_gone():
    md = TroubleshootReport(_full_session()).to_markdown()
    assert "### 🎯 Likely Root Cause" not in md
    assert "### ✅ Verification Plan" not in md
    assert "### 🏁 Final Resolution Status" not in md
    # "### 🛠️ Recommended Fix" replaced by "### 🛠️ Fix This"
    assert "### 🛠️ Recommended Fix" not in md


def test_graceful_degradation_with_no_reasoning_chain_no_fix_no_alternates():
    session = Session(goal=Goal(query="why OSPF stuck", objective="Diagnose OSPF"))
    top = Hypothesis(statement="Some cause")
    top.set_prior(0.6)
    session.hypotheses.append(top)

    md = TroubleshootReport(session).to_markdown()
    assert "### 📍 You Are Here\nDiagnose OSPF" in md
    assert "### 💬 What This Means" not in md
    assert "### 🧭 Most Likely Cause\nSome cause" in md
    assert "### 🔁 If Not, Try These" not in md
    assert "_pending root-cause confirmation_" in md
    assert "_no fix generated — see resolution status_" in md


def test_no_hypotheses_at_all_shows_undetermined():
    session = Session(goal=Goal(query="why OSPF stuck", objective="Diagnose OSPF"))
    md = TroubleshootReport(session).to_markdown()
    assert "### 🧭 Most Likely Cause\n_undetermined_" in md
    assert "### 🗣️ Here's Why" not in md
