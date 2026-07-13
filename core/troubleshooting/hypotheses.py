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

import re
from typing import List, Optional

from core.knowledge.compiler.protocol_registry import all_keywords

from .models import (
    ConfidenceDelta, Effect, Evidence, Hypothesis, HypothesisState, Observation,
)

# Generic tokens carry no diagnostic subject, so they must not create spurious
# matches between an observation and a hypothesis's discriminating signal, nor
# spurious similarity between two hypotheses. Includes domain-boilerplate
# connector words ("mismatch", "between", "neighbors", protocol names) that
# appear in nearly every hypothesis sentence within a session and so add no
# discriminating power — without these, two genuinely DIFFERENT root causes
# ("OSPF hello timer mismatch between neighbors" vs "OSPF dead timer mismatch
# between neighbors") were measured at Jaccard 0.71 (>= the 0.6 threshold),
# silently merging two distinct hypotheses into one and losing the discarded
# one entirely.
#
# Protocol names come from protocol_registry.all_keywords() (the same
# single source of truth engine.py._detect_protocol and intent_engine.py.
# _detect_scenario use) plus "eigrp"/"isis"/"rip", which aren't modeled
# protocols but are still real protocol-name tokens worth suppressing
# here for the same reason. This used to be a third, independently-
# maintained list — one more place a new protocol had to be remembered.
_STOP = {"state", "value", "status", "up", "down", "id", "name", "count",
         "the", "is", "on", "of", "a", "an", "to", "for", "not", "no", "issue",
         "problem", "or", "and", "configuration", "configured", "misconfigured",
         "mismatch", "mismatched", "between", "neighbor", "neighbors",
         "eigrp", "isis", "rip", *all_keywords()}


def content_tokens(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", (s or "").lower())) - _STOP


def _similar(a: str, b: str, threshold: float = 0.6) -> bool:
    """Conservative near-duplicate test on subject tokens (Jaccard), plus a
    full-containment fallback: a terse LLM-authored hypothesis ("MTU
    mismatch between OSPF neighbors") and its own compiled-signature
    counterpart ("MTU mismatch between OSPF neighbors prevents DBD packet
    exchange") describe the same root cause, but the extra detail in the
    compiled phrasing dilutes their Jaccard score below threshold — without
    this, HypothesisManager.add() seeds them as two separate hypotheses
    that split the same evidence between them (the compiled one inflated
    only by the deterministic-state-match tautology, the LLM one holding
    the real grounded evidence), so neither individually reaches
    convergence. Containment only fires when every content token of the
    SHORTER statement is present in the longer one — same-length or
    disjoint-length statements that merely share one generic word (already
    filtered by _STOP) don't qualify."""
    ta, tb = content_tokens(a), content_tokens(b)
    if not ta or not tb:
        return False
    if len(ta & tb) / len(ta | tb) >= threshold:
        return True
    shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return shorter <= longer


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
        # de-duplicate exact AND near-identical hypotheses. Two phrasings of the
        # same cause must not coexist and split evidence between them (which is
        # what defeats the convergence margin). On a match we keep the existing
        # hypothesis and fold in any new discriminating signals.
        norm = statement.lower()
        for h in self.session.hypotheses:
            if h.statement.lower() == norm or _similar(h.statement, statement):
                for sig in (discriminating_signals or []):
                    if sig not in h.discriminating_signals:
                        h.discriminating_signals.append(sig)
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
        """Eliminate disproven hypotheses; confirm strongly-supported ones.

        Both branches require h.evidence_ids — a hypothesis seeded with a
        high prior (e.g. a compiled failure signature at 0.85) must not
        auto-confirm before any real evidence has ever touched it. Without
        this guard, such a hypothesis is marked CONFIRMED on the very first
        reap() call, permanently excluded from active_hypotheses(), and so
        can never be bound to (or revised by) the actual observed evidence —
        freezing the report on an unverified textbook prior forever.

        The CONFIRM branch additionally requires has_grounded_evidence: a
        compiled signature's own deterministic-state-match tautology alone
        (see Hypothesis.has_grounded_evidence) can already push confidence
        past CONFIRM_AT before any genuine LLM-judged evidence arrives.
        Without this, such a hypothesis gets promoted to CONFIRMED —
        dropped from active_hypotheses() — on the very first reap() call
        of a session, permanently shutting it out from ever receiving the
        real evidence a later round's analyze() call would have bound to
        it, deadlocking RootCauseRanker.converged()'s own grounded-evidence
        requirement against a hypothesis that can now never satisfy it."""
        for h in self.session.hypotheses:
            if h.state != HypothesisState.ACTIVE:
                continue
            if h.confidence < self.ELIMINATE_BELOW and h.evidence_ids:
                h.state = HypothesisState.ELIMINATED
            elif h.confidence >= self.CONFIRM_AT and h.evidence_ids and h.has_grounded_evidence:
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
        top = r[0]
        if top.confidence < self.CONVERGE_THRESHOLD:
            return False
        # A hypothesis whose only support is the deterministic-state-match
        # tautology (observed FSM state == this compiled signature's own
        # stuck_state label) has never actually been tested against the
        # specific parameter it blames — confidence alone must not be enough
        # to call it "confirmed" and remediation-eligible. See
        # Hypothesis.has_grounded_evidence.
        if not top.has_grounded_evidence:
            return False
        if len(r) == 1:
            return True
        return (top.confidence - r[1].confidence) >= self.MARGIN
