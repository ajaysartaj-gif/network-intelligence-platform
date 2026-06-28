"""
Evidence Layer (Milestone 2)
===========================

Evidence-first gate for configuration generation. The platform must determine
whether enough VERIFIED runtime evidence exists before the LLM is allowed to
generate configuration. If evidence is incomplete, generation is halted and the
caller receives the missing evidence + recommended collection actions.

Public interface (the single contract future milestones depend on):
    EvidenceContract, EvidenceStatus, EvidenceItem
    assess_evidence(request, device, device_facts, ...)
    get_evidence_assessor()
"""

from .contract import EvidenceContract, EvidenceItem, EvidenceStatus
from .assessor import EvidenceAssessor, get_evidence_assessor, assess_evidence

__all__ = [
    "EvidenceContract",
    "EvidenceItem",
    "EvidenceStatus",
    "EvidenceAssessor",
    "get_evidence_assessor",
    "assess_evidence",
]
