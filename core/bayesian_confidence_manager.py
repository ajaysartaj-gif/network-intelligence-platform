"""
core/bayesian_confidence_manager.py
====================================
Bayesian confidence scoring and hypothesis probability management.

Current (broken): LLM opinion on confidence (not rigorous)
New (fixed): Bayesian probability updating (mathematically sound)

Uses Bayes' theorem to rigorously update hypothesis probabilities as evidence arrives.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class Hypothesis:
    """A single hypothesis about the root cause."""
    name: str  # "Hello/Dead interval mismatch"
    prior_probability: float  # Prior P(H) - belief before evidence (0.0-1.0)
    likelihood_positive: float  # P(E|H) - likelihood of evidence IF hypothesis true
    likelihood_negative: float  # P(E|¬H) - likelihood of evidence IF hypothesis false

    posterior_probability: float = 0.0  # Will be updated
    supporting_evidence: List[str] = field(default_factory=list)
    contradicting_evidence: List[str] = field(default_factory=list)

    def update_posterior(self, new_posterior: float):
        """Update posterior probability after evidence."""
        self.posterior_probability = max(0.0, min(1.0, new_posterior))

    def __post_init__(self):
        """Initialize posterior to prior."""
        self.posterior_probability = self.prior_probability


@dataclass
class EvidenceItem:
    """A piece of evidence that affects hypothesis probabilities."""
    name: str
    likelihood_ratios: Dict[str, float]  # {hypothesis_name: likelihood_ratio}
    # likelihood_ratio = P(E|H) / P(E|¬H)


class BayesianConfidenceManager:
    """
    Rigorously manage confidence using Bayesian probability.

    For each hypothesis H and evidence E:
    P(H|E) = P(E|H) * P(H) / P(E)

    Where:
    - P(H|E) = posterior (probability of hypothesis given evidence)
    - P(E|H) = likelihood (probability of evidence if hypothesis true)
    - P(H) = prior (initial belief)
    - P(E) = marginal probability of evidence
    """

    def __init__(self):
        self.hypotheses: Dict[str, Hypothesis] = {}
        self.evidence_history: List[EvidenceItem] = []
        logger.info("BayesianConfidenceManager initialized")

    def register_hypothesis(self,
                           name: str,
                           prior_probability: float,
                           likelihood_positive: float = 0.7,
                           likelihood_negative: float = 0.2):
        """Register a hypothesis to track."""

        hypothesis = Hypothesis(
            name=name,
            prior_probability=prior_probability,
            likelihood_positive=likelihood_positive,
            likelihood_negative=likelihood_negative
        )

        self.hypotheses[name] = hypothesis
        logger.info(f"Registered hypothesis: {name} (prior: {prior_probability:.0%})")

    def register_hypotheses_for_ospf_exstart(self):
        """Pre-configured hypotheses for OSPF EXSTART."""

        self.register_hypothesis(
            name="Hello/Dead interval mismatch",
            prior_probability=0.40,
            likelihood_positive=0.95,  # If mismatch exists, EXSTART very likely
            likelihood_negative=0.05   # If no mismatch, EXSTART unlikely
        )

        self.register_hypothesis(
            name="Subnet or Area mismatch",
            prior_probability=0.30,
            likelihood_positive=0.85,
            likelihood_negative=0.10
        )

        self.register_hypothesis(
            name="MTU mismatch",
            prior_probability=0.15,
            likelihood_positive=0.70,
            likelihood_negative=0.15
        )

        self.register_hypothesis(
            name="OSPF disabled on interface",
            prior_probability=0.10,
            likelihood_positive=0.90,
            likelihood_negative=0.02
        )

        self.register_hypothesis(
            name="Authentication mismatch",
            prior_probability=0.05,
            likelihood_positive=0.80,
            likelihood_negative=0.05
        )

    def update_with_evidence(self, evidence_name: str, likelihood_ratio_per_hypothesis: Dict[str, float]):
        """
        Update all hypothesis probabilities based on new evidence.

        Parameters
        ----------
        evidence_name : str
            Name of the evidence (e.g., "Hello intervals match")
        likelihood_ratio_per_hypothesis : Dict[str, float]
            {hypothesis_name: likelihood_ratio}
            likelihood_ratio = P(E|H) / P(E|¬H)
            - ratio > 1.0 means evidence supports hypothesis
            - ratio < 1.0 means evidence contradicts hypothesis
            - ratio = 1.0 means evidence is neutral
        """

        logger.info(f"Updating with evidence: {evidence_name}")

        # Store evidence
        self.evidence_history.append(
            EvidenceItem(
                name=evidence_name,
                likelihood_ratios=likelihood_ratio_per_hypothesis
            )
        )

        # Update each hypothesis
        for hyp_name, hyp in self.hypotheses.items():
            if hyp_name not in likelihood_ratio_per_hypothesis:
                logger.debug(f"No likelihood ratio for {hyp_name}, skipping")
                continue

            likelihood_ratio = likelihood_ratio_per_hypothesis[hyp_name]

            # Apply Bayes' theorem
            # New posterior = old_posterior * likelihood_ratio / (1 + (1 - old_posterior) * likelihood_ratio)
            old_posterior = hyp.posterior_probability

            if likelihood_ratio > 0:
                # Update using odds form of Bayes:
                # odds = prior * likelihood_ratio / (1 - prior)
                # posterior = odds / (1 + odds)
                odds = (old_posterior / (1 - old_posterior + 1e-9)) * likelihood_ratio
                new_posterior = odds / (1 + odds)
            else:
                new_posterior = 0.0

            hyp.update_posterior(new_posterior)

            logger.info(
                f"  {hyp_name}: {old_posterior:.0%} → {new_posterior:.0%} "
                f"(ratio: {likelihood_ratio:.2f})"
            )

    def get_top_hypothesis(self) -> Optional[Tuple[str, float]]:
        """Get the most likely hypothesis and its probability."""

        if not self.hypotheses:
            return None

        best = max(self.hypotheses.items(), key=lambda x: x[1].posterior_probability)
        return best[0], best[1].posterior_probability

    def get_top_n_hypotheses(self, n: int = 3) -> List[Tuple[str, float]]:
        """Get top N most likely hypotheses."""

        sorted_hyps = sorted(
            self.hypotheses.items(),
            key=lambda x: x[1].posterior_probability,
            reverse=True
        )

        return [(name, hyp.posterior_probability) for name, hyp in sorted_hyps[:n]]

    def get_confidence_score(self) -> float:
        """
        Get overall investigation confidence (0.0-1.0).

        Confidence is high when:
        - Top hypothesis is significantly more likely than others
        - Evidence strongly supports top hypothesis
        """

        if not self.hypotheses:
            return 0.0

        sorted_hyps = sorted(
            self.hypotheses.values(),
            key=lambda h: h.posterior_probability,
            reverse=True
        )

        if len(sorted_hyps) < 2:
            return sorted_hyps[0].posterior_probability

        top_prob = sorted_hyps[0].posterior_probability
        second_prob = sorted_hyps[1].posterior_probability

        # Confidence increases when top hypothesis dominates
        # Maximum confidence when top is >> second
        # Low confidence when top and second are close
        confidence = (top_prob - second_prob) / (1 - second_prob + 1e-9)
        confidence = max(0.0, min(1.0, confidence))

        return confidence

    def should_converge(self, confidence_threshold: float = 0.85) -> bool:
        """Determine if investigation should stop (converged on root cause)."""

        confidence = self.get_confidence_score()
        return confidence >= confidence_threshold

    def should_get_external_knowledge(self, confidence_threshold: float = 0.60) -> bool:
        """Determine if investigation should seek external knowledge."""

        confidence = self.get_confidence_score()
        return confidence < confidence_threshold

    def print_confidence_report(self) -> str:
        """Generate human-readable confidence report."""

        report = "📊 BAYESIAN CONFIDENCE REPORT\n"
        report += "=" * 70 + "\n\n"

        sorted_hyps = sorted(
            self.hypotheses.items(),
            key=lambda x: x[1].posterior_probability,
            reverse=True
        )

        report += "Hypothesis Probabilities:\n"
        report += "─" * 70 + "\n"

        for i, (name, hyp) in enumerate(sorted_hyps, 1):
            bar_length = int(hyp.posterior_probability * 30)
            bar = "█" * bar_length + "░" * (30 - bar_length)
            report += f"{i}. {name}\n"
            report += f"   {bar} {hyp.posterior_probability:.0%}\n"
            report += f"   Prior: {hyp.prior_probability:.0%} | Posterior: {hyp.posterior_probability:.0%}\n\n"

        report += "─" * 70 + "\n"

        top_hyp, top_prob = self.get_top_hypothesis() or ("Unknown", 0.0)
        confidence = self.get_confidence_score()

        report += f"\n🎯 Top Hypothesis: {top_hyp} ({top_prob:.0%})\n"
        report += f"📊 Overall Confidence: {confidence:.0%}\n"

        if self.should_converge():
            report += "✅ Investigation CONVERGED - High confidence in root cause\n"
        elif self.should_get_external_knowledge():
            report += "⚠️  Confidence low - Consider external knowledge\n"
        else:
            report += "⏳ Confidence moderate - Continue investigating\n"

        if self.evidence_history:
            report += f"\n📜 Evidence collected: {len(self.evidence_history)} item(s)\n"
            for ev in self.evidence_history[-3:]:  # Last 3
                report += f"  • {ev.name}\n"

        return report

    def reset(self):
        """Reset all probabilities to priors."""

        for hyp in self.hypotheses.values():
            hyp.posterior_probability = hyp.prior_probability
            hyp.supporting_evidence = []
            hyp.contradicting_evidence = []

        self.evidence_history = []
        logger.info("Confidence manager reset")


class BayesianHelper:
    """Helper functions for Bayesian calculations."""

    @staticmethod
    def likelihood_ratio_for_match(evidence_matches: bool,
                                   prior_probability: float = 0.5) -> float:
        """
        Calculate likelihood ratio when evidence is a match check.

        If evidence matches:
            P(match|H) >> P(match|¬H)
            Likelihood ratio >> 1.0 (supports hypothesis)

        If evidence doesn't match:
            P(not_match|H) << P(not_match|¬H)
            Likelihood ratio << 1.0 (contradicts hypothesis)
        """

        if evidence_matches:
            # Evidence matches - supports hypothesis
            return 10.0  # P(E|H) = 0.9, P(E|¬H) = 0.09
        else:
            # Evidence doesn't match - contradicts hypothesis
            return 0.1  # P(E|H) = 0.1, P(E|¬H) = 0.9

    @staticmethod
    def likelihood_ratio_for_partial_evidence(strength: float) -> float:
        """
        Calculate likelihood ratio for partial/indirect evidence.

        Parameters
        ----------
        strength : float
            Evidence strength (0.0 = contradicts, 1.0 = strongly supports)
        """

        # Map strength to likelihood ratio
        # strength=1.0 → ratio=100 (very strong support)
        # strength=0.5 → ratio=1.0 (neutral)
        # strength=0.0 → ratio=0.01 (very strong contradiction)

        if strength > 0.5:
            # Supporting evidence
            return 1.0 + (strength - 0.5) * 200  # Range: 1.0 to 101.0
        else:
            # Contradicting evidence
            return 1.0 / (1.0 + (0.5 - strength) * 200)  # Range: 0.01 to 1.0

    @staticmethod
    def combine_evidence(likelihood_ratios: List[float]) -> float:
        """
        Combine multiple likelihood ratios.

        Bayesian approach: multiply likelihood ratios
        """

        combined = 1.0
        for ratio in likelihood_ratios:
            combined *= ratio
        return combined
