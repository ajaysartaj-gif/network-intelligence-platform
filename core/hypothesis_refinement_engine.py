"""
core/hypothesis_refinement_engine.py
=====================================
Dynamic hypothesis refinement based on evidence.

Current (broken): Initial hypotheses never refined; can get stuck with bad ones
New (fixed): Generate new hypotheses when initial ones don't fit evidence
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class HypothesisRefinement:
    """A refinement decision for hypotheses."""
    action: str  # "keep", "prune", "new", "combine"
    hypothesis: str
    reason: str
    new_probability: Optional[float] = None


class HypothesisRefinementEngine:
    """Dynamically refine hypotheses based on evidence."""

    def __init__(self):
        logger.info("HypothesisRefinementEngine initialized")

    def refine_hypotheses(self,
                         current_hypotheses: Dict[str, float],
                         new_evidence: List[Any]) -> List[HypothesisRefinement]:
        """
        Refine hypotheses based on new evidence.

        Parameters
        ----------
        current_hypotheses : Dict[str, float]
            Current hypothesis probabilities
        new_evidence : List
            Evidence collected in latest cycle

        Returns
        -------
        List[HypothesisRefinement]
            Refinement decisions
        """

        refinements = []

        # STEP 1: Check if top hypotheses fit evidence
        top_hypothesis = max(current_hypotheses.items(), key=lambda x: x[1])[0]
        fits_evidence = self._check_hypothesis_fits_evidence(top_hypothesis, new_evidence)

        if not fits_evidence:
            logger.warning(f"Top hypothesis '{top_hypothesis}' doesn't fit evidence - consider new hypotheses")

            # STEP 2: Consider pruning poor hypotheses
            for hyp_name, hyp_prob in current_hypotheses.items():
                if hyp_prob < 0.10:
                    refinements.append(HypothesisRefinement(
                        action="prune",
                        hypothesis=hyp_name,
                        reason="Probability too low (< 10%)"
                    ))

        # STEP 3: Check for hypothesis combinations
        # Sometimes two weak hypotheses should be combined into one stronger one
        combined = self._find_combinable_hypotheses(current_hypotheses)
        for hyp1, hyp2, combined_name in combined:
            refinements.append(HypothesisRefinement(
                action="combine",
                hypothesis=f"{hyp1} + {hyp2}",
                reason=f"Both present simultaneously; consider combined hypothesis '{combined_name}'",
                new_probability=current_hypotheses[hyp1] * current_hypotheses[hyp2]
            ))

        # STEP 4: Look for patterns in evidence that suggest new hypotheses
        new_hyps = self._generate_hypotheses_from_evidence(new_evidence)
        for new_hyp_name, new_hyp_prob, evidence_supporting in new_hyps:
            refinements.append(HypothesisRefinement(
                action="new",
                hypothesis=new_hyp_name,
                reason=f"Suggested by evidence: {', '.join(evidence_supporting)}",
                new_probability=new_hyp_prob
            ))

        return refinements

    def should_generate_new_hypotheses(self,
                                      current_hypotheses: Dict[str, float],
                                      confidence: float,
                                      cycle_number: int) -> bool:
        """
        Determine if we should generate new hypotheses.

        Cases:
        1. Top hypothesis < 50% probable (even after evidence)
        2. After 2+ cycles with no convergence
        3. Evidence contradicts all current hypotheses
        """

        top_prob = max(current_hypotheses.values())

        # Low probability after multiple cycles = initial hypotheses likely wrong
        if cycle_number >= 2 and top_prob < 0.50:
            logger.warning("Top hypothesis still <50% after 2+ cycles - consider new hypotheses")
            return True

        # Confidence flat = hypotheses not improving
        if confidence < 0.40 and cycle_number >= 1:
            logger.warning("Confidence low - initial hypotheses may be poor")
            return True

        return False

    def _check_hypothesis_fits_evidence(self, hypothesis: str, evidence: List[Any]) -> bool:
        """Check if hypothesis explains the evidence."""

        # Simple heuristic: count supporting vs contradicting evidence
        supporting = 0
        contradicting = 0

        for ev in evidence:
            # In real implementation, check if evidence.supports_hypothesis contains hypothesis
            # For now, placeholder
            pass

        # Hypothesis fits if more support than contradiction
        return supporting >= contradicting

    def _find_combinable_hypotheses(self, hypotheses: Dict[str, float]) -> List[Tuple[str, str, str]]:
        """Find hypotheses that might be combined."""

        # Look for related hypotheses that could be one root cause
        # Example: "MTU too low" + "Path MTU discovery broken" → single issue

        combinations = []

        # Placeholder: in real implementation, check semantic similarity
        # For now, return empty list

        return combinations

    def _generate_hypotheses_from_evidence(self,
                                          evidence: List[Any]) -> List[Tuple[str, float, List[str]]]:
        """
        Generate new hypotheses based on evidence patterns.

        Returns
        -------
        List[Tuple[hypothesis_name, probability, supporting_evidence]]
        """

        new_hypotheses = []

        # Look for patterns in evidence
        for ev in evidence:
            # If evidence mentions specific keywords, suggest related hypothesis
            # Example: If evidence shows "ACL", suggest "ACL blocking OSPF"

            keywords_to_hypotheses = {
                "ACL": "Access list (ACL) blocking OSPF traffic",
                "drop": "Dropped packets due to congestion",
                "timeout": "Neighbor timeout or dead interval expiration",
                "asymmetric": "Asymmetric routing or one-way connectivity",
                "firewall": "Firewall filtering OSPF protocol 89",
            }

            # Placeholder: in real implementation, search evidence.output
            # for keywords and suggest related hypotheses

        return new_hypotheses

    def print_refinements(self, refinements: List[HypothesisRefinement]) -> str:
        """Generate human-readable refinement report."""

        if not refinements:
            return "✅ No hypothesis refinements needed\n"

        report = "🔄 HYPOTHESIS REFINEMENTS\n"
        report += "=" * 70 + "\n\n"

        for ref in refinements:
            if ref.action == "keep":
                report += f"✅ Keep: {ref.hypothesis}\n"
                report += f"   {ref.reason}\n\n"

            elif ref.action == "prune":
                report += f"🗑️  Prune: {ref.hypothesis}\n"
                report += f"   {ref.reason}\n\n"

            elif ref.action == "new":
                report += f"✨ New hypothesis: {ref.hypothesis}\n"
                report += f"   {ref.reason}\n"
                report += f"   Estimated probability: {ref.new_probability:.0%}\n\n"

            elif ref.action == "combine":
                report += f"🔀 Combine: {ref.hypothesis}\n"
                report += f"   {ref.reason}\n"
                report += f"   Combined probability: {ref.new_probability:.0%}\n\n"

        return report


class HypothesisQualityChecker:
    """Check quality of current hypothesis set."""

    @staticmethod
    def check_hypothesis_coverage(hypotheses: Dict[str, float]) -> Tuple[float, List[str]]:
        """
        Check if hypotheses cover the observed problem well.

        Returns
        -------
        Tuple[coverage_score, gaps]
            coverage_score: 0.0-1.0 (higher = better)
            gaps: List of observed phenomena not explained by hypotheses
        """

        coverage = sum(hypotheses.values())
        gaps = []

        if coverage < 0.50:
            gaps.append("Hypotheses explain <50% of observed problem")

        if coverage < 1.0:
            gap_prob = 1.0 - coverage
            gaps.append(f"{gap_prob:.0%} of problem unexplained by hypotheses")

        return coverage, gaps

    @staticmethod
    def check_hypothesis_diversity(hypotheses: Dict[str, float]) -> str:
        """
        Check if hypotheses are diverse enough.

        If all hypotheses are similar (e.g., all related to MTU),
        might be missing other root causes.
        """

        if len(hypotheses) < 3:
            return "⚠️  Few hypotheses - consider generating more"

        # Check semantic diversity
        # Placeholder: in real implementation, cluster hypotheses by keywords
        # and check if clusters exist

        return "✅ Hypotheses appear diverse"

    @staticmethod
    def rate_hypothesis_set(hypotheses: Dict[str, float],
                           evidence_count: int,
                           cycles: int) -> str:
        """Rate the quality of the hypothesis set."""

        top_prob = max(hypotheses.values())
        coverage = sum(hypotheses.values())

        if top_prob > 0.80 and coverage > 0.95:
            return "🟢 Excellent - High confidence in root cause"

        elif top_prob > 0.60 and coverage > 0.85:
            return "🟡 Good - Reasonable confidence"

        elif top_prob > 0.40 and coverage > 0.70:
            return "🟠 Fair - Consider more evidence"

        else:
            return "🔴 Poor - Hypotheses need refinement"
