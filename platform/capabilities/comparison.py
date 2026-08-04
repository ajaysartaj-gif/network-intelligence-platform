"""
Generic Comparison Capability

Works with any adapter (OSPF, BGP, Firewall, AWS, Kubernetes, etc.)
"""

from typing import Dict, Any, List
from dataclasses import dataclass
from platform.core.domain import Entity, Observation
from platform.adapters.adapter import ComparisonAdapter


@dataclass
class ComparisonResult:
    """Result of comparing two entities."""
    entity_a_id: str
    entity_b_id: str
    context: str
    matches: bool
    differences: List[Dict[str, Any]]  # List of {field, value_a, value_b, why_matters}
    summary: str


class ComparisonEngine:
    """Generic comparison that works with any domain."""

    def __init__(self, adapter: ComparisonAdapter):
        self.adapter = adapter

    def compare(self, entity_a: Entity, entity_b: Entity, context: str) -> ComparisonResult:
        """
        Compare two entities for a specific investigation context.

        Args:
            entity_a: First entity
            entity_b: Second entity
            context: What are we comparing for?

        Returns:
            ComparisonResult with differences highlighted
        """

        # Get fields relevant to this context
        relevant_fields = self.adapter.get_relevant_fields(context)

        # Do the comparison
        comparison = self.adapter.compare(entity_a, entity_b, context)

        # Extract differences
        differences = []
        for field in relevant_fields:
            value_a = entity_a.config.get(field)
            value_b = entity_b.config.get(field)

            if value_a != value_b:
                differences.append({
                    "field": field,
                    "value_a": value_a,
                    "value_b": value_b,
                    "matches": False,
                    "explanation": comparison.get(field, {}).get("explanation", "")
                })
            else:
                differences.append({
                    "field": field,
                    "value_a": value_a,
                    "value_b": value_b,
                    "matches": True,
                    "explanation": ""
                })

        # Generate summary
        mismatches = [d for d in differences if not d["matches"]]
        if mismatches:
            summary = f"❌ {len(mismatches)} mismatch(es) found: {', '.join([d['field'] for d in mismatches])}"
            matches = False
        else:
            summary = f"✅ All {len(differences)} relevant fields match"
            matches = True

        return ComparisonResult(
            entity_a_id=entity_a.id,
            entity_b_id=entity_b.id,
            context=context,
            matches=matches,
            differences=differences,
            summary=summary
        )

    def generate_comparison_observation(self, result: ComparisonResult) -> Observation:
        """Turn comparison result into an observation for investigation."""
        return Observation(
            timestamp=0,  # TODO: real timestamp
            entity=None,
            relationship=None,
            description=result.summary,
            source="comparison_engine",
            confidence=0.95 if result.matches else 0.99
        )
