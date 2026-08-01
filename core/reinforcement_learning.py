"""
core/reinforcement_learning.py
==============================
Reinforcement learning loop that improves system from every outcome.

Each fix teaches the system: adjust decision thresholds, update confidence,
improve categorization. The system learns exponentially.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class CategoryStats:
    """Statistics for a problem category."""
    category: tuple  # (scope, symptom)
    successes: int = 0
    total: int = 0
    avg_confidence: float = 0.5
    avg_fix_time_seconds: float = 0.0

    @property
    def success_rate(self) -> float:
        """Success rate as percentage."""
        return self.successes / self.total if self.total > 0 else 0.0

    def update(self, success: bool, confidence: float, fix_time: float):
        """Update stats with new outcome."""
        self.total += 1
        if success:
            self.successes += 1

        # Update running average
        self.avg_confidence = (
            (self.avg_confidence * (self.total - 1) + confidence) / self.total
        )
        self.avg_fix_time_seconds = (
            (self.avg_fix_time_seconds * (self.total - 1) + fix_time) / self.total
        )


class ReinforcementLearningEngine:
    """Learn from fix outcomes and improve continuously."""

    def __init__(self,
                 pattern_db: Optional[Any] = None,
                 decision_maker: Optional[Any] = None,
                 intake_classifier: Optional[Any] = None):
        """
        Parameters
        ----------
        pattern_db : PatternDatabase, optional
            Pattern database to update
        decision_maker : AutonomousDecisionMaker, optional
            Decision maker to update thresholds
        intake_classifier : SemanticIntake, optional
            Intake classifier to improve
        """
        self.pattern_db = pattern_db
        self.decision_maker = decision_maker
        self.intake_classifier = intake_classifier

        # Statistics tracking
        self.category_stats: Dict[tuple, CategoryStats] = defaultdict(
            lambda: CategoryStats(category=None)
        )

        # Learning rates
        self.confidence_threshold_learning_rate = 0.02  # 2% per incident
        self.success_rate_threshold_learning_rate = 0.01  # 1% per incident

        logger.info("ReinforcementLearningEngine initialized")

    def learn_from_outcome(self, session: Any):
        """
        Learn from a troubleshooting outcome.

        Parameters
        ----------
        session : TroubleshootingSession
            Completed troubleshooting session with outcome
        """
        outcome = session.outcome
        success = (outcome == "fixed")

        logger.info(f"Learning from outcome: {outcome}")

        # Calculate reward signal
        reward = self._calculate_reward(outcome)
        logger.info(f"Reward signal: {reward:+.2f}")

        # STEP 1: Update pattern confidence
        if session.pattern_id and self.pattern_db:
            self._update_pattern_confidence(session, reward)

        # STEP 2: Update decision maker thresholds
        if self.decision_maker:
            self._update_decision_thresholds(session, reward)

        # STEP 3: Update category statistics
        self._update_category_stats(session, success)

        # STEP 4: Log learning insights
        self._log_learning_insights(session)

        logger.info("Learning complete")

    def _calculate_reward(self, outcome: str) -> float:
        """
        Calculate reward signal for the outcome.

        Returns
        -------
        float
            Reward value: +1.0 for fixed, -0.5 for degraded, -1.0 for error
        """
        reward_map = {
            "fixed": 1.0,
            "degraded": -0.5,
            "error": -1.0,
        }
        return reward_map.get(outcome, 0.0)

    def _update_pattern_confidence(self, session: Any, reward: float):
        """Update confidence for the pattern."""
        try:
            # Get current confidence
            pattern = self.pattern_db.get_pattern(session.pattern_id)
            if not pattern:
                return

            current_confidence = pattern.get("confidence", 0.5)

            # Adjust confidence based on reward
            # Positive reward: increase confidence slightly
            # Negative reward: decrease confidence more aggressively
            if reward > 0:
                adjustment = reward * self.confidence_threshold_learning_rate * 0.5
            else:
                adjustment = reward * self.confidence_threshold_learning_rate

            new_confidence = max(0.1, min(0.95, current_confidence + adjustment))

            logger.info(
                f"Pattern confidence: {current_confidence:.2f} → {new_confidence:.2f} "
                f"(adjustment: {adjustment:+.3f})"
            )

            # Update in database
            self.pattern_db.update_confidence(
                session.pattern_id,
                session.outcome,
                operator_feedback=f"Reward: {reward:+.2f}"
            )

        except Exception as e:
            logger.warning(f"Could not update pattern confidence: {e}")

    def _update_decision_thresholds(self, session: Any, reward: float):
        """Update AutonomousDecisionMaker thresholds based on outcome."""
        try:
            current_threshold = self.decision_maker.confidence_threshold

            # If fix worked, we were too conservative (lower threshold)
            # If fix failed, we were too aggressive (raise threshold)
            if reward > 0:
                # Successful: lower threshold to allow more auto-fixes
                adjustment = -self.confidence_threshold_learning_rate
            elif reward < 0:
                # Failed: raise threshold to be more cautious
                adjustment = self.confidence_threshold_learning_rate
            else:
                adjustment = 0

            new_threshold = max(0.60, min(0.95, current_threshold + adjustment))

            logger.info(
                f"Decision threshold: {current_threshold:.2f} → {new_threshold:.2f} "
                f"(adjustment: {adjustment:+.3f})"
            )

            # Update decision maker
            self.decision_maker.confidence_threshold = new_threshold

        except Exception as e:
            logger.warning(f"Could not update decision thresholds: {e}")

    def _update_category_stats(self, session: Any, success: bool):
        """Update statistics for this problem category."""
        category = (session.problem.scope, session.problem.symptom)

        if category not in self.category_stats:
            self.category_stats[category] = CategoryStats(category=category)

        stats = self.category_stats[category]
        stats.update(
            success=success,
            confidence=session.diagnosis_confidence,
            fix_time=session.duration_seconds
        )

        logger.info(
            f"Category {category}: "
            f"{stats.success_rate:.0%} success ({stats.successes}/{stats.total}), "
            f"avg time: {stats.avg_fix_time_seconds:.1f}s, "
            f"avg confidence: {stats.avg_confidence:.0%}"
        )

    def _log_learning_insights(self, session: Any):
        """Log insights from this learning."""
        insights = []

        # Insight 1: Category performance
        category = (session.problem.scope, session.problem.symptom)
        if category in self.category_stats:
            stats = self.category_stats[category]
            if stats.total >= 5:  # Only after multiple incidents
                if stats.success_rate > 0.85:
                    insights.append(
                        f"✅ Category {category} is highly reliable ({stats.success_rate:.0%})"
                    )
                elif stats.success_rate < 0.50:
                    insights.append(
                        f"⚠️  Category {category} has low success rate ({stats.success_rate:.0%})"
                    )

        # Insight 2: Fix time improvement
        if session.pattern_id:
            try:
                pattern = self.pattern_db.get_pattern(session.pattern_id)
                if pattern and "avg_time" in pattern:
                    if session.duration_seconds < pattern["avg_time"] * 0.8:
                        insights.append(
                            f"⚡ This fix is 20% faster than average!"
                        )
            except:
                pass

        # Log insights
        for insight in insights:
            logger.info(f"💡 Insight: {insight}")

    def get_learning_report(self) -> Dict[str, Any]:
        """
        Get comprehensive learning report.

        Returns
        -------
        Dict
            Report including category stats, threshold changes, etc.
        """
        report = {
            "categories_tracked": len(self.category_stats),
            "category_stats": {},
            "top_performing_categories": [],
            "needs_improvement_categories": [],
            "current_thresholds": {},
        }

        # Add category stats
        for category, stats in self.category_stats.items():
            report["category_stats"][str(category)] = {
                "success_rate": stats.success_rate,
                "total_incidents": stats.total,
                "successes": stats.successes,
                "avg_confidence": stats.avg_confidence,
                "avg_fix_time_seconds": stats.avg_fix_time_seconds,
            }

        # Find top performing
        sorted_stats = sorted(
            self.category_stats.items(),
            key=lambda x: x[1].success_rate,
            reverse=True
        )

        report["top_performing_categories"] = [
            {
                "category": str(cat),
                "success_rate": stats.success_rate,
                "total": stats.total,
            }
            for cat, stats in sorted_stats[:5]
        ]

        report["needs_improvement_categories"] = [
            {
                "category": str(cat),
                "success_rate": stats.success_rate,
                "total": stats.total,
            }
            for cat, stats in sorted_stats[-5:]
            if stats.total >= 3
        ]

        # Current thresholds
        if self.decision_maker:
            report["current_thresholds"] = {
                "confidence": self.decision_maker.confidence_threshold,
                "success_rate": self.decision_maker.success_rate_threshold,
                "precedents": self.decision_maker.precedent_threshold,
            }

        return report

    def print_learning_report(self) -> str:
        """Generate human-readable learning report."""
        report_data = self.get_learning_report()

        report = "📊 LEARNING REPORT\n"
        report += "=" * 60 + "\n\n"

        report += f"Categories Tracked: {report_data['categories_tracked']}\n\n"

        if report_data["top_performing_categories"]:
            report += "✅ TOP PERFORMING CATEGORIES:\n"
            for cat in report_data["top_performing_categories"]:
                report += (
                    f"  • {cat['category']}: "
                    f"{cat['success_rate']:.0%} ({cat['total']} incidents)\n"
                )
            report += "\n"

        if report_data["needs_improvement_categories"]:
            report += "⚠️  NEEDS IMPROVEMENT:\n"
            for cat in report_data["needs_improvement_categories"]:
                report += (
                    f"  • {cat['category']}: "
                    f"{cat['success_rate']:.0%} ({cat['total']} incidents)\n"
                )
            report += "\n"

        if report_data["current_thresholds"]:
            report += "🎯 CURRENT DECISION THRESHOLDS:\n"
            thresholds = report_data["current_thresholds"]
            report += f"  • Confidence: {thresholds['confidence']:.2f}\n"
            report += f"  • Success Rate: {thresholds['success_rate']:.2f}\n"
            report += f"  • Precedents: {thresholds['precedents']}\n"

        report += "\n" + "=" * 60
        report += "\nSystem improves with every incident! 🚀\n"

        return report
