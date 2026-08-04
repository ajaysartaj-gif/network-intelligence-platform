"""
OSPF Adapter

Shows how to implement the adapter interface for a specific domain.
This is one adapter among many (BGP, Firewall, Kubernetes, AWS, etc.)

OSPF is NOT special. It's just the first implementation.
"""

from typing import Dict, Any, List, Tuple
from platform.core.domain import (
    Entity, Relationship, Observation, Investigation, Hypothesis, DomainType
)
from platform.adapters.adapter import AdapterInterface, ComparisonAdapter, ReasoningAdapter, PredictionAdapter


class OSPFAdapter(AdapterInterface, ComparisonAdapter, ReasoningAdapter, PredictionAdapter):
    """
    OSPF-specific implementation of the platform adapters.

    This is the FIRST ADAPTER. Not the only one.
    BGP, Firewall, Kubernetes, AWS adapters will follow the same pattern.
    """

    @property
    def domain(self) -> DomainType:
        return DomainType.ROUTING

    @property
    def name(self) -> str:
        return "OSPF"

    # ============ Parsing ============

    def parse(self, raw_data: Dict[str, str]) -> Tuple[List[Entity], List[Relationship]]:
        """Parse OSPF show commands into entities and relationships."""
        # This would use the existing OSPFParser
        # For now, simplified example
        entities = []
        relationships = []

        # TODO: Integrate with existing OSPFParser
        # neighbors = OSPFParser.parse_show_ip_ospf_neighbor(raw_data.get("show ip ospf neighbor", ""))
        # interfaces = OSPFParser.parse_show_ip_ospf_interface(raw_data.get("show ip ospf interface", ""))

        return entities, relationships

    # ============ Comparison ============

    def compare(self, entity_a: Entity, entity_b: Entity, context: str) -> Dict[str, Any]:
        """Compare two OSPF interfaces."""
        # Return domain-specific comparison logic
        return {
            "area_id": {
                "explanation": "Both neighbors must be in the same area to exchange databases"
            },
            "network_type": {
                "explanation": "Network types must match (broadcast, point-to-point, etc.)"
            }
        }

    def get_relevant_fields(self, context: str) -> List[str]:
        """Get fields relevant to this investigation context."""
        if context == "neighbor_establishment":
            return ["area_id", "network_type", "hello_interval", "dead_interval", "mtu"]
        elif context == "convergence":
            return ["hello_interval", "dead_interval", "cost", "area_id"]
        else:
            return ["area_id", "network_type", "hello_interval", "dead_interval", "mtu"]

    # ============ Reasoning ============

    def diagnose(self, investigation: Investigation) -> Hypothesis:
        """Diagnose OSPF problems from observations."""
        # This would integrate with existing OSPFReasoner
        # For now, simplified example
        return Hypothesis(
            description="Unable to diagnose from current observations",
            supporting_evidence=[],
            contradicting_evidence=investigation.observations,
            confidence=0.0,
            next_test=None
        )

    def explain(self, observation: Observation) -> str:
        """Explain what an OSPF observation means."""
        if "EXSTART" in observation.description:
            return "EXSTART state means database exchange is beginning. Neighbors stuck here can't sync their Link State Databases."
        elif "INIT" in observation.description:
            return "INIT state means we've seen the neighbor but they haven't seen us yet, or we have a parameter mismatch."
        else:
            return f"OSPF observation: {observation.description}"

    def hypothesize(self, observations: List[Observation]) -> List[Hypothesis]:
        """Generate OSPF-specific hypotheses."""
        # This would integrate with existing OSPFReasoner hypothesis generation
        return []

    def eliminate(self, hypothesis: Hypothesis, new_observation: Observation) -> float:
        """Update hypothesis confidence based on new observation."""
        # OSPF-specific logic for evaluating evidence
        return hypothesis.confidence

    # ============ Prediction ============

    def predict(self, hypothesis: Hypothesis, proposed_change: str) -> Dict[str, Any]:
        """Predict OSPF outcome of a proposed change."""
        # OSPF-specific prediction logic
        if "area" in proposed_change.lower():
            return {
                "expected_state": "FULL",
                "convergence_time": "8-15 seconds",
                "risk_level": "low"
            }
        return {"expected_state": "unknown"}

    def predict_outcome(self, current_state: Dict[str, Any], proposed_change: str) -> Dict[str, Any]:
        """Predict what will happen with this change."""
        return self.predict(None, proposed_change)

    def predict_timeline(self, proposed_change: str) -> List[Tuple[float, str]]:
        """Predict timeline of events after change."""
        if "area" in proposed_change.lower():
            return [
                (0, "Configuration applied"),
                (2, "OSPF restarts"),
                (5, "Neighbors go to EXSTART"),
                (8, "Database exchange begins"),
                (12, "Neighbors reach FULL"),
                (15, "Convergence complete")
            ]
        return [(0, "Change applied")]

    def estimate_confidence(self, prediction: Dict[str, Any]) -> float:
        """How confident are we in this prediction?"""
        # OSPF behavior is predictable
        return 0.92

    # ============ Verification ============

    def verify(self, expected: Dict[str, Any], actual: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Verify that actual state matches expected OSPF state."""
        differences = []

        for key, expected_value in expected.items():
            actual_value = actual.get(key)
            if actual_value != expected_value:
                differences.append(f"{key}: expected {expected_value}, got {actual_value}")

        return (len(differences) == 0, differences)

    # ============ Observations ============

    def generate_observations(self, entities: List[Entity], relationships: List[Relationship]) -> List[Observation]:
        """Generate observations about current OSPF state."""
        observations = []

        # Generate observations from entities (e.g., neighbors)
        # and relationships (e.g., adjacencies)

        # Placeholder
        return observations
