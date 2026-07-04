"""
AI Design Engine — deterministic scoring & aggregation
=====================================================
Multi-criteria decision analysis so the RECOMMENDED option is chosen by an
auditable weighted matrix (not the LLM's whim), encoding the design principle:
never optimize only for cost or only for performance.
"""
from __future__ import annotations

from typing import Dict, List

from .models import DIMENSIONS, DesignOption, RiskItem


class TradeoffScorer:
    def __init__(self, weights: Dict[str, float] = None) -> None:
        self.weights = weights or DIMENSIONS

    def score(self, options: List[DesignOption]) -> List[Dict]:
        matrix: List[Dict] = []
        for o in options:
            total = 0.0
            for dim, w in self.weights.items():
                v = float(o.scores.get(dim, 0.0) or 0.0)
                v = max(0.0, min(1.0, v))
                o.scores[dim] = v
                total += w * v
            o.weighted_total = round(total, 4)
            row = {"option": o.name, "total": o.weighted_total}
            row.update({d: o.scores.get(d, 0.0) for d in self.weights})
            matrix.append(row)
        # mark recommended (highest weighted total)
        if options:
            best = max(options, key=lambda x: x.weighted_total)
            for o in options:
                o.recommended = (o.id == best.id)
        return matrix

    def confidence(self, options: List[DesignOption], requirement_count: int) -> float:
        """Confidence from decisiveness (gap to 2nd) + requirement completeness."""
        if not options:
            return 0.0
        ranked = sorted(options, key=lambda x: x.weighted_total, reverse=True)
        top = ranked[0].weighted_total
        margin = top - (ranked[1].weighted_total if len(ranked) > 1 else 0.0)
        completeness = min(1.0, requirement_count / 4.0)   # ~4 reqs = well-specified
        conf = 0.5 * top + 0.3 * min(1.0, margin * 3) + 0.2 * completeness
        return round(max(0.0, min(1.0, conf)), 3)


class RiskAggregator:
    """Deterministic single-point-of-failure surfacing from option risks/topology."""

    SPOF_HINTS = ("single", "one ", "no redundancy", "non-redundant", "sole", "only one")

    def spofs(self, option: DesignOption) -> List[RiskItem]:
        out: List[RiskItem] = []
        blob = " ".join(option.risks + option.disadvantages).lower()
        if any(h in blob for h in self.SPOF_HINTS):
            out.append(RiskItem(kind="spof",
                                detail=f"Potential single point of failure in '{option.name}'",
                                severity="high"))
        return out
