"""
Main Diagnostic Pipeline

Input (CLI) → Normalize → Protocol Reasoning → Evidence Ranking → Hypothesis → Verification → Fix
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from diagnostics.parsers.ospf import OSPFParser
from diagnostics.protocols.ospf import OSPFReasoner, DiagnosticResult


@dataclass
class DiagnosticInput:
    """Engineer's diagnostic input."""
    problem_statement: str  # e.g., "OSPF stuck in EXSTART"
    show_commands: Dict[str, str]  # command -> output mapping
    protocol: str = "ospf"  # Which protocol to diagnose
    vendor: str = "cisco"  # Vendor platform


@dataclass
class DiagnosticOutput:
    """Complete diagnostic result formatted for engineer."""
    root_cause: str
    confidence: float
    evidence: List[str]
    missing_evidence: List[str]
    recommended_fix: str
    rollback_procedure: str
    verification_commands: List[str]
    similar_cases: List[str]  # Future: from Experience Repository


class DiagnosticPipeline:
    """Main diagnostic pipeline orchestrator."""

    def __init__(self):
        self.ospf_parser = OSPFParser()
        self.ospf_reasoner = OSPFReasoner()

    def diagnose(self, input_data: DiagnosticInput) -> DiagnosticOutput:
        """
        Run complete diagnostic pipeline.

        Pipeline:
          1. Input validation
          2. Normalize CLI outputs
          3. Protocol-specific reasoning
          4. Rank hypotheses
          5. Format output
        """

        if input_data.protocol.lower() == "ospf":
            return self._diagnose_ospf(input_data)
        else:
            raise ValueError(f"Protocol not supported: {input_data.protocol}")

    def _diagnose_ospf(self, input_data: DiagnosticInput) -> DiagnosticOutput:
        """Diagnose OSPF problem."""

        # Step 1: Parse show command outputs
        neighbors = []
        interfaces = {}
        config = None

        if "show ip ospf neighbor" in input_data.show_commands:
            neighbors = self.ospf_parser.parse_show_ip_ospf_neighbor(
                input_data.show_commands["show ip ospf neighbor"]
            )

        if "show ip ospf interface" in input_data.show_commands:
            interfaces = self.ospf_parser.parse_show_ip_ospf_interface(
                input_data.show_commands["show ip ospf interface"]
            )

        if "show running-config" in input_data.show_commands:
            config = self.ospf_parser.parse_running_config_ospf(
                input_data.show_commands["show running-config"]
            )
        else:
            # Fallback to empty config
            from diagnostics.parsers.ospf import OSPFConfig
            config = OSPFConfig()

        # Step 2: Run OSPF reasoner
        result: DiagnosticResult = self.ospf_reasoner.diagnose(
            neighbors=neighbors,
            interfaces=interfaces,
            config=config,
            problem_statement=input_data.problem_statement,
        )

        # Step 3: Format for output
        primary = result.primary_cause
        return DiagnosticOutput(
            root_cause=primary.cause.value if primary else "Unknown",
            confidence=result.confidence,
            evidence=[
                f"• {ev.description} ({ev.confidence:.0%} confidence)"
                for ev in (primary.evidence if primary else [])
            ],
            missing_evidence=result.missing_evidence,
            recommended_fix=primary.recommended_fix if primary else "Unable to determine",
            rollback_procedure=" → ".join(primary.rollback_commands) if primary and primary.rollback_commands else "No rollback needed",
            verification_commands=primary.verification_commands if primary else [],
            similar_cases=[],  # Future: populated from Experience Repository
        )
