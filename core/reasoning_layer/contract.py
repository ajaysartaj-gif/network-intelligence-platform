"""
Decision Contract (Milestone 3 — Reasoning & Decision Engine)
============================================================

The single, reusable interface that carries the engineering decision produced
by the Reasoning Layer BEFORE configuration generation. Future milestones depend
on THIS contract — never on raw reasoning internals.

It is produced by orchestrating the EXISTING intelligence (Reasoning Registry,
Decision Faculty, Knowledge Graph, Operational Memory); it contains no
configuration and performs no deployment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class DecisionStatus(str, Enum):
    """The only outcomes the Reasoning Layer may return (deterministic)."""
    PROCEED = "proceed"
    NEED_MORE_INFORMATION = "need_more_information"
    UNSAFE_TO_CONTINUE = "unsafe_to_continue"
    UNSUPPORTED_REQUEST = "unsupported_request"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass
class DecisionContract:
    """Standard engineering-decision result."""
    device: str
    status: DecisionStatus = DecisionStatus.PROCEED
    reason: str = ""
    evidence_used: List[str] = field(default_factory=list)
    missing_evidence: List[str] = field(default_factory=list)
    knowledge_used: List[str] = field(default_factory=list)
    confidence: float = 0.0                     # decision-layer confidence only
    recommended_action: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def proceed(self) -> bool:
        """Configuration generation (LLM) is allowed only when this is True."""
        return self.status == DecisionStatus.PROCEED

    def summary(self) -> str:
        if self.proceed:
            return (f"Proceed: evidence and reasoning support generating "
                    f"configuration for {self.device} "
                    f"(confidence {self.confidence:.2f}).")
        return f"{self.status.value.replace('_', ' ').title()} — {self.reason}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device": self.device,
            "status": self.status.value,
            "reason": self.reason,
            "evidence_used": list(self.evidence_used),
            "missing_evidence": list(self.missing_evidence),
            "knowledge_used": list(self.knowledge_used),
            "confidence": round(self.confidence, 2),
            "recommended_action": self.recommended_action,
            "warnings": list(self.warnings),
        }
