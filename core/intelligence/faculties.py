"""
core/intelligence/faculties.py
==============================
The founding cognitive faculties of the platform — the reasoning abilities a
world-class engineer has that this platform conspicuously lacked.

Each faculty is a registered Reasoner (see reasoning.py) and is GROUNDED in
the platform's real organs (AI client, operational memory), not a stub:

  • HypothesisGenerator — abductive reasoning. Given symptoms, generate the
    set of *plausible explanations* ranked by likelihood, grounded in past
    experience (operational memory). Diagnosis begins with hypotheses; a
    platform that jumps to one cause without enumerating alternatives is not
    reasoning, it is guessing. (Borrowed principle: differential diagnosis in
    medicine, fault-tree analysis in aerospace.)

  • SelfCritic — metacognition. Examines another faculty's conclusion for
    overconfidence, missing evidence, and unconsidered alternatives, and
    returns a trust multiplier. The ability to doubt one's own conclusion is
    the difference between an expert and a confident amateur. (Borrowed
    principle: red-teaming in military command; pre-mortems in decision
    science.)

  • ConfidenceCalibrator — knowing how much to trust yourself. Converts a raw
    conclusion + its evidence + historical accuracy into a *calibrated*
    confidence, so the platform neither over- nor under-trusts itself.
    (Borrowed principle: Brier-score calibration in forecasting; uncertainty
    quantification in control systems.)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from core.intelligence.reasoning import (
    Reasoner, ReasonerSpec, Conclusion, Evidence, EpistemicType,
)

logger = logging.getLogger("NetBrain.Intelligence.Faculties")


def _ai():
    """Reuse the platform's existing AI client; None if unavailable."""
    try:
        from app import call_ai
        return call_ai
    except Exception:
        return None


def _memory():
    try:
        from core.intelligence.operational_memory import get_operational_memory
        return get_operational_memory()
    except Exception:
        return None


def _extract_json(text: str):
    if not text:
        return None
    m = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════════════════
# HYPOTHESIS GENERATION — abductive reasoning
# ════════════════════════════════════════════════════════════════════════════
class HypothesisGenerator(Reasoner):
    def __init__(self):
        super().__init__(ReasonerSpec(
            key="hypothesis_generation",
            name="Hypothesis Generation",
            purpose="Given symptoms, generate ranked plausible explanations "
                    "(abductive reasoning), grounded in past experience.",
            epistemic_type=EpistemicType.HYBRID,
            consumes=[], cost_hint="medium", maturity="II",
        ))

    def _reason(self, context: Dict[str, Any]) -> Conclusion:
        symptoms = context.get("symptoms") or context.get("query") or ""
        protocol = context.get("protocol", "")
        if not symptoms:
            return Conclusion(claim="No symptoms provided to hypothesize from.",
                              confidence=0.0, epistemic_type="hybrid",
                              alternatives=[])

        # Ground in real experience: has memory seen anything like this?
        prior = []
        mem = _memory()
        if mem:
            try:
                prior = mem.similar(symptoms, top_k=5)
            except Exception:
                prior = []
        prior_block = ""
        if prior:
            prior_block = "PAST EXPERIENCE (similar situations the platform remembers):\n" + \
                "\n".join(f"- {p.get('summary','')} (outcome={p.get('outcome','?')})"
                          for p in prior)

        ai = _ai()
        if not ai:
            # Deterministic degraded mode: still enumerate from memory.
            hyps = [p.get("summary", "") for p in prior][:5] or ["insufficient data for hypotheses"]
            return Conclusion(
                claim=f"Most likely: {hyps[0]}", confidence=0.3 if prior else 0.1,
                epistemic_type="hybrid",
                evidence=[Evidence("memory", h, 0.5) for h in hyps],
                alternatives=hyps[1:])

        prompt = (
            "You are a CCIE-level network engineer performing DIFFERENTIAL DIAGNOSIS. "
            "Given the symptoms, generate the set of plausible root-cause HYPOTHESES, "
            "ranked most-to-least likely. Do not jump to one answer — enumerate "
            "alternatives like a doctor considering a differential.\n\n"
            f"SYMPTOMS: {symptoms}\n"
            f"PROTOCOL: {protocol or 'unspecified'}\n\n"
            f"{prior_block}\n\n"
            "Respond ONLY as JSON: "
            '{"hypotheses":[{"cause":"...","likelihood":0.0-1.0,"why":"...",'
            '"test":"a show command that would confirm/deny"}]}. '
            "Order by likelihood descending."
        )
        data = _extract_json(ai(prompt) or "")
        hyps = (data or {}).get("hypotheses", []) if isinstance(data, dict) else []
        if not hyps:
            # AI returned nothing usable — fall back to memory-grounded hypotheses
            # rather than giving up. Reasoning from experience beats silence.
            if prior:
                return Conclusion(
                    claim=f"Most likely (from experience): {prior[0].get('summary','')}",
                    confidence=0.35, epistemic_type="hybrid",
                    evidence=[Evidence("memory", p.get("summary",""),
                                       float(p.get("score", 0.5))) for p in prior],
                    alternatives=[p.get("summary","") for p in prior[1:]])
            return Conclusion(claim="Insufficient data to form hypotheses.",
                              confidence=0.1, epistemic_type="hybrid")
        top = hyps[0]
        # confidence reflects the top hypothesis likelihood, boosted if memory agrees
        conf = float(top.get("likelihood", 0.5))
        if prior:
            conf = min(1.0, conf + 0.1)
        return Conclusion(
            claim=f"Most likely cause: {top.get('cause','')}",
            confidence=round(conf, 4), epistemic_type="hybrid",
            evidence=[Evidence("differential", f"{h.get('cause')} (p={h.get('likelihood')}): {h.get('why','')}",
                               float(h.get("likelihood", 0))) for h in hyps],
            alternatives=[h.get("cause", "") for h in hyps[1:]],
            metadata={"hypotheses": hyps, "tests": [h.get("test") for h in hyps]},
        )


# ════════════════════════════════════════════════════════════════════════════
# SELF-CRITIQUE — metacognition
# ════════════════════════════════════════════════════════════════════════════
class SelfCritic(Reasoner):
    def __init__(self):
        super().__init__(ReasonerSpec(
            key="self_critique",
            name="Self-Critique",
            purpose="Examine a conclusion for overconfidence, missing evidence, "
                    "and unconsidered alternatives; return a trust multiplier.",
            epistemic_type=EpistemicType.LLM,
            consumes=[], cost_hint="low", maturity="II",
        ))

    def _reason(self, context: Dict[str, Any]) -> Conclusion:
        target = context.get("target_conclusion")
        if target is None:
            # nothing to critique → neutral (trust unchanged)
            return Conclusion(claim="No conclusion supplied to critique.",
                              confidence=1.0, epistemic_type="llm")

        claim = getattr(target, "claim", str(target))
        ev = getattr(target, "evidence", []) or []
        alts = getattr(target, "alternatives", []) or []
        raw_conf = getattr(target, "confidence", 0.5)

        # Heuristic critique (always available, deterministic):
        flags = []
        if raw_conf > 0.8 and len(ev) < 2:
            flags.append("high confidence on thin evidence")
        if raw_conf > 0.7 and not alts:
            flags.append("no alternatives considered (possible tunnel vision)")
        if not ev:
            flags.append("no grounding evidence")

        ai = _ai()
        ai_note = ""
        if ai:
            prompt = (
                "You are a red-team reviewer of a network engineering conclusion. "
                "Find the WEAKEST point: is it overconfident, missing evidence, or "
                "ignoring a plausible alternative? Be terse and specific.\n\n"
                f"CONCLUSION: {claim}\n"
                f"STATED CONFIDENCE: {raw_conf}\n"
                f"EVIDENCE COUNT: {len(ev)}\n"
                f"ALTERNATIVES CONSIDERED: {alts or 'none'}\n\n"
                "Respond ONLY as JSON: "
                '{"trust_multiplier":0.0-1.0,"critique":"one sentence"}. '
                "trust_multiplier<1 means discount the conclusion."
            )
            data = _extract_json(ai(prompt) or "")
            if isinstance(data, dict):
                mult = float(data.get("trust_multiplier", 1.0))
                ai_note = data.get("critique", "")
            else:
                mult = 1.0
        else:
            # deterministic fallback: each flag discounts trust
            mult = max(0.4, 1.0 - 0.2 * len(flags))

        # combine heuristic flags into the multiplier
        if flags:
            mult = min(mult, max(0.4, 1.0 - 0.15 * len(flags)))
        critique = ai_note or ("; ".join(flags) if flags else "no significant weaknesses found")
        return Conclusion(
            claim=critique, confidence=round(mult, 4), epistemic_type="llm",
            metadata={"flags": flags, "trust_multiplier": round(mult, 4)},
        )


# ════════════════════════════════════════════════════════════════════════════
# CONFIDENCE CALIBRATION — knowing how much to trust yourself
# ════════════════════════════════════════════════════════════════════════════
class ConfidenceCalibrator(Reasoner):
    """
    Adjusts a raw confidence toward a *calibrated* one using evidence strength
    and the platform's historical accuracy for this kind of claim. Prevents
    both overconfidence (acting on guesses) and underconfidence (paralysis).
    """
    def __init__(self):
        super().__init__(ReasonerSpec(
            key="confidence_calibration",
            name="Confidence Calibration",
            purpose="Convert raw confidence + evidence + historical accuracy "
                    "into a calibrated confidence.",
            epistemic_type=EpistemicType.PROBABILISTIC,
            consumes=[], cost_hint="low", maturity="III",
        ))

    def _reason(self, context: Dict[str, Any]) -> Conclusion:
        target = context.get("target_conclusion")
        raw = context.get("raw_confidence")
        if target is not None:
            raw = getattr(target, "confidence", raw)
            evidence = getattr(target, "evidence", []) or []
        else:
            evidence = context.get("evidence", []) or []
        if raw is None:
            return Conclusion(claim="No confidence to calibrate.", confidence=0.0,
                              epistemic_type="probabilistic")

        # Evidence strength: more & stronger evidence → trust the raw value more;
        # little evidence → regress toward a prior of 0.5 (max uncertainty).
        ev_strength = 0.0
        if evidence:
            try:
                ev_strength = min(1.0, sum(getattr(e, "weight", 0.5) for e in evidence) / 3.0)
            except Exception:
                ev_strength = 0.4
        prior = 0.5
        # regression-to-prior weighted by how much evidence we have
        calibrated = ev_strength * float(raw) + (1 - ev_strength) * prior

        # Historical accuracy: if memory shows this claim-type has been wrong
        # before, pull confidence down further (learning from being wrong).
        mem = _memory()
        hist_adj = 0.0
        if mem and target is not None:
            try:
                sims = mem.similar(getattr(target, "claim", ""), top_k=5)
                if sims:
                    fails = sum(1 for s in sims if s.get("outcome") == "failure")
                    if fails:
                        hist_adj = -0.1 * (fails / len(sims))
            except Exception:
                pass
        calibrated = max(0.0, min(1.0, calibrated + hist_adj))
        return Conclusion(
            claim=f"Calibrated confidence {calibrated:.2f} (raw {float(raw):.2f})",
            confidence=round(calibrated, 4), epistemic_type="probabilistic",
            metadata={"raw": float(raw), "evidence_strength": round(ev_strength, 3),
                      "history_adjustment": round(hist_adj, 3)},
        )


def build_default_faculties() -> List[Reasoner]:
    return [HypothesisGenerator(), SelfCritic(), ConfidenceCalibrator()]
