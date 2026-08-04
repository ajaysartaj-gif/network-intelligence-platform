"""
Generic Prediction Capability

Predicts outcomes of changes in any domain.
"""

from typing import Dict, Any, List, Tuple
from dataclasses import dataclass
from platform.core.domain import Recommendation, Hypothesis
from platform.adapters.adapter import PredictionAdapter


@dataclass
class PredictionEvent:
    """A predicted event in the timeline."""
    time_seconds: float
    action: str
    confidence: float
    expected_duration: float


class PredictionEngine:
    """Generic prediction that works with any domain."""

    def __init__(self, adapter: PredictionAdapter):
        self.adapter = adapter

    def predict_change(
        self,
        current_state: Dict[str, Any],
        proposed_change: str,
        hypothesis: Hypothesis
    ) -> Recommendation:
        """
        Predict the outcome of a proposed change.

        Args:
            current_state: Current configuration/state
            proposed_change: What are we changing?
            hypothesis: Our current understanding of the problem

        Returns:
            Recommendation with predicted outcome
        """

        # Predict what will happen
        predicted_outcome = self.adapter.predict_outcome(current_state, proposed_change)

        # Predict timeline
        timeline_events = self.adapter.predict_timeline(proposed_change)

        # Estimate confidence
        confidence = self.adapter.estimate_confidence(predicted_outcome)

        # Calculate blast radius (simplified)
        blast_radius = {
            "directly_affected": 1,  # Will be populated by adapter
            "potentially_affected": 0,
            "risk_level": "low" if confidence > 0.9 else "medium" if confidence > 0.7 else "high"
        }

        # Generate verification steps
        verification_steps = self._generate_verification_steps(predicted_outcome)

        # Estimate risks
        risks = self._estimate_risks(proposed_change, confidence)

        return Recommendation(
            description=proposed_change,
            predicted_outcome=self._format_outcome(predicted_outcome),
            predicted_timeline=self._format_timeline(timeline_events),
            confidence=confidence,
            blast_radius=blast_radius,
            rollback_plan="Revert configuration to previous version",
            verification_steps=verification_steps,
            risks=risks
        )

    def predict_timeline(self, proposed_change: str) -> List[PredictionEvent]:
        """
        Predict the timeline of events after a change.

        Args:
            proposed_change: What are we changing?

        Returns:
            Ordered list of events with timing
        """
        timeline = self.adapter.predict_timeline(proposed_change)

        events = []
        for time_sec, description in timeline:
            events.append(PredictionEvent(
                time_seconds=time_sec,
                action=description,
                confidence=0.9,  # Will vary by event
                expected_duration=2.0  # Will vary
            ))

        return events

    def _format_outcome(self, outcome: Dict[str, Any]) -> str:
        """Format predicted outcome as human-readable string."""
        if outcome.get("state") == "healthy":
            return "System should return to healthy state"
        elif outcome.get("state") == "degraded":
            return "System will be temporarily degraded"
        else:
            return str(outcome)

    def _format_timeline(self, timeline: List[Tuple[float, str]]) -> str:
        """Format timeline as human-readable string."""
        lines = []
        for time_sec, event in timeline:
            lines.append(f"  T+{time_sec:.0f}s: {event}")
        return "\n".join(lines)

    def _generate_verification_steps(self, predicted_outcome: Dict[str, Any]) -> List[str]:
        """Generate verification steps to confirm prediction."""
        return [
            "Verify system state matches expected outcome",
            "Confirm no unexpected errors in logs",
            "Check metrics are within expected ranges"
        ]

    def _estimate_risks(self, proposed_change: str, confidence: float) -> List[str]:
        """Estimate risks of the proposed change."""
        if confidence > 0.95:
            return ["Low risk: High confidence in prediction"]
        elif confidence > 0.80:
            return ["Medium risk: Some uncertainty in prediction", "May need manual verification"]
        else:
            return ["High risk: Low confidence in prediction", "Recommend staged deployment"]
