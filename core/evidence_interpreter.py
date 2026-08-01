"""
core/evidence_interpreter.py
=============================
Protocol-aware evidence interpreter.

Current (broken): Generic LLM interprets evidence
New (fixed): Domain expert applies protocol logic to interpret evidence

Interprets evidence in context of protocol specifications and state machines.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


@dataclass
class EvidenceResult:
    """A single piece of evidence collected."""
    check_name: str
    command: str
    output: str  # Actual output from the check
    parsed_value: Any  # Parsed result (e.g., hello=10, state=FULL)
    raw_data: Dict[str, Any] = None


@dataclass
class InterpretationResult:
    """Interpretation of evidence."""
    evidence: EvidenceResult
    interpretation: str  # What does this evidence mean?
    supports_hypothesis: List[str]  # Which hypotheses does this support?
    eliminates_hypothesis: List[str]  # Which hypotheses does this eliminate?
    confidence_delta: float  # How much does this change confidence? (+0.1 to +0.9)
    contradictions: List[str]  # Any contradictions with other evidence?
    next_questions: List[str]  # What should we check next based on this?


class OSPFEvidenceInterpreter:
    """Interpret evidence for OSPF investigations."""

    def __init__(self):
        logger.info("OSPFEvidenceInterpreter initialized")

    def interpret_hello_interval_check(self, local_result: EvidenceResult, remote_result: Optional[EvidenceResult]) -> InterpretationResult:
        """Interpret hello interval check result."""

        # Parse hello intervals
        local_hello = self._extract_hello_interval(local_result.output)
        remote_hello = remote_result and self._extract_hello_interval(remote_result.output)

        interpretation = InterpretationResult(
            evidence=local_result,
            interpretation="",
            supports_hypothesis=[],
            eliminates_hypothesis=[],
            confidence_delta=0.0,
            contradictions=[],
            next_questions=[]
        )

        if local_hello is None:
            interpretation.interpretation = "Could not parse hello interval from output"
            return interpretation

        if remote_hello is None:
            interpretation.interpretation = "Remote hello interval not available yet"
            interpretation.next_questions = ["Check remote device hello interval"]
            return interpretation

        # Both available - compare
        if local_hello == remote_hello:
            interpretation.interpretation = f"✅ Hello intervals MATCH: both {local_hello}s"
            interpretation.eliminates_hypothesis = ["Hello/Dead interval mismatch"]
            interpretation.confidence_delta = 0.40  # High confidence: 40% of issues eliminated
        else:
            interpretation.interpretation = f"❌ Hello interval MISMATCH: local={local_hello}s, remote={remote_hello}s"
            interpretation.supports_hypothesis = ["Hello/Dead interval mismatch"]
            interpretation.confidence_delta = 0.50  # Very high confidence: found the issue
            interpretation.next_questions = ["Fix hello interval on one device to match other"]

        return interpretation

    def interpret_area_check(self, neighbor_output: str) -> InterpretationResult:
        """Interpret OSPF neighbor area check."""

        local_area = self._extract_area_from_config(neighbor_output)

        interpretation = InterpretationResult(
            evidence=EvidenceResult(
                check_name="OSPF Area Configuration",
                command="show ip ospf interface",
                output=neighbor_output,
                parsed_value={"area": local_area}
            ),
            interpretation="",
            supports_hypothesis=[],
            eliminates_hypothesis=[],
            confidence_delta=0.0,
            contradictions=[],
            next_questions=[]
        )

        if local_area is None:
            interpretation.interpretation = "Could not determine OSPF area"
            interpretation.next_questions = ["Manually verify OSPF area configuration"]
            return interpretation

        interpretation.interpretation = f"Local device in area {local_area}"
        interpretation.next_questions = ["Verify remote device is in same area"]

        return interpretation

    def interpret_mtu_check(self, local_mtu: int, remote_mtu: Optional[int]) -> InterpretationResult:
        """Interpret MTU check result."""

        interpretation = InterpretationResult(
            evidence=EvidenceResult(
                check_name="Interface MTU",
                command="show interface",
                output=f"local_mtu={local_mtu}",
                parsed_value={"local_mtu": local_mtu, "remote_mtu": remote_mtu}
            ),
            interpretation="",
            supports_hypothesis=[],
            eliminates_hypothesis=[],
            confidence_delta=0.0,
            contradictions=[],
            next_questions=[]
        )

        # Handle None values
        if local_mtu is None:
            local_mtu = 1500

        # OSPF requires at least 1500 byte MTU for default packet size
        # Minimum is actually 576, but most implementations expect 1500
        if local_mtu < 1500:
            interpretation.interpretation = f"❌ Local MTU too small: {local_mtu}. OSPF needs ≥1500"
            interpretation.supports_hypothesis = ["MTU mismatch"]
            interpretation.confidence_delta = 0.20
        else:
            interpretation.interpretation = f"✅ Local MTU sufficient: {local_mtu} ≥ 1500"
            interpretation.eliminates_hypothesis = ["Local MTU too small"]
            interpretation.confidence_delta = 0.10

        if remote_mtu:
            if local_mtu != remote_mtu:
                interpretation.interpretation += f" | Remote: {remote_mtu}"
                interpretation.supports_hypothesis = ["MTU mismatch between ends"]
                interpretation.confidence_delta = 0.25
            else:
                interpretation.interpretation += f" | Remote: {remote_mtu} ✅ MATCH"
                interpretation.eliminates_hypothesis.append("MTU mismatch")
                interpretation.confidence_delta = 0.30

        return interpretation

    def interpret_authentication_check(self, config_output: str) -> InterpretationResult:
        """Interpret OSPF authentication configuration check."""

        auth_type = self._extract_auth_type(config_output)

        interpretation = InterpretationResult(
            evidence=EvidenceResult(
                check_name="OSPF Authentication",
                command="show ip ospf interface",
                output=config_output,
                parsed_value={"auth_type": auth_type}
            ),
            interpretation="",
            supports_hypothesis=[],
            eliminates_hypothesis=[],
            confidence_delta=0.0,
            contradictions=[],
            next_questions=[]
        )

        if auth_type is None or auth_type.lower() == "none":
            interpretation.interpretation = "✅ No authentication configured"
            interpretation.eliminates_hypothesis = ["Authentication mismatch"]
            interpretation.confidence_delta = 0.15
        else:
            interpretation.interpretation = f"🔐 Authentication type: {auth_type}"
            interpretation.next_questions = ["Verify remote device has matching authentication type and key"]
            interpretation.confidence_delta = 0.10

        return interpretation

    def interpret_neighbor_state(self, neighbor_output: str) -> InterpretationResult:
        """Interpret OSPF neighbor state check."""

        state = self._extract_neighbor_state(neighbor_output)

        interpretation = InterpretationResult(
            evidence=EvidenceResult(
                check_name="OSPF Neighbor State",
                command="show ip ospf neighbor",
                output=neighbor_output,
                parsed_value={"state": state}
            ),
            interpretation="",
            supports_hypothesis=[],
            eliminates_hypothesis=[],
            confidence_delta=0.0,
            contradictions=[],
            next_questions=[]
        )

        if state is None:
            interpretation.interpretation = "❌ Neighbor not found in OSPF neighbors"
            interpretation.supports_hypothesis = ["OSPF not running on interface"]
            interpretation.confidence_delta = 0.50
            return interpretation

        # OSPF state machine: DOWN → INIT → 2-WAY → EXSTART → EXCHANGE → LOADING → FULL

        if state.upper() == "FULL":
            interpretation.interpretation = f"✅ Neighbor state: FULL (fully adjacent)"
            interpretation.eliminates_hypothesis = ["Any adjacency issue"]
            interpretation.confidence_delta = 0.95  # Issue is resolved
        elif state.upper() == "EXSTART":
            interpretation.interpretation = f"⚠️  Neighbor state: EXSTART (exchanging database)"
            interpretation.supports_hypothesis = ["Configuration mismatch", "Network issue preventing database exchange"]
            interpretation.confidence_delta = 0.30
            interpretation.next_questions = [
                "Check hello/dead intervals",
                "Verify subnet and area match",
                "Check network connectivity"
            ]
        elif state.upper() == "2-WAY":
            interpretation.interpretation = f"⚠️  Neighbor state: 2-WAY (not exchanging)"
            interpretation.supports_hypothesis = ["Asymmetric routing", "Network ACLs", "One-way connectivity issue"]
            interpretation.confidence_delta = 0.20
        elif state.upper() in ["INIT", "ATTEMPT"]:
            interpretation.interpretation = f"❌ Neighbor state: {state} (not progressing)"
            interpretation.supports_hypothesis = ["Network connectivity issue"]
            interpretation.confidence_delta = 0.40
        else:
            interpretation.interpretation = f"❓ Neighbor state: {state}"

        return interpretation

    # Helper methods for parsing

    def _extract_hello_interval(self, output: str) -> Optional[int]:
        """Extract hello interval from OSPF output."""
        try:
            for line in output.split('\n'):
                if 'hello' in line.lower() and 'interval' in line.lower():
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if 'hello' in part.lower():
                            # Try to parse the next number
                            if i + 1 < len(parts):
                                try:
                                    return int(parts[i + 1])
                                except ValueError:
                                    pass
        except Exception as e:
            logger.debug(f"Error extracting hello interval: {e}")
        return None

    def _extract_area_from_config(self, output: str) -> Optional[str]:
        """Extract OSPF area from config."""
        try:
            for line in output.split('\n'):
                if 'area' in line.lower():
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if 'area' in part.lower():
                            if i + 1 < len(parts):
                                return parts[i + 1]
        except Exception as e:
            logger.debug(f"Error extracting area: {e}")
        return None

    def _extract_auth_type(self, output: str) -> Optional[str]:
        """Extract authentication type from config."""
        try:
            for line in output.split('\n'):
                if 'authentication' in line.lower():
                    parts = line.split()
                    if len(parts) > 1:
                        return parts[-1]
            return "none"
        except Exception as e:
            logger.debug(f"Error extracting auth type: {e}")
        return None

    def _extract_neighbor_state(self, output: str) -> Optional[str]:
        """Extract OSPF neighbor state."""
        try:
            states = ["FULL", "EXSTART", "EXCHANGE", "LOADING", "2-WAY", "INIT", "DOWN", "ATTEMPT"]
            output_upper = output.upper()
            for state in states:
                if state in output_upper:
                    return state
        except Exception as e:
            logger.debug(f"Error extracting neighbor state: {e}")
        return None


class BGPEvidenceInterpreter:
    """Interpret evidence for BGP investigations."""

    def __init__(self):
        logger.info("BGPEvidenceInterpreter initialized")

    def interpret_session_state(self, output: str) -> InterpretationResult:
        """Interpret BGP session state."""
        # BGP state machine: IDLE → CONNECT → ACTIVE → OPENSENT → OPENCONFIRM → ESTABLISHED

        interpretation = InterpretationResult(
            evidence=EvidenceResult(
                check_name="BGP Session State",
                command="show ip bgp neighbors",
                output=output,
                parsed_value={}
            ),
            interpretation="",
            supports_hypothesis=[],
            eliminates_hypothesis=[],
            confidence_delta=0.0,
            contradictions=[],
            next_questions=[]
        )

        if "Established" in output or "ESTABLISHED" in output.upper():
            interpretation.interpretation = "✅ BGP session ESTABLISHED"
            interpretation.eliminates_hypothesis = ["Session down"]
            interpretation.confidence_delta = 0.90
        elif "CONNECT" in output.upper():
            interpretation.interpretation = "⚠️  BGP session in CONNECT state"
            interpretation.next_questions = ["Check TCP connectivity to port 179"]
            interpretation.confidence_delta = 0.30
        elif "OPENSENT" in output.upper():
            interpretation.interpretation = "⚠️  BGP session in OPENSENT state (waiting for OPEN)"
            interpretation.next_questions = ["Check neighbor AS number and BGP configuration"]
            interpretation.confidence_delta = 0.25
        else:
            interpretation.interpretation = "❌ BGP session not established"
            interpretation.supports_hypothesis = ["Session down"]
            interpretation.confidence_delta = 0.50

        return interpretation


class EvidenceInterpreter:
    """Main evidence interpreter factory."""

    def __init__(self):
        self.ospf = OSPFEvidenceInterpreter()
        self.bgp = BGPEvidenceInterpreter()
        logger.info("EvidenceInterpreter initialized")

    def interpret_ospf_evidence(self,
                               evidence_list: List[EvidenceResult]) -> List[InterpretationResult]:
        """Interpret a list of OSPF evidence results."""

        interpretations = []

        for evidence in evidence_list:
            interpretation = None

            if "hello" in evidence.check_name.lower():
                # Find corresponding remote result if available
                remote_result = next((e for e in evidence_list if "remote" in e.check_name.lower()),
                                    None)
                interpretation = self.ospf.interpret_hello_interval_check(evidence, remote_result)

            elif "area" in evidence.check_name.lower():
                interpretation = self.ospf.interpret_area_check(evidence.output)

            elif "mtu" in evidence.check_name.lower():
                mtu = evidence.parsed_value.get("mtu")
                remote_mtu = evidence.parsed_value.get("remote_mtu")
                interpretation = self.ospf.interpret_mtu_check(mtu, remote_mtu)

            elif "authentication" in evidence.check_name.lower():
                interpretation = self.ospf.interpret_authentication_check(evidence.output)

            elif "neighbor" in evidence.check_name.lower() and "state" in evidence.check_name.lower():
                interpretation = self.ospf.interpret_neighbor_state(evidence.output)

            if interpretation:
                interpretations.append(interpretation)

        return interpretations

    def generate_summary(self, interpretations: List[InterpretationResult]) -> str:
        """Generate summary of all interpretations."""

        report = "📊 EVIDENCE INTERPRETATION\n"
        report += "=" * 70 + "\n\n"

        for interp in interpretations:
            report += f"Check: {interp.evidence.check_name}\n"
            report += f"{interp.interpretation}\n"

            if interp.eliminates_hypothesis:
                report += f"  ✅ Eliminates: {', '.join(interp.eliminates_hypothesis)}\n"

            if interp.supports_hypothesis:
                report += f"  📌 Supports: {', '.join(interp.supports_hypothesis)}\n"

            if interp.contradictions:
                report += f"  ⚠️  Contradictions: {', '.join(interp.contradictions)}\n"

            report += f"  Confidence delta: +{interp.confidence_delta:.0%}\n\n"

        return report
