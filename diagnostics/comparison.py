"""
Context-Aware Configuration Comparison

Protocol-agnostic comparison engine that shows only differences
relevant to the engineer's current problem context.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from enum import Enum


class ComparisonContext(Enum):
    """Contexts that determine which parameters are relevant."""
    NEIGHBOR_ESTABLISHMENT = "neighbor_establishment"
    BGP_PEERING = "bgp_peering"
    LACP_FORMATION = "lacp_formation"
    AUTHENTICATION = "authentication"
    CONVERGENCE = "convergence"


@dataclass
class RelevantParameter:
    """A parameter relevant to the current context."""
    name: str
    value_a: Any
    value_b: Any
    matches: bool
    importance: str  # "critical", "important", "informational"
    why_matters: str  # Explanation for why this matters in this context


@dataclass
class ComparisonResult:
    """Result of context-aware comparison."""
    context: ComparisonContext
    endpoint_a: str
    endpoint_b: str
    relevant_differences: List[RelevantParameter]
    hidden_parameters: List[str]  # Not shown because not relevant to context
    critical_mismatches: List[str]  # Show these first
    summary: str  # One-line summary


class ContextAwareComparison:
    """Protocol-agnostic comparison engine."""

    # Define what parameters matter for each context
    CONTEXT_PARAMETERS = {
        ComparisonContext.NEIGHBOR_ESTABLISHMENT: {
            "critical": [
                "area_id",
                "network_type",
                "authentication",
            ],
            "important": [
                "hello_interval",
                "dead_interval",
                "mtu",
            ],
            "informational": [
                "router_id",
                "process_id",
            ],
        },
        ComparisonContext.BGP_PEERING: {
            "critical": [
                "as_number",
                "authentication",
                "address_family",
            ],
            "important": [
                "hold_time",
                "keepalive_interval",
                "local_as",
            ],
            "informational": [
                "router_id",
                "bgp_id",
            ],
        },
    }

    def compare(
        self,
        endpoint_a: str,
        endpoint_b: str,
        config_a: Dict[str, Any],
        config_b: Dict[str, Any],
        context: ComparisonContext,
    ) -> ComparisonResult:
        """
        Compare two configurations for a specific context.

        Args:
            endpoint_a: First device name
            endpoint_b: Second device name
            config_a: Configuration dict for first device
            config_b: Configuration dict for second device
            context: What problem are we investigating?

        Returns:
            ComparisonResult with only relevant differences
        """

        relevant_params = []
        hidden_params = []
        critical_mismatches = []

        # Get parameters relevant to this context
        if context not in self.CONTEXT_PARAMETERS:
            return ComparisonResult(
                context=context,
                endpoint_a=endpoint_a,
                endpoint_b=endpoint_b,
                relevant_differences=[],
                hidden_parameters=[],
                critical_mismatches=["Unknown context"],
                summary=f"Context {context} not supported yet",
            )

        context_params = self.CONTEXT_PARAMETERS[context]

        # Check all relevant parameters
        all_relevant = (
            context_params.get("critical", [])
            + context_params.get("important", [])
            + context_params.get("informational", [])
        )

        for param in all_relevant:
            value_a = config_a.get(param)
            value_b = config_b.get(param)

            if value_a is None or value_b is None:
                continue

            matches = value_a == value_b

            # Determine importance level
            if param in context_params.get("critical", []):
                importance = "critical"
            elif param in context_params.get("important", []):
                importance = "important"
            else:
                importance = "informational"

            # Why does this parameter matter?
            why_matters = self._explain_parameter(param, context)

            relevant_params.append(
                RelevantParameter(
                    name=param,
                    value_a=value_a,
                    value_b=value_b,
                    matches=matches,
                    importance=importance,
                    why_matters=why_matters,
                )
            )

            if not matches and importance == "critical":
                critical_mismatches.append(param)

        # Find parameters that were in config but not relevant to this context
        all_config_params = set(config_a.keys()) | set(config_b.keys())
        for param in all_config_params:
            if param not in all_relevant:
                hidden_params.append(param)

        # Sort by importance: critical mismatches first
        relevant_params.sort(
            key=lambda p: (
                p.matches,  # False (mismatches) come first
                (
                    0
                    if p.importance == "critical"
                    else 1 if p.importance == "important" else 2
                ),
            )
        )

        summary = self._generate_summary(
            endpoint_a, endpoint_b, critical_mismatches, context
        )

        return ComparisonResult(
            context=context,
            endpoint_a=endpoint_a,
            endpoint_b=endpoint_b,
            relevant_differences=relevant_params,
            hidden_parameters=hidden_params,
            critical_mismatches=critical_mismatches,
            summary=summary,
        )

    def _explain_parameter(self, param: str, context: ComparisonContext) -> str:
        """Explain why a parameter matters in this context."""
        explanations = {
            # OSPF neighbor establishment
            "area_id": "Both neighbors must be in the same area to exchange databases",
            "network_type": "Both sides must agree on network type (broadcast, point-to-point, etc)",
            "authentication": "Authentication must match or adjacency will fail",
            "hello_interval": "Neighbors detect each other with hello messages",
            "dead_interval": "If no hello for this duration, neighbor is considered down",
            "mtu": "MTU must match or database exchange will fail",
            # BGP
            "as_number": "BGP peers must use different ASes for eBGP",
            "hold_time": "How long to wait for keepalive before considering peer dead",
            "keepalive_interval": "How often to send keepalive messages",
        }
        return explanations.get(param, "Configuration parameter")

    def _generate_summary(
        self,
        endpoint_a: str,
        endpoint_b: str,
        mismatches: List[str],
        context: ComparisonContext,
    ) -> str:
        """Generate a one-line summary of findings."""
        if not mismatches:
            return f"✅ {endpoint_a} and {endpoint_b} match on all {context.value} parameters"

        if len(mismatches) == 1:
            return f"❌ Mismatch found: {mismatches[0]} differs between {endpoint_a} and {endpoint_b}"

        return f"❌ {len(mismatches)} critical mismatches found: {', '.join(mismatches)}"
