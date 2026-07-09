"""
core/knowledge/compiler/artifacts.py
=======================================
The Reasoning Artifact model — dataclasses only. No new storage model:
every artifact publishes into the EXISTING core.knowledge_graph.
KnowledgeGraph via artifact_to_object() + Phase 2's
graph_ops.merge_into_graph, exactly like Fact did in Phase 3.

These artifacts are DELIBERATELY distinct from several pre-existing,
already-working systems — see docs/nkc_reasoning_artifact_model.md for the
full side-by-side, summarized here so the distinction travels with the
code:

  DecisionGraph   is a STATIC precompiled flowchart (condition -> action ->
                  success/failure path), derived from a protocol's known
                  state transitions. It is NOT core.intelligence.decision's
                  Judgment/Option/Appraisal — that's a RUNTIME multi-
                  criteria deliberation over live options. Different
                  question, different artifact.

  RiskAnnotation  is a small, deterministic estimate (severity/impact from
                  compiled-knowledge signals) attached to an artifact for
                  descriptive purposes. It is NOT
                  core.governance.contract.GovernanceContract, which
                  remains the sole AUTHORITATIVE pre-deployment risk gate.

  RemediationTemplate REFERENCES an existing vendor-adapter intent name
                  (e.g. "ignore_protocol_mtu" from
                  core/vendor/adapters/cisco_ios_like.py) — it never
                  invents new command text; that stays exactly where it
                  already lives.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.vendor.models import NormalizedObject

COMPILER_VERSION = "nkc-reasoning-artifact-compiler/0.1"


@dataclass
class FailureSignature:
    protocol: str
    stuck_state: str
    likely_cause: str
    evidence_fields: List[str] = field(default_factory=list)   # attribute names on the compiled object that support this cause
    confidence: float = 0.7


@dataclass
class VerificationTemplate:
    protocol: str
    commands: List[str] = field(default_factory=list)
    success_criteria: str = ""
    failure_indicators: List[str] = field(default_factory=list)
    alternative_checks: List[str] = field(default_factory=list)


@dataclass
class RemediationTemplate:
    applicable_signature: str        # FailureSignature.likely_cause this remediates
    intent_name: str                 # references an EXISTING VendorAdapter intent, e.g. "ignore_protocol_mtu"
    prerequisites: List[str] = field(default_factory=list)
    risk_level: str = "low"          # "low" | "medium" | "high" — descriptive, not a governance decision


@dataclass
class DecisionNode:
    condition: str
    action: str
    expected_result: str
    on_success: Optional[str] = None    # next state name, or None if terminal
    on_failure: Optional[str] = None    # likely_cause to consult, or None
    escalation: Optional[str] = None    # human-readable escalation guidance


@dataclass
class DecisionGraph:
    protocol: str
    nodes: List[DecisionNode] = field(default_factory=list)


@dataclass
class RiskAnnotation:
    severity: str                       # "low" | "medium" | "high"
    probability: float                  # 0-1, derived from signature confidence
    impact: str                         # human-readable
    affected_object_count: int = 0
    mitigation_reference: str = "GovernanceEngine.govern() is the authoritative pre-deployment gate"


@dataclass
class ReasoningArtifact:
    id: str
    name: str
    description: str
    version: int
    protocol: str
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.0
    dependencies: List[str] = field(default_factory=list)
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    failure_signatures: List[FailureSignature] = field(default_factory=list)
    verification: List[VerificationTemplate] = field(default_factory=list)
    remediation: List[RemediationTemplate] = field(default_factory=list)
    decision_graph: Optional[DecisionGraph] = None
    risk: Optional[RiskAnnotation] = None
    references: List[str] = field(default_factory=list)
    compiler_version: str = COMPILER_VERSION
    timestamp: float = field(default_factory=time.time)

    def content_hash(self) -> str:
        parts = [
            self.protocol,
            str(len(self.failure_signatures)), str(len(self.verification)),
            str(len(self.remediation)),
            str(len(self.decision_graph.nodes) if self.decision_graph else 0),
            str(self.risk.severity if self.risk else ""),
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def artifact_to_object(artifact: ReasoningArtifact) -> NormalizedObject:
    """Adapter so a ReasoningArtifact can be published into the EXISTING
    KnowledgeGraph via graph_ops.merge_into_graph — reused unchanged."""
    attributes: Dict[str, Any] = {
        "name": artifact.name,
        "description": artifact.description,
        "protocol": artifact.protocol,
        "version": artifact.version,
        "evidence": artifact.evidence,
        "dependencies": artifact.dependencies,
        "inputs": artifact.inputs,
        "outputs": artifact.outputs,
        "failure_signature_count": len(artifact.failure_signatures),
        "verification_count": len(artifact.verification),
        "remediation_count": len(artifact.remediation),
        "has_decision_graph": artifact.decision_graph is not None,
        "risk_severity": artifact.risk.severity if artifact.risk else "",
        "references": artifact.references,
        "_confidence": artifact.confidence,
        "_extracted_by": "deterministic",
        "_compiler_version": artifact.compiler_version,
        "_hash": artifact.content_hash(),
    }
    return NormalizedObject(type="reasoning_artifact", id=artifact.id, device="", attributes=attributes)
