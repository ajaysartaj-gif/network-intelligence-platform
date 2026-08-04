"""
BGP Adapter

Shows how easy it is to add a second routing protocol.
Uses the same platform, different implementation.
"""

from typing import Dict, Any, List, Tuple
from platform.core.domain import Entity, Relationship, Observation, Investigation, Hypothesis, DomainType
from platform.adapters.adapter import AdapterInterface, ComparisonAdapter, ReasoningAdapter, PredictionAdapter


class BGPAdapter(AdapterInterface, ComparisonAdapter, ReasoningAdapter, PredictionAdapter):
    """
    BGP-specific implementation of the platform adapters.

    Same interface as OSPF. Different implementation.
    """

    @property
    def domain(self) -> DomainType:
        return DomainType.ROUTING

    @property
    def name(self) -> str:
        return "BGP"

    # ============ Parsing ============

    def parse(self, raw_data: Dict[str, str]) -> Tuple[List[Entity], List[Relationship]]:
        """Parse BGP show commands into entities and relationships."""
        entities = []
        relationships = []

        # Parse BGP-specific commands
        # show ip bgp summary
        # show ip bgp neighbors
        # show running-config | section bgp

        return entities, relationships

    # ============ Comparison ============

    def compare(self, entity_a: Entity, entity_b: Entity, context: str) -> Dict[str, Any]:
        """Compare two BGP peers."""
        return {
            "remote_as": {
                "explanation": "eBGP peers need different ASes, iBGP peers need same AS"
            },
            "hold_time": {
                "explanation": "Hold time must match or peers will timeout"
            }
        }

    def get_relevant_fields(self, context: str) -> List[str]:
        """Get fields relevant to BGP investigation context."""
        if context == "peering":
            return ["remote_as", "hold_time", "keepalive_interval", "local_as"]
        elif context == "route_filtering":
            return ["prefix_lists", "route_maps", "as_path_filters"]
        else:
            return ["remote_as", "hold_time", "keepalive_interval"]

    # ============ Reasoning ============

    def diagnose(self, investigation: Investigation) -> Hypothesis:
        """Diagnose BGP problems from observations."""
        return Hypothesis(
            description="Unable to diagnose from current observations",
            supporting_evidence=[],
            contradicting_evidence=investigation.observations,
            confidence=0.0,
            next_test=None
        )

    def explain(self, observation: Observation) -> str:
        """Explain what a BGP observation means."""
        if "Idle" in observation.description:
            return "Idle state means the connection hasn't been established yet. Check reachability and configuration."
        elif "Established" in observation.description:
            return "Established state means the peering is healthy and routes are being exchanged."
        else:
            return f"BGP observation: {observation.description}"

    def hypothesize(self, observations: List[Observation]) -> List[Hypothesis]:
        """Generate BGP-specific hypotheses."""
        return []

    def eliminate(self, hypothesis: Hypothesis, new_observation: Observation) -> float:
        """Update hypothesis confidence based on new observation."""
        return hypothesis.confidence

    # ============ Prediction ============

    def predict_outcome(self, current_state: Dict[str, Any], proposed_change: str) -> Dict[str, Any]:
        """Predict BGP outcome of a proposed change."""
        if "AS" in proposed_change:
            return {
                "expected_state": "session_reset",
                "convergence_time": "30-60 seconds",
                "impact": "Routes will be withdrawn then re-learned"
            }
        return {"expected_state": "unknown"}

    def predict_timeline(self, proposed_change: str) -> List[Tuple[float, str]]:
        """Predict timeline of events after BGP change."""
        if "AS" in proposed_change:
            return [
                (0, "Configuration applied"),
                (2, "BGP session reset"),
                (3, "TCP connection closed"),
                (5, "TCP connection re-established"),
                (10, "OPEN messages exchanged"),
                (15, "Routes withdrawn"),
                (45, "Routes re-learned"),
                (60, "Convergence complete")
            ]
        return [(0, "Change applied")]

    def estimate_confidence(self, prediction: Dict[str, Any]) -> float:
        """How confident are we in BGP prediction?"""
        return 0.88

    # ============ Verification ============

    def verify(self, expected: Dict[str, Any], actual: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Verify that actual state matches expected BGP state."""
        differences = []

        for key, expected_value in expected.items():
            actual_value = actual.get(key)
            if actual_value != expected_value:
                differences.append(f"{key}: expected {expected_value}, got {actual_value}")

        return (len(differences) == 0, differences)

    # ============ Observations ============

    def generate_observations(self, entities: List[Entity], relationships: List[Relationship]) -> List[Observation]:
        """Generate observations about current BGP state."""
        return []
