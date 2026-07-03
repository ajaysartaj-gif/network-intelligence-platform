"""
Troubleshooting Engine — hypotheses & confidence
================================================
ConfidenceCalculator : deterministic, evidence-driven confidence updates.
HypothesisManager    : lifecycle (add / merge / eliminate / confirm).
RootCauseRanker      : ranking + threshold-gated conclusions.

Confidence is NOT guessed by the LLM. The LLM only judges whether a piece of
evidence supports/contradicts a hypothesis and how strongly (0..1); the math here
turns that into a confidence via log-odds accumulation. That guarantees the
spec's rules: confidence rises only on support, falls on contradiction, and every
move is traceable to an evidence id.
"""
from __future__ import annotations

from typing import List, Optional

from .models import (
    ConfidenceDelta, Effect, Evidence, Hypothesis, HypothesisState, Observation,
)


class ConfidenceCalculator:
    # how many log-odds units a unit-weight piece of evidence is worth
    SUPPORT_GAIN = 1.15
    CONTRADICT_GAIN = 1.6      # contradiction bites harder than support (conservative)

    def update(self, hyp: Hypothesis, evidence: Evidence, obs: Observation) -> ConfidenceDelta:
        if evidence.effect == Effect.SUPPORT:
            change = self.SUPPORT_GAIN * max(0.0, min(1.0, evidence.weight))
        elif evidence.effect == Effect.CONTRADICT:
            change = -self.CONTRADICT_GAIN * max(0.0, min(1.0, evidence.weight))
        else:
            change = 0.0
        delta = ConfidenceDelta(
            evidence_id=evidence.id, effect=evidence.effect, weight=evidence.weight,
            log_odds_change=change,
            reason=evidence.reason or f"{obs.subject}.{obs.attribute}={obs.value}",
        )
        hyp.apply(delta, evidence.id)
        return delta


class HypothesisManager:
    ELIMINATE_BELOW = 0.05      # confidence floor before a hypothesis is dropped
    CONFIRM_AT = 0.80           # confidence at/above which we treat as confirmed

    def __init__(self, session) -> None:
        self.session = session

    def add(self, statement: str, rationale: str = "",
            discriminating_signals: Optional[List[str]] = None,
            prior: float = 0.2) -> Optional[Hypothesis]:
        statement = (statement or "").strip()
        if not statement:
            return None
        # de-duplicate near-identical hypotheses
        norm = statement.lower()
        for h in self.session.hypotheses:
            if h.statement.lower() == norm:
                return h
        h = Hypothesis(
            statement=statement, rationale=rationale,
            discriminating_signals=discriminating_signals or [],
        )
        h.set_prior(prior)
        self.session.hypotheses.append(h)
        return h

    def get(self, hypothesis_id: str) -> Optional[Hypothesis]:
        return next((h for h in self.session.hypotheses if h.id == hypothesis_id), None)

    def reap(self) -> None:
        """Eliminate disproven hypotheses; confirm strongly-supported ones."""
        for h in self.session.hypotheses:
            if h.state != HypothesisState.ACTIVE:
                continue
            if h.confidence < self.ELIMINATE_BELOW and h.evidence_ids:
                h.state = HypothesisState.ELIMINATED
            elif h.confidence >= self.CONFIRM_AT:
                h.state = HypothesisState.CONFIRMED


class RootCauseRanker:
    CONVERGE_THRESHOLD = 0.80   # single cause must reach this to auto-propose a fix
    PRESENT_THRESHOLD = 0.50    # below converge but above this → present as "likely"
    MARGIN = 0.15               # top must beat 2nd by this to be unambiguous

    def rank(self, session) -> List[Hypothesis]:
        return session.ranked()

    def converged(self, session) -> bool:
        r = self.rank(session)
        if not r:
            return False
        if r[0].confidence < self.CONVERGE_THRESHOLD:
            return False
        if len(r) == 1:
            return True
        return (r[0].confidence - r[1].confidence) >= self.MARGIN
