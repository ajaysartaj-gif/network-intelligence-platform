"""
Core Platform Engine

Orchestrates all capabilities in a domain-agnostic way.
Works with any adapter (OSPF, BGP, Firewall, Kubernetes, AWS, etc.)
"""

from typing import Dict, Any, Optional, List
from platform.core.domain import (
    Investigation, Entity, Relationship, Observation,
    Hypothesis, Recommendation, DomainType, ProblemType
)
from platform.adapters.adapter import (
    AdapterInterface, ComparisonAdapter, ReasoningAdapter, PredictionAdapter
)
from platform.capabilities.comparison import ComparisonEngine
from platform.capabilities.reasoning import ReasoningEngine
from platform.capabilities.prediction import PredictionEngine


class PlatformEngine:
    """
    Core platform that works with any domain through adapters.

    Not OSPF-specific. Not networking-specific.
    Just infrastructure intelligence.
    """

    def __init__(self, adapter: AdapterInterface):
        self.adapter = adapter
        self.comparison_engine = None
        self.reasoning_engine = None
        self.prediction_engine = None

    def investigate(
        self,
        problem_statement: str,
        raw_data: Dict[str, str],
        problem_type: ProblemType = ProblemType.UNKNOWN
    ) -> Investigation:
        """
        Investigate an infrastructure problem.

        Works with any domain as long as you provide the right adapter.

        Args:
            problem_statement: Description of the problem
            raw_data: Domain-specific raw data (CLI, API, config, etc.)
            problem_type: What category is this?

        Returns:
            Investigation object with diagnosis
        """

        # Create investigation
        investigation = Investigation(
            id="inv_001",  # TODO: generate unique ID
            problem=problem_statement,
            problem_type=problem_type,
            observations=[],
            hypotheses=[],
            primary_hypothesis=None,
            started_at=0,  # TODO: real timestamp
            confidence=0.0
        )

        # Parse raw data into entities and relationships
        entities, relationships = self.adapter.parse(raw_data)

        # Generate observations from what we see
        observations = self.adapter.generate_observations(entities, relationships)
        for obs in observations:
            investigation.add_observation(obs)

        # Run reasoning to diagnose
        reasoning_engine = ReasoningEngine(self.adapter)
        hypothesis = reasoning_engine.diagnose(investigation)
        investigation.primary_hypothesis = hypothesis
        investigation.confidence = hypothesis.confidence

        return investigation

    def compare(
        self,
        entity_a: Entity,
        entity_b: Entity,
        context: str
    ) -> Dict[str, Any]:
        """
        Compare two entities in a specific context.

        Works with any domain.

        Args:
            entity_a: First entity
            entity_b: Second entity
            context: What are we comparing for?

        Returns:
            Comparison result
        """

        if not isinstance(self.adapter, ComparisonAdapter):
            raise ValueError(f"Adapter {self.adapter.name} doesn't support comparison")

        comparison_engine = ComparisonEngine(self.adapter)
        result = comparison_engine.compare(entity_a, entity_b, context)

        return {
            "summary": result.summary,
            "matches": result.matches,
            "differences": result.differences
        }

    def predict(
        self,
        investigation: Investigation,
        proposed_change: str
    ) -> Recommendation:
        """
        Predict the outcome of a proposed change.

        Works with any domain.

        Args:
            investigation: Current investigation
            proposed_change: What change are we considering?

        Returns:
            Recommendation with predicted outcome
        """

        if not isinstance(self.adapter, PredictionAdapter):
            raise ValueError(f"Adapter {self.adapter.name} doesn't support prediction")

        prediction_engine = PredictionEngine(self.adapter)

        # TODO: Get current state from investigation
        current_state = {}  # Will be populated from entities

        recommendation = prediction_engine.predict_change(
            current_state,
            proposed_change,
            investigation.primary_hypothesis
        )

        return recommendation

    def verify(
        self,
        expected_state: Dict[str, Any],
        actual_state: Dict[str, Any]
    ) -> tuple[bool, List[str]]:
        """
        Verify that actual state matches expected state.

        Works with any domain.

        Args:
            expected_state: What we expected
            actual_state: What we got

        Returns:
            (verified, differences)
        """

        return self.adapter.verify(expected_state, actual_state)

    def explain(self, observation: Observation) -> str:
        """
        Explain what an observation means.

        Works with any domain.

        Args:
            observation: Something we observed

        Returns:
            Human-readable explanation
        """

        if not isinstance(self.adapter, ReasoningAdapter):
            return f"Observed: {observation.description}"

        reasoning_engine = ReasoningEngine(self.adapter)
        return reasoning_engine.explain_observation(observation)
