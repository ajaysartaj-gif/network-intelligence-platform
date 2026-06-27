"""
core/intelligence/decision/faculties.py
========================================
The faculties of judgment. Each appraises an option along one axis a senior
architect weighs — and each is grounded in the platform's real organs
(forecasting, memory, learning), never in stubs.

Appraising faculties return a merit in [0,1] (1 = strongly favours the option).
Hard-constraint faculties (ethics/safety) may VETO instead of scoring, because
some lines cannot be bought out by benefit elsewhere. Two holistic faculties
(alternative comparison, counterfactual) reason across all options at once.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from core.intelligence.decision.base import (
    DecisionFaculty, FacultySpec, Option, DecisionContext, Appraisal, OptionVerdict,
)


# ── lazy organs ──────────────────────────────────────────────────────────────
def _sys():
    from core.intelligence.memory import get_memory_system
    return get_memory_system()


def _pred():
    from core.intelligence.forecasting import get_prediction_engine
    return get_prediction_engine()


def _learn():
    from core.intelligence.learning import get_learning_engine
    return get_learning_engine()


def _board(option: Option, ctx: DecisionContext, only: Optional[List[str]] = None):
    """Per-option forecast board, cached on the context for the deliberation."""
    cache = ctx.metadata.setdefault("_forecast_cache", {})
    ck = (option.id, tuple(only or []))
    if ck in cache:
        return cache[ck]
    try:
        board = _pred().forecast(
            {"device": option.device, "intent": option.intent,
             "protocol": option.protocol, "site": option.site},
            only=only, log=False)
    except Exception:
        board = []
    cache[ck] = board
    return board


def _risk_of(option: Option, ctx: DecisionContext) -> float:
    if option.is_status_quo:
        # inaction is not free: its "risk" is the unresolved problem's severity.
        return float(ctx.metadata.get("problem_severity", 0.2))
    board = _board(option, ctx)
    return max([0.0] + [f.risk for f in board])


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


# ════════════════════════════════════════════════════════════════════════════
class RiskBalancing(DecisionFaculty):
    def __init__(self):
        super().__init__(FacultySpec("risk_balancing", "Risk Balancing", "risk",
                         "Balances expected risk against reward.", default_weight=1.3))

    def _appraise(self, o: Option, ctx: DecisionContext) -> Appraisal:
        risk = _risk_of(o, ctx)
        merit = clamp(1 - risk)
        return Appraisal(self.spec.key, merit, confidence=0.7,
                         rationale=f"expected risk {risk:.0%}", metadata={"risk": risk})


class BusinessPrioritization(DecisionFaculty):
    def __init__(self):
        super().__init__(FacultySpec("business_prioritization", "Business Prioritization",
                         "business", "Weights options by business value served.",
                         default_weight=1.3))

    def _appraise(self, o: Option, ctx: DecisionContext) -> Appraisal:
        try:
            crit = float(_sys().business.impact_of(o.device).get("criticality") or 0.3) if o.device else 0.3
        except Exception:
            crit = 0.3
        problem = float(ctx.metadata.get("problem_severity", 0.0))
        if o.is_status_quo:
            # doing nothing on a high-criticality problem is low business merit.
            merit = clamp(1 - crit * problem)
            rat = f"holding leaves a {crit:.0%}-critical asset exposed"
        else:
            # acting to serve a critical asset is high business merit.
            merit = clamp(0.4 + 0.6 * crit)
            rat = f"serves asset criticality {crit:.0%}"
        return Appraisal(self.spec.key, merit, 0.65, rat, metadata={"criticality": crit})


class TradeoffAnalysis(DecisionFaculty):
    def __init__(self):
        super().__init__(FacultySpec("tradeoff_analysis", "Tradeoff Analysis", "tradeoff",
                         "Rewards options balanced across the core tension "
                         "(value vs safety), penalises lopsided ones.",
                         default_weight=1.1))

    def _appraise(self, o: Option, ctx: DecisionContext) -> Appraisal:
        safety = clamp(1 - _risk_of(o, ctx))
        # quick value proxy: proven success likelihood of the action
        board = _board(o, ctx, only=["deployment_success"])
        value = (board[0].probability if board and board[0].probability is not None
                 else (0.5 if not o.is_status_quo else 0.4))
        # harmonic mean rewards being good on BOTH, not great on one.
        merit = 0.0 if (safety + value) == 0 else 2 * safety * value / (safety + value)
        gap = abs(safety - value)
        return Appraisal(self.spec.key, clamp(merit), 0.6,
                         f"value {value:.0%} vs safety {safety:.0%} (imbalance {gap:.0%})",
                         metadata={"value": value, "safety": safety, "tension": gap})


class CostOptimization(DecisionFaculty):
    def __init__(self):
        super().__init__(FacultySpec("cost_optimization", "Cost Optimization", "cost",
                         "Prefers the lower-cost path to an equivalent outcome.",
                         default_weight=0.9))

    def _appraise(self, o: Option, ctx: DecisionContext) -> Appraisal:
        effort = o.effort
        if effort is None:
            n = len(o.attributes.get("commands", []) or [])
            effort = clamp(0.1 + 0.08 * n) if n else (0.0 if o.is_status_quo else 0.4)
        return Appraisal(self.spec.key, clamp(1 - effort), 0.5,
                         f"estimated effort {effort:.0%}", metadata={"effort": effort})


class OpportunityCost(DecisionFaculty):
    def __init__(self):
        super().__init__(FacultySpec("opportunity_cost", "Opportunity Cost", "opportunity",
                         "Penalises options that consume scarce windows/locks or "
                         "foreclose better futures.", default_weight=0.9))

    def _appraise(self, o: Option, ctx: DecisionContext) -> Appraisal:
        if o.is_status_quo:
            return Appraisal(self.spec.key, 0.7, 0.5, "holds optionality open")
        effort = o.effort if o.effort is not None else 0.4
        irreversible = (o.reversible is False)
        # spending a maintenance window / irreversible effort forecloses options.
        forgone = effort * (0.7 if irreversible else 0.3)
        return Appraisal(self.spec.key, clamp(1 - forgone), 0.45,
                         f"forecloses ~{forgone:.0%} of future flexibility"
                         + (" (irreversible)" if irreversible else ""))


class OperationalWisdom(DecisionFaculty):
    def __init__(self):
        super().__init__(FacultySpec("operational_wisdom", "Operational Wisdom", "experience",
                         "Applies hard-won experience and institutional lessons.",
                         default_weight=1.2))

    def _appraise(self, o: Option, ctx: DecisionContext) -> Appraisal:
        if o.is_status_quo:
            return Appraisal(self.spec.key, 0.5, 0.4, "no precedent needed to hold")
        merit, conf, notes = 0.5, 0.4, []
        try:
            comp = _sys().experience.competence(o.protocol or "general")
            merit = clamp(0.3 + 0.6 * float(comp.get("success_rate") or 0.5))
            conf = clamp(0.3 + comp.get("attempts", 0) / 50)
            notes.append(f"{comp.get('level')} ({comp.get('success_rate',0):.0%})")
        except Exception:
            pass
        try:
            lessons = _learn().lessons(f"{o.intent} {o.protocol}", top_k=3)
            for l in lessons:
                if l.get("lesson_type") == "mistake":
                    merit = clamp(merit - 0.2); notes.append("recalls a past mistake")
                elif l.get("lesson_type") == "strategy":
                    merit = clamp(merit + 0.15); notes.append("matches a proven strategy")
        except Exception:
            pass
        return Appraisal(self.spec.key, merit, conf, "; ".join(notes) or "limited experience")


class HumanFactors(DecisionFaculty):
    def __init__(self):
        super().__init__(FacultySpec("human_factors", "Human Factors", "human",
                         "Accounts for operator workload, fatigue and skill.",
                         default_weight=1.0))

    def _appraise(self, o: Option, ctx: DecisionContext) -> Appraisal:
        if o.is_status_quo:
            return Appraisal(self.spec.key, 0.7, 0.5, "no human action required")
        board = _board(o, ctx, only=["operator_error"])
        p_err = board[0].probability if board and board[0].probability is not None else 0.2
        return Appraisal(self.spec.key, clamp(1 - p_err), 0.55,
                         f"predicted operator-error {p_err:.0%}")


class EthicalConstraints(DecisionFaculty):
    """Hard constraints — may VETO. Safety, honesty, least-harm, freeze, consent."""
    def __init__(self):
        super().__init__(FacultySpec("ethical_constraints", "Ethical Constraints", "ethics",
                         "Enforces hard lines cost-benefit cannot override.",
                         default_weight=2.0, hard_constraint=True))

    def _appraise(self, o: Option, ctx: DecisionContext) -> Appraisal:
        if o.is_status_quo or not o.changes_state:
            return Appraisal(self.spec.key, 1.0, 0.9, "no hard-constraint exposure")
        reasons = []
        # 1) change freeze (consent of the business to change-control)
        try:
            fr = _sys().business.in_freeze(o.device) if o.device else {"frozen": False}
            if fr.get("frozen"):
                reasons.append(f"violates change freeze: {fr.get('reason')}")
        except Exception:
            pass
        # 2) contraindication (least-harm: don't repeat known-harmful actions)
        try:
            scars = _sys().failure.contraindications(
                f"{o.intent} {o.protocol} {o.device}", top_k=3)
            worst = max((s.get("weight", 0) for s in scars), default=0.0)
            if worst >= 0.6:
                reasons.append(f"known-harmful action (failure memory w={worst:.2f})")
        except Exception:
            pass
        # 3) honesty: a high-impact change must not proceed silently/unverifiably
        if o.attributes.get("unverifiable") and o.attributes.get("high_impact"):
            reasons.append("high-impact change cannot be verified — not honest to proceed")
        if reasons:
            return Appraisal(self.spec.key, 0.0, 0.95, "; ".join(reasons), veto=True)
        return Appraisal(self.spec.key, 1.0, 0.8, "within ethical/safety constraints")


class LongTermImpact(DecisionFaculty):
    def __init__(self):
        super().__init__(FacultySpec("long_term_impact", "Long-term Impact", "long_term",
                         "Values durable fixes over band-aids (15-year view).",
                         default_weight=1.1))

    def _appraise(self, o: Option, ctx: DecisionContext) -> Appraisal:
        if o.is_status_quo:
            sev = float(ctx.metadata.get("problem_severity", 0.2))
            return Appraisal(self.spec.key, clamp(1 - sev), 0.4,
                             "deferring may let the problem compound")
        merit, notes = 0.55, []
        try:
            lessons = _learn().lessons(f"{o.intent} {o.protocol}", top_k=3)
            if any(l.get("lesson_type") == "mistake" and
                   (l.get("extra") or {}).get("systemic") for l in lessons):
                merit -= 0.25; notes.append("addresses a symptom of a systemic recurring fault")
            if o.attributes.get("root_cause_fix"):
                merit += 0.3; notes.append("fixes root cause (durable)")
            if o.attributes.get("workaround"):
                merit -= 0.2; notes.append("workaround → future tech debt")
        except Exception:
            pass
        return Appraisal(self.spec.key, clamp(merit), 0.45, "; ".join(notes) or "neutral durability")


class ShortTermImpact(DecisionFaculty):
    def __init__(self):
        super().__init__(FacultySpec("short_term_impact", "Short-term Impact", "short_term",
                         "Values quick resolution with low immediate disruption.",
                         default_weight=1.0))

    def _appraise(self, o: Option, ctx: DecisionContext) -> Appraisal:
        if o.is_status_quo:
            return Appraisal(self.spec.key, 0.45, 0.4, "no immediate change/disruption")
        board = _board(o, ctx, only=["cascading_failure"])
        cascade = board[0].probability if board and board[0].probability is not None else 0.1
        try:
            proc = _sys().procedural.best_for(o.intent, o.protocol, min_rate=0.0)
            speed = 0.7 if proc else 0.5
        except Exception:
            speed = 0.5
        merit = clamp(0.5 * speed + 0.5 * (1 - cascade))
        return Appraisal(self.spec.key, merit, 0.55,
                         f"resolution speed {speed:.0%}, immediate blast {cascade:.0%}")


class Simulation(DecisionFaculty):
    def __init__(self):
        super().__init__(FacultySpec("simulation", "Simulation", "simulation",
                         "Projects the outcome of each option before committing.",
                         default_weight=1.2))

    def _appraise(self, o: Option, ctx: DecisionContext) -> Appraisal:
        if o.is_status_quo:
            return Appraisal(self.spec.key, 0.5, 0.4, "baseline: no simulated change")
        board = _board(o, ctx, only=["deployment_success", "cascading_failure", "rollback_probability"])
        succ = next((f.probability for f in board if f.kind == "deployment_success"
                     and f.probability is not None), 0.5)
        casc = next((f.probability for f in board if f.kind == "cascading_failure"
                     and f.probability is not None), 0.1)
        rb = next((f.probability for f in board if f.kind == "rollback_probability"
                   and f.probability is not None), 0.2)
        merit = clamp(succ * (1 - casc) * (1 - 0.5 * rb))
        return Appraisal(self.spec.key, merit, 0.6,
                         f"sim: success {succ:.0%}, cascade {casc:.0%}, rollback {rb:.0%}",
                         metadata={"success": succ, "cascade": casc, "rollback": rb})


class SecondOrderEffects(DecisionFaculty):
    def __init__(self):
        super().__init__(FacultySpec("second_order_effects", "Second-order Effects", "ripple",
                         "Weighs the consequences of the consequences.",
                         default_weight=1.1))

    def _appraise(self, o: Option, ctx: DecisionContext) -> Appraisal:
        if o.is_status_quo:
            return Appraisal(self.spec.key, 0.6, 0.4, "no induced ripple")
        board = _board(o, ctx, only=["cascading_failure", "customer_impact", "change_conflict"])
        effects = []
        penalty = 0.0
        for f in board:
            if f.probability and f.probability >= 0.3:
                effects.append(f"{f.target} ({f.probability:.0%})")
                penalty += 0.2 * f.probability
        return Appraisal(self.spec.key, clamp(1 - penalty), 0.5,
                         ("ripples: " + "; ".join(effects)) if effects else "limited ripple",
                         metadata={"effects": effects})


class ReversibilityAnalysis(DecisionFaculty):
    """Discovered: prefer two-way-door decisions under uncertainty (real options)."""
    def __init__(self):
        super().__init__(FacultySpec("reversibility", "Reversibility Analysis", "reversibility",
                         "Prefers reversible moves when uncertainty is high.",
                         default_weight=1.0))

    def _appraise(self, o: Option, ctx: DecisionContext) -> Appraisal:
        if o.reversible is True or o.is_status_quo:
            return Appraisal(self.spec.key, 0.85, 0.6, "reversible (two-way door)")
        if o.reversible is False:
            # irreversibility hurts more when we're uncertain (high risk spread)
            risk = _risk_of(o, ctx)
            merit = clamp(0.6 - 0.5 * risk)
            return Appraisal(self.spec.key, merit, 0.55,
                             f"irreversible under {risk:.0%} risk — one-way door")
        return Appraisal(self.spec.key, 0.6, 0.4, "reversibility unknown")


class PrecedentConsistency(DecisionFaculty):
    """Discovered: stay consistent with decisions that worked before."""
    def __init__(self):
        super().__init__(FacultySpec("precedent_consistency", "Precedent Consistency",
                         "precedent", "Rewards consistency with proven past decisions.",
                         default_weight=0.9))

    def _appraise(self, o: Option, ctx: DecisionContext) -> Appraisal:
        try:
            cases = _sys().decision.best_choice(f"{o.protocol}:{o.intent}", top_k=3)
            if cases:
                top = cases[0]
                merit = clamp(float(top.get("confidence") or 0.5))
                return Appraisal(self.spec.key, merit, 0.5,
                                 f"precedent: {top.get('summary','')[:50]}")
        except Exception:
            pass
        return Appraisal(self.spec.key, 0.55, 0.3, "no strong precedent")


class Robustness(DecisionFaculty):
    """Discovered: minimax-regret — how badly could this do in the worst case?"""
    def __init__(self):
        super().__init__(FacultySpec("robustness", "Robustness", "robustness",
                         "Minimises worst-case regret across plausible scenarios.",
                         default_weight=1.0))

    def _appraise(self, o: Option, ctx: DecisionContext) -> Appraisal:
        if o.is_status_quo:
            sev = float(ctx.metadata.get("problem_severity", 0.2))
            return Appraisal(self.spec.key, clamp(1 - sev), 0.4,
                             "worst case: problem persists")
        board = _board(o, ctx)
        # worst-case = highest (risk × severity) any forecaster sees for this option
        worst = max([0.0] + [clamp(f.risk * (0.5 + f.severity)) for f in board])
        return Appraisal(self.spec.key, clamp(1 - worst), 0.5,
                         f"worst-case regret {worst:.0%}")


class StakeholderImpact(DecisionFaculty):
    """Discovered: who bears the cost — penalise concentrating harm on customers."""
    def __init__(self):
        super().__init__(FacultySpec("stakeholder_impact", "Stakeholder Impact", "stakeholders",
                         "Considers the distribution of benefit and harm.",
                         default_weight=0.9))

    def _appraise(self, o: Option, ctx: DecisionContext) -> Appraisal:
        if o.is_status_quo:
            return Appraisal(self.spec.key, 0.55, 0.4, "status quo for all parties")
        board = _board(o, ctx, only=["customer_impact"])
        cust = board[0].probability if board and board[0].probability is not None else 0.1
        return Appraisal(self.spec.key, clamp(1 - cust), 0.45,
                         f"customer-facing impact {cust:.0%}")


# ── holistic faculties (reason across all options) ──────────────────────────
class AlternativeComparison(DecisionFaculty):
    def __init__(self):
        super().__init__(FacultySpec("alternative_comparison", "Alternative Comparison",
                         "comparison", "Compares options on common criteria; flags "
                         "dominated ones.", default_weight=1.0))

    def deliberate(self, ctx: DecisionContext,
                   verdicts: List[OptionVerdict]) -> Dict[str, Any]:
        dominated = []
        for a in verdicts:
            for b in verdicts:
                if a is b:
                    continue
                # b dominates a if b is >= on value AND confidence and strictly > somewhere
                if (b.value >= a.value and b.confidence >= a.confidence
                        and (b.value > a.value or b.confidence > a.confidence)
                        and not a.vetoed):
                    dominated.append(a.option.label)
                    break
        notes = [f"“{v.option.label}”: value {v.value:.0%}, conf {v.confidence:.0%}"
                 for v in sorted(verdicts, key=lambda x: x.value, reverse=True)]
        return {"comparison": notes, "dominated": sorted(set(dominated))}


class CounterfactualEvaluation(DecisionFaculty):
    def __init__(self):
        super().__init__(FacultySpec("counterfactual", "Counterfactual Evaluation",
                         "counterfactual", "Evaluates the do-nothing baseline and the "
                         "cost of being wrong.", default_weight=1.0))

    def deliberate(self, ctx: DecisionContext,
                   verdicts: List[OptionVerdict]) -> Dict[str, Any]:
        sq = next((v for v in verdicts if v.option.is_status_quo), None)
        best = max(verdicts, key=lambda x: (not x.vetoed, x.value), default=None)
        if not best:
            return {}
        if sq and not best.option.is_status_quo:
            delta = best.value - sq.value
            cf = (f"acting (“{best.option.label}”) beats holding by {delta:+.0%} value; "
                  if delta > 0 else
                  f"holding is within {abs(delta):.0%} of acting — acting may not be worth it; ")
            cf += f"if the chosen action fails, fallback is rollback to the held state."
        else:
            cf = "no change considered the strongest course; preserving current state."
        return {"counterfactual": cf}


def build_appraisers() -> List[DecisionFaculty]:
    return [RiskBalancing(), BusinessPrioritization(), TradeoffAnalysis(),
            CostOptimization(), OpportunityCost(), OperationalWisdom(),
            HumanFactors(), EthicalConstraints(), LongTermImpact(), ShortTermImpact(),
            Simulation(), SecondOrderEffects(), ReversibilityAnalysis(),
            PrecedentConsistency(), Robustness(), StakeholderImpact()]


def build_holistic() -> List[DecisionFaculty]:
    return [AlternativeComparison(), CounterfactualEvaluation()]
