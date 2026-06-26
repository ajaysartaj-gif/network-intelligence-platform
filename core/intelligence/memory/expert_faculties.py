"""
core/intelligence/memory/expert_faculties.py
=============================================
New cognitive faculties that turn the derived memories into better reasoning.

Memory is inert until something reasons from it. These Reasoners plug into the
existing ReasoningRegistry (same contract as HypothesisGenerator et al.) and let
the rest of the platform consult accumulated experience the way a senior
engineer's instinct does:

  • CaseRecall          — "have we seen this before?" (episodic, case-based)
  • ProceduralRecall    — "what worked last time?" (known-good playbook)
  • FailureAvoidance    — "what must we NOT do here?" (scar tissue → veto/caution)
  • ExpertiseEstimator  — "how good are we at this?" (earned autonomy)
  • OutcomePredictor    — "will this succeed, and how risky is now?" (and it
                          logs the prediction so it can later be scored)
  • OperatorAligner     — "what would THIS operator want?"

Each returns a calibrated Conclusion with grounded Evidence, so they compose
with self-critique and confidence-calibration exactly like the founding
faculties.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from core.intelligence.reasoning import (
    Reasoner, ReasonerSpec, Conclusion, Evidence, EpistemicType,
)

logger = logging.getLogger("NetBrain.Intelligence.Memory.Faculties")


def _sys():
    from core.intelligence.memory.memory_system import get_memory_system
    return get_memory_system()


class CaseRecall(Reasoner):
    def __init__(self):
        super().__init__(ReasonerSpec(
            key="case_recall", name="Case Recall",
            purpose="Recall the most similar past incident as a whole case "
                    "(case-based reasoning) to guide the present one.",
            epistemic_type=EpistemicType.HYBRID, cost_hint="low", maturity="III"))

    def _reason(self, context: Dict[str, Any]) -> Conclusion:
        sit = context.get("symptoms") or context.get("query") or ""
        if not sit:
            return Conclusion("No situation to recall cases for.", 0.0, "hybrid")
        cases = _sys().episodic.similar_cases(sit, top_k=3)
        if not cases:
            return Conclusion("No comparable past case in memory.", 0.1, "hybrid")
        top = cases[0]
        conf = 0.6 if top.get("resolved") else 0.35
        return Conclusion(
            claim=(f"Seen before on {top.get('device') or 'the network'}: "
                   f"{top.get('known_fix') or top.get('root_cause') or top.get('story','')}"),
            confidence=conf, epistemic_type="hybrid",
            evidence=[Evidence("episodic", c.get("story", ""),
                               0.6 if c.get("resolved") else 0.3) for c in cases],
            alternatives=[c.get("story", "") for c in cases[1:]],
            metadata={"cases": cases})


class ProceduralRecall(Reasoner):
    def __init__(self):
        super().__init__(ReasonerSpec(
            key="procedural_recall", name="Procedural Recall",
            purpose="Recall the known-good command procedure for an intent, with "
                    "its historical success rate.",
            epistemic_type=EpistemicType.PROBABILISTIC, cost_hint="low", maturity="III"))

    def _reason(self, context: Dict[str, Any]) -> Conclusion:
        intent = context.get("intent") or context.get("query") or ""
        protocol = context.get("protocol", "")
        if not intent:
            return Conclusion("No intent to recall a procedure for.", 0.0, "probabilistic")
        best = _sys().procedural.best_for(intent, protocol, min_rate=0.5)
        if not best:
            return Conclusion("No proven procedure yet for this intent.", 0.15,
                              "probabilistic")
        return Conclusion(
            claim=f"Known-good procedure ({best['success_rate']:.0%} over "
                  f"{best['attempts']} runs) available.",
            confidence=float(best["success_rate"]), epistemic_type="probabilistic",
            evidence=[Evidence("procedural", c, 0.7) for c in best["commands"][:8]],
            metadata={"procedure": best})


class FailureAvoidance(Reasoner):
    def __init__(self):
        super().__init__(ReasonerSpec(
            key="failure_avoidance", name="Failure Avoidance",
            purpose="Surface contraindications (scar tissue) for a proposed "
                    "action and advise veto or caution.",
            epistemic_type=EpistemicType.PROBABILISTIC, safety_class="gated",
            cost_hint="low", maturity="III"))

    def _reason(self, context: Dict[str, Any]) -> Conclusion:
        action = context.get("intent") or context.get("action") or context.get("query") or ""
        ctx = context.get("protocol") or context.get("device") or ""
        probe = f"{action} {ctx}".strip()
        if not probe:
            return Conclusion("No action to check against failure memory.", 1.0,
                              "probabilistic")
        scars = _sys().failure.contraindications(probe, top_k=4, min_weight=0.15)
        if not scars:
            return Conclusion("No prior failures contraindicate this action.", 0.85,
                              "probabilistic")
        worst = scars[0]
        sev = float((worst.get("extra") or {}).get("severity", 0)
                    or worst.get("weight", 0.5))
        veto = worst.get("weight", 0) >= 0.6
        return Conclusion(
            claim=("VETO: " if veto else "CAUTION: ") + worst.get("summary", ""),
            confidence=round(1.0 - min(0.8, worst.get("weight", 0.3)), 4),
            epistemic_type="probabilistic",
            evidence=[Evidence("failure", s.get("summary", ""), s.get("weight", 0.3))
                      for s in scars],
            metadata={"veto": veto, "contraindications": scars})


class ExpertiseEstimator(Reasoner):
    def __init__(self):
        super().__init__(ReasonerSpec(
            key="expertise_estimator", name="Expertise Estimator",
            purpose="Report the platform's earned competence in a domain and "
                    "whether it has earned autonomy there.",
            epistemic_type=EpistemicType.PROBABILISTIC, cost_hint="low", maturity="III"))

    def _reason(self, context: Dict[str, Any]) -> Conclusion:
        domain = (context.get("protocol") or context.get("domain")
                  or context.get("intent") or "general")
        comp = _sys().experience.competence(domain)
        return Conclusion(
            claim=f"{comp['level']} at {domain} "
                  f"({comp['success_rate']:.0%} over {comp['attempts']}); "
                  f"autonomy {'earned' if comp['autonomy_ok'] else 'not earned'}.",
            confidence=float(comp["success_rate"]), epistemic_type="probabilistic",
            metadata=comp)


class OutcomePredictor(Reasoner):
    def __init__(self):
        super().__init__(ReasonerSpec(
            key="outcome_predictor", name="Outcome Predictor",
            purpose="Predict whether a proposed change will succeed, combining "
                    "procedural success, experience and temporal risk; logs the "
                    "prediction to be scored later.",
            epistemic_type=EpistemicType.PROBABILISTIC,
            consumes=["procedural_recall", "expertise_estimator"],
            cost_hint="low", maturity="III"))

    def _reason(self, context: Dict[str, Any]) -> Conclusion:
        intent = context.get("intent") or context.get("query") or ""
        protocol = context.get("protocol", "")
        device = context.get("device", "")
        domain = protocol or "general"
        s = _sys()
        proc = s.procedural.best_for(intent, protocol, min_rate=0.0)
        comp = s.experience.competence(domain)
        p_proc = proc["success_rate"] if proc else 0.5
        p_exp = comp["success_rate"] if comp["attempts"] else 0.5
        p = round(0.6 * p_proc + 0.4 * p_exp, 4)
        # temporal risk adjusts the estimate down at unusually failure-heavy times
        trisk = s.temporal.risk_now(f"domain:{domain}")
        if trisk.get("elevated"):
            p = round(max(0.05, p - 0.1), 4)
        # empirical self-calibration from trust memory
        cal = s.trust.calibrate(domain, p)
        p = cal["calibrated"]
        try:
            s.prediction.predict(f"{domain}:{device}", f"{intent} will succeed", p)
        except Exception:
            pass
        return Conclusion(
            claim=f"Estimated success {p:.0%} for «{intent}»"
                  + (" (elevated-risk window)" if trisk.get("elevated") else ""),
            confidence=p, epistemic_type="probabilistic",
            evidence=[Evidence("procedural", f"proc success {p_proc:.0%}", 0.6),
                      Evidence("experience", f"{comp['level']} ({p_exp:.0%})", 0.5),
                      Evidence("temporal", trisk.get("detail", ""), 0.3),
                      Evidence("trust", cal.get("basis", ""), 0.4)],
            metadata={"temporal": trisk, "calibration": cal})


class OperatorAligner(Reasoner):
    def __init__(self):
        super().__init__(ReasonerSpec(
            key="operator_aligner", name="Operator Aligner",
            purpose="Recall what this operator tends to want (auto-approve / "
                    "review / reject) for this kind of change.",
            epistemic_type=EpistemicType.PROBABILISTIC, cost_hint="low", maturity="II"))

    def _reason(self, context: Dict[str, Any]) -> Conclusion:
        operator = context.get("operator") or "default"
        intent = context.get("intent") or context.get("query") or ""
        protocol = context.get("protocol", "")
        from core.intelligence.memory.consolidation import _class_intent
        subject = f"{protocol or 'generic'}:{_class_intent(intent)}"
        st = _sys().operator.stance_for(operator, "approval", subject)
        if not st:
            return Conclusion("No learned preference for this operator/action yet.",
                              0.2, "probabilistic")
        return Conclusion(
            claim=f"{operator} usually wants: {st['stance']} for {subject}.",
            confidence=float(st.get("confidence") or 0.5),
            epistemic_type="probabilistic", metadata=st)


def build_expert_faculties() -> List[Reasoner]:
    return [CaseRecall(), ProceduralRecall(), FailureAvoidance(),
            ExpertiseEstimator(), OutcomePredictor(), OperatorAligner()]


def register_expert_faculties() -> int:
    """Register all expert faculties into the shared reasoning registry."""
    try:
        from core.intelligence.reasoning import get_reasoning_registry
        reg = get_reasoning_registry()
        facs = build_expert_faculties()
        for f in facs:
            reg.register(f)
        return len(facs)
    except Exception as exc:
        logger.debug(f"expert faculty registration deferred: {exc}")
        return 0
