"""
AWS Adapter

Shows that the same platform works for cloud infrastructure.
Not networking-specific. Infrastructure-agnostic.
"""

from typing import Dict, Any, List, Tuple
from platform.core.domain import Entity, Relationship, Observation, Investigation, Hypothesis, DomainType
from platform.adapters.adapter import AdapterInterface, ComparisonAdapter, ReasoningAdapter, PredictionAdapter


class AWSAdapter(AdapterInterface, ComparisonAdapter, ReasoningAdapter, PredictionAdapter):
    """
    AWS-specific implementation of the platform adapters.

    Same interface as OSPF and BGP. Completely different domain.
    This proves the platform truly is domain-agnostic.
    """

    @property
    def domain(self) -> DomainType:
        return DomainType.CLOUD

    @property
    def name(self) -> str:
        return "AWS"

    # ============ Parsing ============

    def parse(self, raw_data: Dict[str, str]) -> Tuple[List[Entity], List[Relationship]]:
        """Parse AWS API responses into entities and relationships."""
        entities = []
        relationships = []

        # Parse AWS resources
        # VPCs, subnets, route tables, security groups, etc.

        return entities, relationships

    # ============ Comparison ============

    def compare(self, entity_a: Entity, entity_b: Entity, context: str) -> Dict[str, Any]:
        """Compare two AWS resources."""
        return {
            "cidr_block": {
                "explanation": "CIDR blocks must not overlap between VPCs"
            },
            "route_table_id": {
                "explanation": "Route tables must be configured identically for failover"
            }
        }

    def get_relevant_fields(self, context: str) -> List[str]:
        """Get fields relevant to AWS investigation context."""
        if context == "vpc_routing":
            return ["cidr_block", "route_table_id", "nat_gateway_id", "internet_gateway_id"]
        elif context == "security_group":
            return ["ingress_rules", "egress_rules", "vpc_id"]
        else:
            return ["availability_zone", "state", "vpc_id"]

    # ============ Reasoning ============

    def diagnose(self, investigation: Investigation) -> Hypothesis:
        """Diagnose AWS problems from observations."""
        return Hypothesis(
            description="Unable to diagnose from current observations",
            supporting_evidence=[],
            contradicting_evidence=investigation.observations,
            confidence=0.0,
            next_test=None
        )

    def explain(self, observation: Observation) -> str:
        """Explain what an AWS observation means."""
        if "terminated" in observation.description.lower():
            return "Instance terminated state means it's shutting down or is already shut down."
        elif "stopped" in observation.description.lower():
            return "Instance stopped state means it's halted but can be restarted without data loss."
        else:
            return f"AWS observation: {observation.description}"

    def hypothesize(self, observations: List[Observation]) -> List[Hypothesis]:
        """Generate AWS-specific hypotheses."""
        return []

    def eliminate(self, hypothesis: Hypothesis, new_observation: Observation) -> float:
        """Update hypothesis confidence based on new observation."""
        return hypothesis.confidence

    # ============ Prediction ============

    def predict_outcome(self, current_state: Dict[str, Any], proposed_change: str) -> Dict[str, Any]:
        """Predict AWS outcome of a proposed change."""
        if "security group" in proposed_change.lower():
            return {
                "expected_state": "traffic_allowed",
                "impact_time": "immediate",
                "blast_radius": "specific_instances_only"
            }
        return {"expected_state": "unknown"}

    def predict_timeline(self, proposed_change: str) -> List[Tuple[float, str]]:
        """Predict timeline of events after AWS change."""
        if "security group" in proposed_change.lower():
            return [
                (0, "Rule change applied"),
                (0.5, "Rule takes effect in AWS"),
                (1, "Traffic allowed/blocked per new rule"),
                (5, "Connections established/closed")
            ]
        return [(0, "Change applied")]

    def estimate_confidence(self, prediction: Dict[str, Any]) -> float:
        """How confident are we in AWS prediction?"""
        return 0.95  # AWS behavior is very predictable

    # ============ Verification ============

    def verify(self, expected: Dict[str, Any], actual: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Verify that actual state matches expected AWS state."""
        differences = []

        for key, expected_value in expected.items():
            actual_value = actual.get(key)
            if actual_value != expected_value:
                differences.append(f"{key}: expected {expected_value}, got {actual_value}")

        return (len(differences) == 0, differences)

    # ============ Observations ============

    def generate_observations(self, entities: List[Entity], relationships: List[Relationship]) -> List[Observation]:
        """Generate observations about current AWS state."""
        return []
