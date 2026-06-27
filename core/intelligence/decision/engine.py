"""
core/intelligence/decision/engine.py
=====================================
The Deliberation Engine — where appraisals become a judgment.

Given a decision (a set of options in context), it lets every faculty appraise
every option, then composes those appraisals the way a senior architect composes
considerations:

  • hard constraints first — an ethically/operationally vetoed option is off the
    table no matter how attractive it scores elsewhere;
  • multi-criteria aggregation — a weighted blend of the remaining axes, so no
    single number ("lowest risk", "cheapest") wins by itself;
  • confidence from agreement — the judgment is only as confident as the
    faculties' consensus and the evidence behind it; genuine disagreement lowers
    confidence and surfaces as recorded dissent rather than being hidden;
  • explanation — the chosen option comes with its decisive factors, the
    tradeoffs accepted, the second-order effects, the counterfactual of doing
    nothing, and why the runner-up lost.

The result is a Judgment, exposed to the existing reasoning architecture as a
Reasoner so it composes with hypothesis/critique/calibration, and run past the
autonomy safety gate so a confident judgment still cannot bypass approval. Every
judgment is recorded so the platform's decisions improve over time.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, List, Optional

from core.intelligence.decision.base import (
    Option, DecisionContext, Appraisal, OptionVerdict, Judgment,
    DecisionFacultyRegistry,
)
from core.intelligence.decision.faculties import build_appraisers, build_holistic

logger = logging.getLogger("NetBrain.Intelligence.Decision")


def _stdev(xs: List[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


class DeliberationEngine:
    def __init__(self):
        self.registry = DecisionFacultyRegistry()
        for f in build_appraisers():
            self.registry.register(f)
        self.holistic = build_holistic()
        self._judgments = 0

    # ── the act of judgment ──────────────────────────────────────────────────
    def judge(self, ctx: DecisionContext, *, record: bool = True) -> Judgment:
        ctx = ctx.with_status_quo()
        self._judgments += 1
        appraisers = self.registry.all()

        verdicts: List[OptionVerdict] = []
        for o in ctx.options:
            appraisals = [f.appraise(o, ctx) for f in appraisers]
            vetoes = [a for a in appraisals if a.veto]
            scored = [a for a in appraisals if not a.veto]
            wsum = sum(a.weight for a in scored) or 1.0
            value = sum(a.merit * a.weight for a in scored) / wsum
            # risk-adjust: shrink value toward 0 by the spread of low-merit axes
            merits = [a.merit for a in scored]
            disagreement = _stdev(merits)
            value = value * (1 - 0.25 * disagreement)
            conf = sum(a.confidence for a in scored) / max(1, len(scored))
            verdicts.append(OptionVerdict(
                option=o, value=round(value, 4), confidence=round(conf, 4),
                appraisals=appraisals, vetoed=bool(vetoes),
                veto_reasons=[a.rationale for a in vetoes]))

        # holistic passes (comparison, counterfactual)
        holistic: Dict[str, Any] = {}
        for hf in self.holistic:
            try:
                holistic.update(hf.deliberate(ctx, verdicts))
            except Exception as exc:
                logger.debug(f"holistic {hf.spec.key}: {exc}")

        # choose: best non-vetoed by value
        viable = [v for v in verdicts if not v.vetoed]
        ranking = sorted(verdicts, key=lambda v: (not v.vetoed, v.value), reverse=True)
        chosen_v = max(viable, key=lambda v: v.value) if viable else None

        judgment = self._compose(ctx, chosen_v, ranking, holistic)
        if record:
            self._record(ctx, judgment)
        return judgment

    # ── compose the explained judgment ───────────────────────────────────────
    def _compose(self, ctx: DecisionContext, chosen_v: Optional[OptionVerdict],
                 ranking: List[OptionVerdict], holistic: Dict[str, Any]) -> Judgment:
        if chosen_v is None:
            reasons = []
            for v in ranking:
                if v.vetoed:
                    reasons.append(f"“{v.option.label}”: {', '.join(v.veto_reasons)}")
            return Judgment(
                question=ctx.question, chosen=None, ranking=ranking, confidence=0.9,
                rationale="Every actionable option is barred by a hard constraint.",
                dissent=reasons, requires_human=True,
                metadata={"holistic": holistic})

        chosen = chosen_v.option
        # decision confidence: faculty agreement × evidence × margin over runner-up
        merits = [a.merit for a in chosen_v.appraisals if not a.veto]
        agreement = 1 - min(1.0, 2 * _stdev(merits))
        evidence = chosen_v.confidence
        runner = next((v for v in ranking if v.option.id != chosen.id and not v.vetoed), None)
        margin = (chosen_v.value - runner.value) if runner else 0.3
        margin_conf = min(1.0, 0.5 + margin)
        confidence = round(max(0.05, 0.4 * agreement + 0.35 * evidence + 0.25 * margin_conf), 4)

        # decisive factors (most influential appraisals) and dissent
        factors = chosen_v.top_factors(3)
        pros = [f"{a.faculty}: {a.rationale}" for a in factors if a.merit >= 0.55]
        cons = [f"{a.faculty}: {a.rationale}" for a in chosen_v.appraisals
                if a.merit < 0.4 and not a.veto]
        dissent = cons[:3]

        # tradeoffs: where the chosen option is weak but we accepted it
        tradeoffs = []
        for a in chosen_v.appraisals:
            if 0.3 <= a.merit < 0.5 and not a.veto:
                tradeoffs.append(f"accepts weaker {a.faculty} ({a.rationale})")
        # second-order from the faculty that computed ripples
        so = next((a for a in chosen_v.appraisals if a.faculty == "second_order_effects"), None)
        second_order = (so.metadata.get("effects", []) if so else []) or []

        rationale = (f"“{chosen.label}” wins on " +
                     (", ".join(p.split(':')[0] for p in pros[:3]) or "balance of factors") +
                     (f"; chosen over “{runner.option.label}” by {margin:+.0%} value."
                      if runner else "."))

        # run past the autonomy safety gate (judgment proposes, gate disposes)
        requires_human = False
        gate_note = ""
        if chosen.changes_state and not chosen.is_status_quo:
            try:
                from core.intelligence.autonomy import authorize, Action
                d = authorize(Action(kind="config_change", intent=chosen.intent,
                                     device=chosen.device, protocol=chosen.protocol,
                                     site=chosen.site, operator=ctx.operator))
                if not d.allowed:
                    requires_human = True
                    gate_note = f"safety gate: {d.verdict.value} ({'; '.join(d.reasons[:2])})"
            except Exception:
                requires_human = True
        # low confidence or thin margin or low value also needs a human
        if confidence < 0.6 or chosen_v.value < 0.55 or (runner and margin < 0.08):
            requires_human = requires_human or chosen.changes_state
        if gate_note:
            dissent = dissent + [gate_note]

        return Judgment(
            question=ctx.question, chosen=chosen, ranking=ranking,
            confidence=confidence, rationale=rationale, tradeoffs=tradeoffs[:3],
            second_order=second_order[:3],
            counterfactual=holistic.get("counterfactual", ""),
            dissent=dissent, requires_human=requires_human,
            metadata={"holistic": holistic, "agreement": round(agreement, 3),
                      "margin": round(margin, 3),
                      "pros": pros, "value": chosen_v.value})

    # ── learning loop: every judgment is recorded ────────────────────────────
    def _record(self, ctx: DecisionContext, j: Judgment) -> None:
        try:
            from core.intelligence.memory import get_memory_system
            sysm = get_memory_system()
            if j.chosen:
                sysm.decision.record(
                    f"{j.chosen.protocol or 'generic'}:{ctx.question[:50]}",
                    "act" if j.chosen.changes_state and not j.chosen.is_status_quo else "hold",
                    rationale=j.rationale, outcome="unknown")
        except Exception:
            pass

    # ── dict form for UI / API ───────────────────────────────────────────────
    def judge_dict(self, ctx: DecisionContext) -> Dict[str, Any]:
        j = self.judge(ctx)
        return {
            "question": j.question,
            "chosen": (None if not j.chosen else
                       {"id": j.chosen.id, "label": j.chosen.label,
                        "intent": j.chosen.intent, "device": j.chosen.device}),
            "confidence": j.confidence, "rationale": j.rationale,
            "tradeoffs": j.tradeoffs, "second_order": j.second_order,
            "counterfactual": j.counterfactual, "dissent": j.dissent,
            "requires_human": j.requires_human,
            "ranking": [{"label": v.option.label, "value": v.value,
                         "confidence": v.confidence, "vetoed": v.vetoed,
                         "veto_reasons": v.veto_reasons} for v in j.ranking],
            "explanation": j.explain(),
        }

    def report(self) -> Dict[str, Any]:
        return {"faculties": self.registry.report(),
                "holistic": [h.spec.key for h in self.holistic],
                "judgments_made": self._judgments}

    def health(self) -> Dict[str, Any]:
        facs = self.registry.all() + self.holistic
        active = sum(1 for f in facs if f.health()["status"] == "active")
        return {"faculties": len(facs), "active": active,
                "judgments_made": self._judgments}


# ── singleton ────────────────────────────────────────────────────────────────
_engine: Optional[DeliberationEngine] = None


def get_deliberation_engine() -> DeliberationEngine:
    global _engine
    if _engine is None:
        _engine = DeliberationEngine()
    return _engine


def _coerce_options(raw: List[Any]) -> List[Option]:
    opts = []
    for i, r in enumerate(raw or []):
        if isinstance(r, Option):
            opts.append(r)
        elif isinstance(r, dict):
            opts.append(Option(
                id=str(r.get("id", i)), label=r.get("label", f"option {i}"),
                intent=r.get("intent", ""), device=r.get("device", ""),
                protocol=r.get("protocol", ""), site=r.get("site", ""),
                reversible=r.get("reversible"), effort=r.get("effort"),
                changes_state=r.get("changes_state", True),
                attributes=r.get("attributes", {})))
        elif isinstance(r, str):
            opts.append(Option(id=str(i), label=r, intent=r))
    return opts


def judge(question: str, options: List[Any], **kw) -> Judgment:
    """Convenience: build a context and return a judgment."""
    ctx = DecisionContext(question=question, options=_coerce_options(options),
                          goal=kw.get("goal", ""), operator=kw.get("operator", "default"),
                          metadata=kw.get("metadata", {}))
    return get_deliberation_engine().judge(ctx)


# ── reasoning-architecture integration ───────────────────────────────────────
def _build_judgment_reasoner():
    from core.intelligence.reasoning import (
        Reasoner, ReasonerSpec, Conclusion, Evidence, EpistemicType)

    class Judge(Reasoner):
        def __init__(self):
            super().__init__(ReasonerSpec(
                key="judgment", name="Judgment",
                purpose="Deliberate over options and render an explained, "
                        "confidence-bearing decision (not a bare recommendation).",
                epistemic_type=EpistemicType.HYBRID,
                consumes=["forward_outlook", "lesson_recall", "case_recall"],
                cost_hint="high", maturity="III"))

        def _reason(self, context: Dict[str, Any]) -> Conclusion:
            raw = context.get("options") or []
            if not raw:
                return Conclusion(
                    "No options supplied to deliberate over; judgment needs "
                    "alternatives to compare.", 0.1, "hybrid")
            ctx = DecisionContext(
                question=context.get("question") or context.get("query") or "decision",
                options=_coerce_options(raw), goal=context.get("goal", ""),
                operator=context.get("operator", "default"),
                metadata=context.get("metadata", {}))
            j = get_deliberation_engine().judge(ctx)
            claim = (j.explain().split("\n")[0] if j.chosen
                     else "No acceptable option — escalate.")
            ev = []
            if j.chosen:
                for v in j.ranking[:4]:
                    ev.append(Evidence("option", f"{v.option.label}: value {v.value:.0%}"
                                       + (" [vetoed]" if v.vetoed else ""), v.value))
            return Conclusion(
                claim=claim, confidence=j.confidence, epistemic_type="hybrid",
                evidence=ev,
                alternatives=[v.option.label for v in j.ranking[1:4]],
                metadata={"rationale": j.rationale, "tradeoffs": j.tradeoffs,
                          "counterfactual": j.counterfactual,
                          "requires_human": j.requires_human})

    return Judge()


def wire_decision() -> Dict[str, Any]:
    result = {"faculties": 0, "reasoner": False, "pillar": False}
    engine = get_deliberation_engine()
    result["faculties"] = len(engine.registry.all()) + len(engine.holistic)

    try:
        from core.intelligence.reasoning import get_reasoning_registry
        get_reasoning_registry().register(_build_judgment_reasoner())
        result["reasoner"] = True
    except Exception as exc:
        logger.debug(f"judgment reasoner deferred: {exc}")

    try:
        from core.intelligence.capability_model import (
            get_capability_registry, Capability, CapabilityHealth, CapabilityStatus)

        def _probe():
            h = engine.health()
            return CapabilityHealth(
                CapabilityStatus.ACTIVE,
                f"Deliberation across {h['faculties']} judgment faculties "
                f"(tradeoffs, ethics-veto, second-order, counterfactual, "
                f"reversibility, regret); {h['judgments_made']} judgments rendered.",
                metrics=h)
        get_capability_registry().register(Capability(
            "judgment", "Judgment",
            "Weighs competing considerations into an explained, confidence-bearing "
            "decision with tradeoffs, alternatives, counterfactuals and second-order "
            "effects — judgment, not recommendation.",
            "core/intelligence/decision/engine.py",
            ["reasoning", "prediction", "risk", "memory", "decision"], _probe))
        result["pillar"] = True
    except Exception as exc:
        logger.debug(f"judgment pillar deferred: {exc}")

    return result
