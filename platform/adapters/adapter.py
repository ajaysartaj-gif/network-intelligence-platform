"""
Adapter framework: how to connect any protocol/platform/system.

Each domain (OSPF, BGP, Firewall, Kubernetes, AWS, etc.) implements this interface.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple
from platform.core.domain import Entity, Relationship, Observation, Investigation, Hypothesis, Recommendation, DomainType


class AdapterInterface(ABC):
    """Interface that every adapter must implement."""

    @property
    @abstractmethod
    def domain(self) -> DomainType:
        """What domain does this adapter handle?"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name (e.g., 'OSPF', 'BGP', 'Palo Alto Firewall')"""
        pass

    @abstractmethod
    def parse(self, raw_data: Dict[str, str]) -> Tuple[List[Entity], List[Relationship]]:
        """
        Parse raw input (CLI output, API response, config file) into entities and relationships.

        Args:
            raw_data: Domain-specific raw data (e.g., show commands for networking)

        Returns:
            (entities, relationships) that this system manages
        """
        pass

    @abstractmethod
    def diagnose(self, investigation: Investigation) -> Optional[Hypothesis]:
        """
        Given an investigation with observations, generate the most likely hypothesis.

        Args:
            investigation: Current investigation state

        Returns:
            Best hypothesis, or None if can't diagnose
        """
        pass

    @abstractmethod
    def predict(self, hypothesis: Hypothesis, proposed_change: str) -> Recommendation:
        """
        Predict what happens if we make a proposed change.

        Args:
            hypothesis: Current understanding of the problem
            proposed_change: What change are we considering?

        Returns:
            Recommendation with predicted outcome
        """
        pass

    @abstractmethod
    def verify(self, expected: Dict[str, Any], actual: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Check if actual state matches expected state.

        Args:
            expected: What we expected to see
            actual: What we actually see

        Returns:
            (is_verified, differences) - True if matches, list of what differs
        """
        pass

    @abstractmethod
    def generate_observations(self, entities: List[Entity], relationships: List[Relationship]) -> List[Observation]:
        """
        Generate observations about the current state.

        Args:
            entities: Current entities
            relationships: Current relationships

        Returns:
            List of observations about what we see
        """
        pass


class ComparisonAdapter(ABC):
    """Adapter for comparing two instances of the same thing."""

    @abstractmethod
    def compare(self, entity_a: Entity, entity_b: Entity, context: str) -> Dict[str, Any]:
        """
        Compare two entities in a specific context.

        Args:
            entity_a: First thing to compare
            entity_b: Second thing to compare
            context: What are we comparing for? (e.g., "neighbor_establishment", "peering")

        Returns:
            Comparison result with differences and explanations
        """
        pass

    @abstractmethod
    def get_relevant_fields(self, context: str) -> List[str]:
        """
        Get the fields that are relevant for this context.

        Args:
            context: The problem we're investigating

        Returns:
            List of field names that matter for this context
        """
        pass


class ReasoningAdapter(ABC):
    """Adapter for domain-specific reasoning."""

    @abstractmethod
    def explain(self, observation: Observation) -> str:
        """
        Explain why we're seeing this observation.

        Args:
            observation: Something we observed

        Returns:
            Human-readable explanation of why this is happening
        """
        pass

    @abstractmethod
    def hypothesize(self, observations: List[Observation]) -> List[Hypothesis]:
        """
        Generate hypotheses based on observations.

        Args:
            observations: What we've observed so far

        Returns:
            Ranked list of hypotheses (best first)
        """
        pass

    @abstractmethod
    def eliminate(self, hypothesis: Hypothesis, new_observation: Observation) -> float:
        """
        Given a new observation, how much should we believe this hypothesis?

        Args:
            hypothesis: Current theory
            new_observation: New evidence

        Returns:
            Updated confidence (0.0 to 1.0)
        """
        pass


class PredictionAdapter(ABC):
    """Adapter for domain-specific prediction."""

    @abstractmethod
    def predict_outcome(self, current_state: Dict[str, Any], proposed_change: str) -> Dict[str, Any]:
        """
        Predict what will happen if we make this change.

        Args:
            current_state: Current configuration/state
            proposed_change: What are we changing?

        Returns:
            Predicted state after change
        """
        pass

    @abstractmethod
    def predict_timeline(self, proposed_change: str) -> List[Tuple[float, str]]:
        """
        Predict timeline of events after a change.

        Args:
            proposed_change: What are we changing?

        Returns:
            List of (time_seconds, event_description) tuples
        """
        pass

    @abstractmethod
    def estimate_confidence(self, prediction: Dict[str, Any]) -> float:
        """
        How confident are we in this prediction?

        Returns:
            Confidence 0.0 to 1.0
        """
        pass
