"""
Evidence Contract (Milestone 2)
===============================

The single, reusable interface that describes whether enough VERIFIED runtime
evidence exists to safely generate configuration. Future milestones depend on
THIS contract — never on raw CLI text.

Contains: Evidence Status, Evidence Completeness, Confidence, Available
Evidence, Missing Evidence, Warnings, Collection Recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class EvidenceStatus(str, Enum):
    """First-class evidence status."""
    COMPLETE = "complete"          # all required evidence verified → generation allowed
    PARTIAL = "partial"            # some required evidence missing → generation blocked
    INSUFFICIENT = "insufficient"  # no/critical evidence missing → generation blocked
    UNKNOWN = "unknown"


@dataclass
class EvidenceItem:
    """One piece of evidence and whether it is present/required."""
    key: str
    label: str
    present: bool
    required: bool
    detail: str = ""


@dataclass
class EvidenceContract:
    """Reusable result of an evidence assessment."""
    device: str
    status: EvidenceStatus = EvidenceStatus.UNKNOWN
    completeness: float = 0.0          # 0..100
    confidence: float = 0.0            # 0..1
    available: List[EvidenceItem] = field(default_factory=list)
    missing: List[EvidenceItem] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    # ── decisions ───────────────────────────────────────────────────────────
    @property
    def sufficient(self) -> bool:
        """True ONLY when every required piece of evidence is present.
        Configuration generation (LLM) is allowed only when this is True."""
        return self.status == EvidenceStatus.COMPLETE

    def missing_labels(self) -> List[str]:
        return [m.label for m in self.missing]

    def required_missing(self) -> List[EvidenceItem]:
        return [m for m in self.missing if m.required]

    def summary(self) -> str:
        if self.sufficient:
            return f"Evidence complete for {self.device} ({self.completeness:.0f}%)."
        miss = ", ".join(self.missing_labels()) or "—"
        return (f"Insufficient verified evidence for {self.device} "
                f"({self.completeness:.0f}% complete). Missing: {miss}.")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device": self.device,
            "status": self.status.value,
            "completeness": round(self.completeness, 1),
            "confidence": round(self.confidence, 2),
            "available": [i.label for i in self.available],
            "missing": [i.label for i in self.missing],
            "warnings": list(self.warnings),
            "recommendations": list(self.recommendations),
        }
