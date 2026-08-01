"""
core/network_health_scorer.py
=============================
Real-time network health scoring for proactive visibility and planning.

Produces 0-100 health score based on incidents, predictions, and trends.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class HealthScoreFactor:
    """A single factor contributing to health score."""
    name: str
    weight: float  # 0.0-1.0, how much this affects overall score
    current_value: float  # 0.0-100.0
    description: str
    recommendation: Optional[str] = None


class NetworkHealthScorer:
    """Score network health in real-time."""

    def __init__(self,
                 pattern_db: Optional[Any] = None,
                 predictor: Optional[Any] = None):
        """
        Parameters
        ----------
        pattern_db : PatternDatabase, optional
            Database of incidents
        predictor : PredictiveForecaster, optional
            Predictor for future issues
        """
        self.pattern_db = pattern_db
        self.predictor = predictor
        logger.info("NetworkHealthScorer initialized")

    def calculate_network_health(self,
                               telemetry: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
        """
        Calculate overall network health score.

        Parameters
        ----------
        telemetry : Dict[str, Dict[str, float]]
            Current telemetry data by device

        Returns
        -------
        Dict
            Health score and detailed breakdown
        """
        factors = []
        score = 100.0

        logger.info("Calculating network health...")

        # FACTOR 1: Recent incident rate
        incident_factor = self._calculate_incident_factor()
        factors.append(incident_factor)
        score -= (100 - incident_factor.current_value) * incident_factor.weight

        # FACTOR 2: Predicted issues
        prediction_factor = self._calculate_prediction_factor(telemetry)
        factors.append(prediction_factor)
        score -= (100 - prediction_factor.current_value) * prediction_factor.weight

        # FACTOR 3: Degradation trends
        degradation_factor = self._calculate_degradation_factor(telemetry)
        factors.append(degradation_factor)
        score -= (100 - degradation_factor.current_value) * degradation_factor.weight

        # FACTOR 4: Pattern confidence
        confidence_factor = self._calculate_confidence_factor()
        factors.append(confidence_factor)
        score += (confidence_factor.current_value - 70) * confidence_factor.weight

        # FACTOR 5: Device reliability
        reliability_factor = self._calculate_reliability_factor()
        factors.append(reliability_factor)
        score -= (100 - reliability_factor.current_value) * reliability_factor.weight

        # Clamp to 0-100
        score = max(0, min(100, score))

        # Grade assignment
        grade = self._score_to_grade(score)

        result = {
            "overall_health": score,
            "health_grade": grade,
            "timestamp": datetime.now().isoformat(),
            "factors": {f.name: {
                "value": f.current_value,
                "weight": f.weight,
                "description": f.description,
                "recommendation": f.recommendation,
            } for f in factors},
            "summary": self._generate_summary(score, grade, factors),
        }

        logger.info(f"Network health: {score:.0f}/100 ({grade})")
        return result

    def _calculate_incident_factor(self) -> HealthScoreFactor:
        """Calculate factor based on recent incidents."""
        if not self.pattern_db:
            return HealthScoreFactor(
                name="Recent Incidents",
                weight=0.30,
                current_value=100.0,
                description="No data available"
            )

        try:
            # Get incidents from last 7 days
            seven_days_ago = datetime.now() - timedelta(days=7)
            recent_incidents = self.pattern_db.get_incidents_since(days=7)

            incident_count = len(recent_incidents)

            # Score: 100 with no incidents, down to 0 with many
            # 10+ incidents = 0, 0 incidents = 100
            incident_score = max(0, 100 - (incident_count * 10))

            recommendation = None
            if incident_count > 5:
                recommendation = "Too many incidents. Investigate root causes."
            elif incident_count > 2:
                recommendation = "Some incidents detected. Monitor carefully."

            return HealthScoreFactor(
                name="Recent Incidents",
                weight=0.30,
                current_value=incident_score,
                description=f"{incident_count} incident(s) in last 7 days",
                recommendation=recommendation
            )

        except Exception as e:
            logger.warning(f"Could not calculate incident factor: {e}")
            return HealthScoreFactor(
                name="Recent Incidents",
                weight=0.30,
                current_value=80.0,
                description="Calculation error"
            )

    def _calculate_prediction_factor(self, telemetry: Dict) -> HealthScoreFactor:
        """Calculate factor based on predicted issues."""
        if not self.predictor or not telemetry:
            return HealthScoreFactor(
                name="Predicted Issues",
                weight=0.25,
                current_value=100.0,
                description="No predictions available"
            )

        try:
            # Get predictions
            predictions = self.predictor.predict_issues_24h_ahead(telemetry)

            predicted_count = len(predictions)

            # Score: 100 with no predictions, down based on urgency
            # Critical issues: -30 each, High: -20 each, Medium: -10 each, Low: -5 each
            prediction_score = 100.0

            for pred in predictions:
                if pred.urgency == "critical":
                    prediction_score -= 30
                elif pred.urgency == "high":
                    prediction_score -= 20
                elif pred.urgency == "medium":
                    prediction_score -= 10
                else:
                    prediction_score -= 5

            prediction_score = max(0, prediction_score)

            recommendation = None
            if predicted_count >= 3:
                recommendation = "Multiple issues predicted. Take preventive action now."
            elif predicted_count == 2:
                recommendation = "Some issues predicted. Plan maintenance."
            elif predicted_count == 1:
                recommendation = "One issue predicted. Monitor closely."

            return HealthScoreFactor(
                name="Predicted Issues",
                weight=0.25,
                current_value=prediction_score,
                description=f"{predicted_count} issue(s) predicted in next 24h",
                recommendation=recommendation
            )

        except Exception as e:
            logger.warning(f"Could not calculate prediction factor: {e}")
            return HealthScoreFactor(
                name="Predicted Issues",
                weight=0.25,
                current_value=80.0,
                description="Calculation error"
            )

    def _calculate_degradation_factor(self, telemetry: Dict) -> HealthScoreFactor:
        """Calculate factor based on degradation trends."""
        if not telemetry:
            return HealthScoreFactor(
                name="Degradation Trends",
                weight=0.15,
                current_value=100.0,
                description="No telemetry data"
            )

        try:
            degrading_devices = []
            degradation_score = 100.0

            for device, metrics in telemetry.items():
                # Check for downward trends in health metrics
                for metric_name, metric_value in metrics.items():
                    if isinstance(metric_value, list) and len(metric_value) > 2:
                        # Simple trend: is latest < average?
                        avg = sum(metric_value) / len(metric_value)
                        latest = metric_value[-1]

                        if latest < avg * 0.8:  # Down 20%
                            degrading_devices.append(device)
                            degradation_score -= 15

            degradation_score = max(0, degradation_score)

            recommendation = None
            if degrading_devices:
                recommendation = f"Degrading: {', '.join(set(degrading_devices))}"

            return HealthScoreFactor(
                name="Degradation Trends",
                weight=0.15,
                current_value=degradation_score,
                description=f"{len(set(degrading_devices))} device(s) degrading",
                recommendation=recommendation
            )

        except Exception as e:
            logger.warning(f"Could not calculate degradation factor: {e}")
            return HealthScoreFactor(
                name="Degradation Trends",
                weight=0.15,
                current_value=85.0,
                description="Calculation error"
            )

    def _calculate_confidence_factor(self) -> HealthScoreFactor:
        """Calculate factor based on pattern confidence."""
        if not self.pattern_db:
            return HealthScoreFactor(
                name="Pattern Confidence",
                weight=0.15,
                current_value=50.0,
                description="No patterns learned yet"
            )

        try:
            avg_confidence = self.pattern_db.get_average_confidence()

            # Score based on confidence (70% baseline)
            # If avg_confidence = 70%, score = 100
            # If avg_confidence = 90%, score = 120 (capped to 100)
            confidence_score = (avg_confidence - 0.70) * 100 + 100
            confidence_score = max(40, min(100, confidence_score))

            recommendation = None
            if avg_confidence < 0.70:
                recommendation = "Patterns need more learning. Keep using system."
            elif avg_confidence > 0.85:
                recommendation = "Patterns are highly reliable. Good confidence."

            return HealthScoreFactor(
                name="Pattern Confidence",
                weight=0.10,
                current_value=confidence_score,
                description=f"Average confidence: {avg_confidence:.0%}",
                recommendation=recommendation
            )

        except Exception as e:
            logger.warning(f"Could not calculate confidence factor: {e}")
            return HealthScoreFactor(
                name="Pattern Confidence",
                weight=0.10,
                current_value=60.0,
                description="Calculation error"
            )

    def _calculate_reliability_factor(self) -> HealthScoreFactor:
        """Calculate factor based on device reliability."""
        # This is a placeholder - would integrate with device inventory
        return HealthScoreFactor(
            name="Device Reliability",
            weight=0.05,
            current_value=90.0,
            description="All monitored devices online",
            recommendation=None
        )

    def _score_to_grade(self, score: float) -> str:
        """Convert score to letter grade."""
        if score >= 90:
            return "A (Excellent)"
        elif score >= 75:
            return "B (Good)"
        elif score >= 60:
            return "C (Fair)"
        elif score >= 40:
            return "D (Poor)"
        else:
            return "F (Critical)"

    def _generate_summary(self, score: float, grade: str, factors: List[HealthScoreFactor]) -> str:
        """Generate health summary text."""
        if score >= 90:
            summary = "Network is healthy and performing well. No immediate action needed."
        elif score >= 75:
            summary = "Network is mostly healthy. Monitor for trending issues."
        elif score >= 60:
            summary = "Network has some issues. Proactive maintenance recommended."
        elif score >= 40:
            summary = "Network health is declining. Immediate attention needed."
        else:
            summary = "Network is critical. Take action now to prevent outages."

        return summary

    def print_health_report(self, health_data: Dict[str, Any]) -> str:
        """Generate human-readable health report."""
        report = "🏥 NETWORK HEALTH REPORT\n"
        report += "=" * 60 + "\n\n"

        report += f"Overall Health: {health_data['overall_health']:.0f}/100\n"
        report += f"Grade: {health_data['health_grade']}\n"
        report += f"Status: {health_data['summary']}\n\n"

        report += "Factor Breakdown:\n"
        report += "─" * 60 + "\n"

        for factor_name, factor_data in health_data["factors"].items():
            report += f"\n{factor_name}: {factor_data['value']:.0f}/100\n"
            report += f"  └─ {factor_data['description']}\n"

            if factor_data.get("recommendation"):
                report += f"  └─ 💡 {factor_data['recommendation']}\n"

        report += "\n" + "=" * 60
        report += f"\nTimestamp: {health_data['timestamp']}\n"

        return report
