"""
core/information_gain_calculator.py
===================================
Information-gain-aware prioritization of diagnostic checks.

Current (broken): Checks run in arbitrary order
New (fixed): Prioritize checks that eliminate the most hypotheses first
"""

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


@dataclass
class CheckPriority:
    """Priority score for a diagnostic check."""
    check_name: str
    info_gain: float  # 0.0-1.0: how much does this reduce hypothesis space?
    time_estimate_sec: float  # How long does this take?
    priority_score: float  # info_gain / time (higher is better)
    rank: int  # 1 = highest priority, N = lowest


class InformationGainCalculator:
    """Calculate information gain for diagnostic checks."""

    def __init__(self):
        logger.info("InformationGainCalculator initialized")

    def prioritize_checks(self,
                         checks: List[Dict[str, float]],
                         hypotheses: Dict[str, float]) -> List[CheckPriority]:
        """
        Prioritize checks by information gain.

        Parameters
        ----------
        checks : List[Dict]
            List of checks with {name, info_gain, time_estimate_sec, eliminates_hypotheses}
        hypotheses : Dict[str, float]
            Current hypothesis probabilities {hypothesis_name: probability}

        Returns
        -------
        List[CheckPriority]
            Checks sorted by priority (highest first)
        """

        priorities = []

        for check in checks:
            check_name = check.get("name", "Unknown")
            info_gain = check.get("info_gain", 0.5)
            time_estimate = check.get("time_estimate_sec", 1.0)
            eliminates_hyps = check.get("eliminates_hypotheses", [])

            # Calculate how much probability mass this check eliminates
            eliminated_prob = sum(
                hypotheses.get(hyp, 0.0)
                for hyp in eliminates_hyps
            )

            # Effective info gain = base info gain * probability of hypotheses it eliminates
            effective_info_gain = info_gain * eliminated_prob

            # Priority score = info gain per unit time
            priority_score = effective_info_gain / (time_estimate + 0.1)

            priority = CheckPriority(
                check_name=check_name,
                info_gain=effective_info_gain,
                time_estimate_sec=time_estimate,
                priority_score=priority_score,
                rank=0
            )

            priorities.append(priority)

        # Sort by priority score (descending)
        priorities.sort(key=lambda p: p.priority_score, reverse=True)

        # Assign ranks
        for i, priority in enumerate(priorities, 1):
            priority.rank = i

        logger.info(f"Prioritized {len(priorities)} checks by info gain")

        return priorities

    def entropy_of_hypotheses(self, hypotheses: Dict[str, float]) -> float:
        """
        Calculate Shannon entropy of hypothesis distribution.

        Entropy = -Σ P(H) * log2(P(H))

        High entropy: hypotheses evenly distributed (uncertain)
        Low entropy: one hypothesis dominates (confident)
        """

        entropy = 0.0

        for prob in hypotheses.values():
            if prob > 0:
                entropy -= prob * math.log2(prob)

        return entropy

    def expected_entropy_after_check(self,
                                    check_name: str,
                                    hypotheses: Dict[str, float],
                                    eliminates: List[str],
                                    likelihood_ratio: float) -> float:
        """
        Calculate expected entropy after running a check.

        This helps predict whether a check will reduce uncertainty.

        Lower expected entropy = check is more informative
        """

        # Scenario 1: Check confirms a hypothesis (eliminates others)
        prob_confirms = sum(hypotheses.get(h, 0.0) for h in eliminates)

        # Scenario 2: Check doesn't confirm anything
        prob_not_confirms = 1.0 - prob_confirms

        # Expected entropy = weighted average of both scenarios
        entropy_if_confirms = self._entropy_after_elimination(hypotheses, eliminates)
        entropy_if_not_confirms = self.entropy_of_hypotheses(hypotheses)

        expected_entropy = (
            prob_confirms * entropy_if_confirms +
            prob_not_confirms * entropy_if_not_confirms
        )

        return expected_entropy

    def _entropy_after_elimination(self, hypotheses: Dict[str, float], eliminates: List[str]) -> float:
        """Calculate entropy after eliminating certain hypotheses."""

        remaining = {}

        for h, prob in hypotheses.items():
            if h not in eliminates:
                remaining[h] = prob

        # Renormalize
        total = sum(remaining.values())
        if total > 0:
            remaining = {h: p / total for h, p in remaining.items()}

        return self.entropy_of_hypotheses(remaining)

    def information_gain(self,
                        hypotheses_before: Dict[str, float],
                        hypotheses_after: Dict[str, float]) -> float:
        """
        Calculate information gain from current to future state.

        IG = Entropy(before) - Entropy(after)

        Higher IG = check provides more information
        """

        entropy_before = self.entropy_of_hypotheses(hypotheses_before)
        entropy_after = self.entropy_of_hypotheses(hypotheses_after)

        return entropy_before - entropy_after

    def print_prioritization(self, priorities: List[CheckPriority]) -> str:
        """Generate human-readable prioritization report."""

        report = "🎯 CHECK PRIORITIZATION (by Information Gain)\n"
        report += "=" * 70 + "\n\n"

        for priority in priorities:
            bar_length = int(priority.priority_score * 30)
            bar = "█" * bar_length + "░" * (30 - bar_length)

            report += f"{priority.rank}. {priority.check_name}\n"
            report += f"   {bar}\n"
            report += f"   Info Gain: {priority.info_gain:.1%} | Time: {priority.time_estimate_sec:.1f}s | Score: {priority.priority_score:.2f}\n\n"

        return report


class HighInfoGainCalculator:
    """Helper to identify high-info-gain checks."""

    @staticmethod
    def identify_critical_checks(checks: List[Dict], threshold: float = 0.5) -> List[str]:
        """
        Identify checks that have high information gain (above threshold).

        These should be run first.
        """

        critical = []

        for check in checks:
            info_gain = check.get("info_gain", 0.0)
            if info_gain >= threshold:
                critical.append(check.get("name", "Unknown"))

        return critical

    @staticmethod
    def estimate_convergence_time(checks: List[CheckPriority],
                                 confidence_needed: float = 0.85) -> float:
        """
        Estimate total time to converge.

        Run high-priority checks until confidence threshold.
        """

        total_time = 0.0
        accumulated_info_gain = 0.0

        for check in checks:
            total_time += check.time_estimate_sec

            # Simulate info gain accumulation (simplified)
            accumulated_info_gain += check.info_gain

            # Rough estimate: need 85% confidence
            if accumulated_info_gain >= confidence_needed:
                break

        return total_time
