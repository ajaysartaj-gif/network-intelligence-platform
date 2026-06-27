"""
core/intelligence/decision/base.py
===================================
The substrate for JUDGMENT — what separates a senior architect from a junior
engineer.

A junior produces a recommendation: "do X." A senior produces a judgment: they
hold several options at once, weigh competing considerations that genuinely
trade off against each other, see the second-order and long-term consequences
the obvious answer ignores, know what they're giving up (opportunity cost),
respect hard lines that cost-benefit can't buy out (ethics/safety), prefer
reversible moves under uncertainty, stay consistent with past decisions, and can
explain WHY — including why not the alternatives — with calibrated confidence.

This package models those abilities as DECISION FACULTIES. Each faculty appraises
each option along one axis of judgment; the deliberation engine composes their
appraisals (multi-criteria decision analysis), applies hard-constraint vetoes,
and returns a Judgment: a ranked, explained, confidence-bearing choice — not a
bare recommendation. Judgments are exposed to the existing reasoning architecture
as a Reasoner, so deliberation composes with hypothesis, critique and calibration.
"""
from __future__ import annotations

import time
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Option:
    """A candidate course of action under consideration."""
    id: str
    label: str
    intent: str = ""
    device: str = ""
    protocol: str = ""
    site: str = ""
    reversible: Optional[bool] = None        # one-way vs two-way door (None=unknown)
    effort: Optional[float] = None           # rough cost 0..1 if known
    changes_state: bool = True
    is_status_quo: bool = False              # the "do nothing" baseline
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionContext:
    """The decision to be judged."""
    question: str
    options: List[Option]
    goal: str = ""                           # the objective being served
    operator: str = "default"
    horizon_s: float = 7 * 24 * 3600
    constraints: List[str] = field(default_factory=list)
    stakeholders: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def with_status_quo(self) -> "DecisionContext":
        """Ensure a do-nothing baseline exists for counterfactual comparison."""
        if not any(o.is_status_quo for o in self.options):
            self.options = self.options + [Option(
                id="status_quo", label="Do nothing (hold)", intent="no change",
                changes_state=False, is_status_quo=True, reversible=True, effort=0.0)]
        return self


@dataclass
class Appraisal:
    """One faculty's view of one option along its axis of judgment.

    merit is normalised so that 1.0 = strongly favours choosing this option and
    0.0 = strongly against, whatever the faculty's underlying quantity. veto is
    reserved for hard-constraint faculties (ethics/safety): a vetoed option must
    not be chosen regardless of its merits elsewhere.
    """
    faculty: str
    merit: float                              # [0,1], higher = better choice
    confidence: float = 0.6                   # [0,1]
    rationale: str = ""
    veto: bool = False
    weight: float = 1.0                       # faculty importance in aggregation
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OptionVerdict:
    option: Option
    value: float                              # aggregated, risk-adjusted merit
    confidence: float
    appraisals: List[Appraisal]
    vetoed: bool
    veto_reasons: List[str] = field(default_factory=list)

    def top_factors(self, n: int = 3) -> List[Appraisal]:
        return sorted(self.appraisals, key=lambda a: a.weight * abs(a.merit - 0.5),
                      reverse=True)[:n]


@dataclass
class Judgment:
    question: str
    chosen: Optional[Option]
    ranking: List[OptionVerdict]
    confidence: float
    rationale: str
    tradeoffs: List[str] = field(default_factory=list)
    second_order: List[str] = field(default_factory=list)
    counterfactual: str = ""
    dissent: List[str] = field(default_factory=list)
    requires_human: bool = False
    ts: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def explain(self) -> str:
        if not self.chosen:
            return f"No acceptable option for «{self.question}» — escalate. " \
                   + "; ".join(self.dissent)
        lines = [f"Judgment on «{self.question}»: choose “{self.chosen.label}” "
                 f"(confidence {self.confidence:.0%}).", self.rationale]
        if self.tradeoffs:
            lines.append("Tradeoffs: " + "; ".join(self.tradeoffs))
        if self.second_order:
            lines.append("Second-order: " + "; ".join(self.second_order))
        if self.counterfactual:
            lines.append("Counterfactual: " + self.counterfactual)
        if self.dissent:
            lines.append("Dissent: " + "; ".join(self.dissent))
        if self.requires_human:
            lines.append("→ requires human approval before execution.")
        return "\n".join(lines)


@dataclass
class FacultySpec:
    key: str
    name: str
    axis: str                                 # the judgment axis it covers
    purpose: str
    default_weight: float = 1.0
    hard_constraint: bool = False             # may veto rather than score


class DecisionFaculty(ABC):
    """Base for every judgment faculty. A faculty appraises a single option in
    context; holistic faculties may also override deliberate() for cross-option
    reasoning (e.g. comparison, counterfactual)."""

    def __init__(self, spec: FacultySpec):
        self.spec = spec
        self._runs = 0
        self._errors = 0

    def appraise(self, option: Option, ctx: DecisionContext) -> Appraisal:
        self._runs += 1
        try:
            a = self._appraise(option, ctx)
            a.weight = a.weight if a.weight != 1.0 else self.spec.default_weight
            return a
        except Exception as exc:
            self._errors += 1
            return Appraisal(self.spec.key, 0.5, 0.2, f"appraisal error: {exc}",
                             weight=self.spec.default_weight)

    def _appraise(self, option: Option, ctx: DecisionContext) -> Appraisal:
        return Appraisal(self.spec.key, 0.5, 0.3, "neutral")

    # optional holistic pass over the whole context (default: nothing)
    def deliberate(self, ctx: DecisionContext,
                   verdicts: List[OptionVerdict]) -> Dict[str, Any]:
        return {}

    def health(self) -> Dict[str, Any]:
        err = self._errors / max(1, self._runs)
        return {"key": self.spec.key, "axis": self.spec.axis,
                "runs": self._runs, "error_rate": round(err, 3),
                "status": "active" if self._runs and err < 0.5
                          else ("partial" if not self._runs else "degraded")}


class DecisionFacultyRegistry:
    def __init__(self):
        self._f: Dict[str, DecisionFaculty] = {}

    def register(self, f: DecisionFaculty) -> None:
        self._f[f.spec.key] = f

    def get(self, key: str) -> Optional[DecisionFaculty]:
        return self._f.get(key)

    def all(self) -> List[DecisionFaculty]:
        return list(self._f.values())

    def report(self) -> List[Dict[str, Any]]:
        return [{"key": f.spec.key, "name": f.spec.name, "axis": f.spec.axis,
                 "hard_constraint": f.spec.hard_constraint, "health": f.health()}
                for f in self._f.values()]
