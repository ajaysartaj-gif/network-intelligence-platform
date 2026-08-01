"""
core/knowledge_gap_detector.py
===============================
Explicit knowledge gap detection.

Current (missing): System doesn't ask "what don't we know?"
New (added): After each cycle, detect gaps and trigger targeted retrieval
"""

import logging
from dataclasses import dataclass
from typing import List, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class KnowledgeSource(str, Enum):
    """Where knowledge should come from."""
    PROTOCOL = "protocol"  # Protocol specification knowledge
    ENTERPRISE = "enterprise"  # Past issues in enterprise (RAG)
    VENDOR = "vendor"  # Vendor APIs (MCP)
    WEB = "web"  # Public internet
    MCP = "mcp"  # Vendor APIs


@dataclass
class KnowledgeGap:
    """A gap in knowledge that should be filled."""
    gap_description: str  # "What is OSPF state machine for this device?"
    priority: int  # 1 (critical) to 10 (low)
    source: KnowledgeSource  # Where to find this knowledge
    urgency: str  # "high", "medium", "low"
    why_needed: str  # Why does this knowledge matter?


class KnowledgeGapDetector:
    """Detect knowledge gaps after each investigation cycle."""

    def __init__(self):
        logger.info("KnowledgeGapDetector initialized")

    def detect_gaps(self,
                   current_hypothesis: str,
                   confidence: float,
                   evidence_collected: List[Any]) -> List[KnowledgeGap]:
        """
        Detect knowledge gaps after an investigation cycle.

        Parameters
        ----------
        current_hypothesis : str
            Current top hypothesis
        confidence : float
            Current confidence level (0.0-1.0)
        evidence_collected : List
            Evidence collected so far

        Returns
        -------
        List[KnowledgeGap]
            Ranked list of knowledge gaps
        """

        gaps = []

        # GAP 1: Protocol Knowledge
        if self._needs_protocol_knowledge(current_hypothesis, evidence_collected):
            gaps.append(KnowledgeGap(
                gap_description="What is the complete OSPF state machine? What causes EXSTART?",
                priority=1,
                source=KnowledgeSource.PROTOCOL,
                urgency="high",
                why_needed="Protocol knowledge guides diagnostic checks"
            ))

        # GAP 2: Enterprise Knowledge
        if confidence < 0.70 and self._needs_enterprise_knowledge(current_hypothesis):
            gaps.append(KnowledgeGap(
                gap_description=f"Have we seen {current_hypothesis} issues before in this network?",
                priority=2,
                source=KnowledgeSource.ENTERPRISE,
                urgency="high",
                why_needed="Enterprise history can confirm or refute hypothesis quickly"
            ))

        # GAP 3: Vendor-Specific Knowledge
        if self._needs_vendor_knowledge(current_hypothesis):
            gaps.append(KnowledgeGap(
                gap_description="What are vendor-specific quirks or defaults that might explain this?",
                priority=3,
                source=KnowledgeSource.VENDOR,
                urgency="medium",
                why_needed="Vendor-specific behavior might be the root cause"
            ))

        # GAP 4: Real-time State Knowledge (MCP)
        if self._needs_live_state_knowledge(current_hypothesis):
            gaps.append(KnowledgeGap(
                gap_description="What is the actual OSPF neighbor state on the remote device RIGHT NOW?",
                priority=2,
                source=KnowledgeSource.MCP,
                urgency="high",
                why_needed="Live device state immediately answers many questions"
            ))

        # GAP 5: Public Knowledge
        if confidence < 0.60 and self._is_unusual_issue(current_hypothesis):
            gaps.append(KnowledgeGap(
                gap_description=f"Are there known issues or advisories related to {current_hypothesis}?",
                priority=4,
                source=KnowledgeSource.WEB,
                urgency="medium",
                why_needed="Public knowledge base might have documented solutions"
            ))

        # Sort by priority (1 = highest priority)
        gaps.sort(key=lambda g: g.priority)

        logger.info(f"Detected {len(gaps)} knowledge gaps")

        return gaps

    def _needs_protocol_knowledge(self, hypothesis: str, evidence: List[Any]) -> bool:
        """Check if protocol knowledge would help."""

        # Always useful for protocol-related hypotheses
        protocol_keywords = ["OSPF", "BGP", "IS-IS", "EIGRP", "hello", "dead", "adjacency"]
        return any(kw in hypothesis for kw in protocol_keywords)

    def _needs_enterprise_knowledge(self, hypothesis: str) -> bool:
        """Check if enterprise knowledge would help."""

        # Useful when we have a specific hypothesis
        return len(hypothesis) > 5

    def _needs_vendor_knowledge(self, hypothesis: str) -> bool:
        """Check if vendor-specific knowledge would help."""

        # Useful for device-specific behavior
        vendor_keywords = ["Cisco", "Juniper", "Arista", "quirk", "default", "implementation"]
        return any(kw in hypothesis for kw in vendor_keywords)

    def _needs_live_state_knowledge(self, hypothesis: str) -> bool:
        """Check if querying live device state would help."""

        # Useful for state-related hypotheses
        state_keywords = ["state", "neighbor", "status", "up", "down", "established"]
        return any(kw in hypothesis.lower() for kw in state_keywords)

    def _is_unusual_issue(self, hypothesis: str) -> bool:
        """Check if this seems like an unusual/rare issue."""

        common_issues = ["mismatch", "down", "disconnected", "no route"]
        return not any(issue in hypothesis.lower() for issue in common_issues)


class GapTriager:
    """Triage which gaps are most important to fill."""

    @staticmethod
    def prioritize_gaps(gaps: List[KnowledgeGap], confidence: float) -> List[KnowledgeGap]:
        """
        Prioritize knowledge gaps based on urgency and confidence.

        If confidence is very low (< 0.40):
            Prioritize broad knowledge (protocol, enterprise)

        If confidence is moderate (0.40-0.70):
            Prioritize targeted knowledge (vendor, MCP)

        If confidence is high (> 0.70):
            Only fill high-priority gaps
        """

        sorted_gaps = sorted(gaps, key=lambda g: g.priority)

        if confidence < 0.40:
            # Broad knowledge needed
            return [g for g in sorted_gaps if g.source in [
                KnowledgeSource.PROTOCOL,
                KnowledgeSource.ENTERPRISE
            ]][:3]

        elif confidence < 0.70:
            # Targeted knowledge needed
            return [g for g in sorted_gaps if g.source in [
                KnowledgeSource.MCP,
                KnowledgeSource.VENDOR
            ]][:2]

        else:
            # Only critical gaps
            return [g for g in sorted_gaps if g.urgency == "high"][:1]

    @staticmethod
    def print_gaps(gaps: List[KnowledgeGap]) -> str:
        """Generate human-readable gap report."""

        if not gaps:
            return "✅ No knowledge gaps detected\n"

        report = "🔍 KNOWLEDGE GAPS DETECTED\n"
        report += "=" * 70 + "\n\n"

        for i, gap in enumerate(gaps, 1):
            report += f"{i}. {gap.gap_description}\n"
            report += f"   Source: {gap.source.value} | Priority: {gap.priority} | Urgency: {gap.urgency}\n"
            report += f"   Why: {gap.why_needed}\n\n"

        return report
