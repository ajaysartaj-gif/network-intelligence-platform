"""
Generic Reasoning Capability

Works with any adapter to diagnose problems and generate hypotheses.
"""

from typing import List
from dataclasses import dataclass
from platform.core.domain import Observation, Hypothesis, Investigation
from platform.adapters.adapter import ReasoningAdapter


class ReasoningEngine:
    """Generic reasoning that works with any domain."""

    def __init__(self, adapter: ReasoningAdapter):
        self.adapter = adapter

    def diagnose(self, investigation: Investigation) -> Hypothesis:
        """
        Diagnose the problem based on observations.

        Args:
            investigation: Current investigation state

        Returns:
            Best hypothesis
        """

        # Generate initial hypotheses from observations
        hypotheses = self.adapter.hypothesize(investigation.observations)

        if not hypotheses:
            return Hypothesis(
                description="Unable to generate hypotheses from available observations",
                supporting_evidence=[],
                contradicting_evidence=investigation.observations,
                confidence=0.0,
                next_test=None
            )

        # Refine hypotheses with each observation
        for observation in investigation.observations:
            for hypothesis in hypotheses:
                new_confidence = self.adapter.eliminate(hypothesis, observation)
                hypothesis.confidence = new_confidence

        # Sort by confidence
        hypotheses.sort(key=lambda h: h.confidence, reverse=True)

        return hypotheses[0]

    def explain_observation(self, observation: Observation) -> str:
        """
        Explain what an observation means.

        Args:
            observation: Something we observed

        Returns:
            Human-readable explanation
        """
        return self.adapter.explain(observation)

    def generate_hypotheses(self, observations: List[Observation]) -> List[Hypothesis]:
        """
        Generate candidate hypotheses.

        Args:
            observations: Current observations

        Returns:
            Ranked list of hypotheses
        """
        hypotheses = self.adapter.hypothesize(observations)
        hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        return hypotheses

    def evaluate_hypothesis(self, hypothesis: Hypothesis, new_observation: Observation) -> float:
        """
        Update hypothesis confidence with new evidence.

        Args:
            hypothesis: Current hypothesis
            new_observation: New observation

        Returns:
            Updated confidence
        """
        return self.adapter.eliminate(hypothesis, new_observation)
