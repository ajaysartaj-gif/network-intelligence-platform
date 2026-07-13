"""
core/knowledge/compiler/reasoning_artifact_compiler.py
==========================================================
ReasoningArtifactCompiler — the orchestrator for NKC Phase 4. Composes
Phase 3's protocol_models.py, this package's failure_signatures.py and
artifacts.py, and Phase 2's graph_ops.py into one entry point that
compiles reasoning ONCE (deterministically, from verified protocol state
models and existing vendor-adapter intents) so it can be reused many
times, instead of the LLM re-deriving hypotheses/verification/fixes fresh
every troubleshooting session (core/troubleshooting/reasoning.py's current
behavior, left untouched — wiring these artifacts into that engine's live
hot path is a future integration point, not built here).

Every method is a thin composition of an existing module — no new
extraction/scoring/graph logic beyond sequencing, same discipline as
compiler.py and cross_document_compiler.py.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from core.knowledge.compiler import failure_signatures, graph_ops
from core.knowledge.compiler.artifacts import (
    DecisionGraph, DecisionNode, FailureSignature, ReasoningArtifact,
    RemediationTemplate, RiskAnnotation, VerificationTemplate, artifact_to_object,
)
from core.knowledge.compiler.compiler import get_compiled_graph
from core.knowledge.compiler.protocol_models import build_protocol_model
from core.knowledge.compiler.protocol_registry import PROTOCOL_SPECS
from core.knowledge_graph import KnowledgeGraph

# All four of these used to be hand-maintained module-level dicts here —
# one more file to touch per protocol. Now derived from protocol_registry.
# py's PROTOCOL_SPECS, the single place a new protocol's verification
# template, remediation POLICY (vendor-neutral: which intent fixes which
# state, and how risky it is — never the vendor syntax itself), and
# regression states are declared (see protocol_registry.py's own
# ProtocolSpec.verification/remediation_policies/regression_states fields).
_VERIFICATION_TEMPLATES: Dict[str, VerificationTemplate] = {
    name: spec.verification for name, spec in PROTOCOL_SPECS.items() if spec.verification is not None
}

_REMEDIATION_INTENTS: Dict[str, Dict[str, str]] = {
    name: {r.trigger_state: r.intent_name for r in spec.remediation_policies if r.trigger_state}
    for name, spec in PROTOCOL_SPECS.items() if spec.remediation_policies
}

_RISK_LEVEL_BY_INTENT = {
    r.intent_name: r.risk_level for spec in PROTOCOL_SPECS.values() for r in spec.remediation_policies
}

_REGRESSION_STATES = {s for spec in PROTOCOL_SPECS.values() for s in spec.regression_states}


class ReasoningArtifactCompiler:
    def __init__(self, graph: Optional[KnowledgeGraph] = None):
        self.graph = graph if graph is not None else get_compiled_graph()
        self._last_hash: Dict[str, str] = {}
        self._version: Dict[str, int] = {}
        self._cache: Dict[str, ReasoningArtifact] = {}
        self._history: Dict[str, List[ReasoningArtifact]] = {}

    # ── individual sub-compilers ───────────────────────────────────────────

    def compile_root_causes(self, protocol: str) -> List[FailureSignature]:
        return failure_signatures.compile_failure_signatures(protocol)

    def compile_verification(self, protocol: str) -> List[VerificationTemplate]:
        tmpl = _VERIFICATION_TEMPLATES.get((protocol or "").strip().lower())
        return [tmpl] if tmpl else []

    def compile_remediation(self, protocol: str) -> List[RemediationTemplate]:
        protocol = (protocol or "").strip().lower()
        intents = _REMEDIATION_INTENTS.get(protocol, {})
        templates = []
        for cause_state, intent_name in intents.items():
            sig = next((s for s in self.compile_root_causes(protocol)
                       if s.stuck_state == cause_state), None)
            templates.append(RemediationTemplate(
                applicable_signature=sig.likely_cause if sig else cause_state,
                intent_name=intent_name,
                prerequisites=[f"Confirm the compiled evidence for '{cause_state}' "
                               f"before applying — this intent is a workaround/config "
                               f"change, not automatically safe"],
                risk_level=_RISK_LEVEL_BY_INTENT.get(intent_name, "medium")))
        return templates

    def compile_decision_graph(self, protocol: str) -> Optional[DecisionGraph]:
        protocol = (protocol or "").strip().lower()
        model = build_protocol_model(protocol)
        if model is None:
            return None
        signatures = {s.stuck_state: s for s in self.compile_root_causes(protocol)}

        nodes: List[DecisionNode] = []
        for state in model.states:
            outgoing = [t for t in model.transitions if t.from_state == state]
            forward = [t for t in outgoing if t.to_state not in _REGRESSION_STATES]
            # A state whose only outgoing edges are regressions (e.g. Full's
            # only transition is back to Down on dead-interval expiry) is a
            # terminal/success state, not a state with no valid "success
            # path" — falling back to the regression edge here would
            # mislabel reaching Down from Full as "success."
            success_transition = forward[0] if forward else None
            sig = signatures.get(state)
            nodes.append(DecisionNode(
                condition=f"{protocol.upper()} is in state '{state}'",
                action=f"verify state/evidence for '{state}'",
                expected_result=(f"transitions to '{success_transition.to_state}'"
                                if success_transition else "remains stable (terminal state)"),
                on_success=success_transition.to_state if success_transition else None,
                on_failure=sig.likely_cause if sig else None,
                escalation=("escalate to a human operator if stuck beyond the expected "
                           "convergence window" if sig else None)))
        return DecisionGraph(protocol=protocol, nodes=nodes)

    def compile_risk(self, protocol: str, *, affected_object_count: int = 0,
                     observed_confidence: Optional[float] = None) -> RiskAnnotation:
        signatures = self.compile_root_causes(protocol)
        if not signatures:
            return RiskAnnotation(severity="unknown", probability=0.0,
                                  impact="no verified failure model for this protocol",
                                  affected_object_count=affected_object_count)
        avg_confidence = sum(s.confidence for s in signatures) / len(signatures)
        # A live investigation's actual top-hypothesis confidence is a far
        # better estimate of "how likely is this really the cause" than the
        # static average confidence across every compiled signature for the
        # protocol — that average never changes within a session (it depends
        # on nothing actually observed), so surfacing it as the live "risk
        # probability" freezes the number across rounds even while the real
        # hypothesis confidence swings sharply (e.g. after a fix fails
        # verification and confidence drops). Falls back to the static
        # average when no live session confidence is supplied (e.g.
        # compile_reasoning()'s protocol-general risk profile, which has no
        # session to draw a confidence from).
        probability = avg_confidence if observed_confidence is None else observed_confidence
        severity = "high" if affected_object_count > 10 else (
            "medium" if affected_object_count > 1 else "low")
        impact = (f"Potentially affects {affected_object_count} compiled object(s) if unresolved"
                 if affected_object_count else "Impact scope not supplied by caller")
        return RiskAnnotation(severity=severity, probability=round(probability, 4),
                              impact=impact, affected_object_count=affected_object_count)

    # ── composed artifacts ────────────────────────────────────────────────

    def compile_troubleshooting(self, protocol: str) -> ReasoningArtifact:
        """Composes root causes + verification + remediation + decision
        graph — the workflow, WITHOUT risk (see compile_reasoning)."""
        protocol = (protocol or "").strip().lower()
        signatures = self.compile_root_causes(protocol)
        verification = self.compile_verification(protocol)
        remediation = self.compile_remediation(protocol)
        decision_graph = self.compile_decision_graph(protocol)
        confidence = (sum(s.confidence for s in signatures) / len(signatures)
                     if signatures else 0.0)
        return ReasoningArtifact(
            id=f"artifact:{protocol}:troubleshooting", name=f"{protocol.upper()} troubleshooting workflow",
            description=f"Compiled troubleshooting workflow for {protocol.upper()}, derived "
                       f"from its verified protocol state model.",
            version=1, protocol=protocol,
            evidence=[f"protocol_models.PROTOCOL_STATE_MODELS['{protocol}']"],
            confidence=round(confidence, 4),
            dependencies=[f"protocol_models.build_protocol_model('{protocol}')"],
            inputs=["compiled NormalizedObjects (interface/protocol/neighbor/timer)"],
            outputs=["failure_signatures", "verification", "remediation", "decision_graph"],
            failure_signatures=signatures, verification=verification,
            remediation=remediation, decision_graph=decision_graph)

    def compile_reasoning(self, protocol: str, *, affected_object_count: int = 0) -> ReasoningArtifact:
        """The full outer artifact: compile_troubleshooting's result PLUS
        risk attached."""
        artifact = self.compile_troubleshooting(protocol)
        artifact.id = f"artifact:{artifact.protocol}:reasoning"
        artifact.name = f"{artifact.protocol.upper()} reasoning artifact"
        artifact.risk = self.compile_risk(artifact.protocol, affected_object_count=affected_object_count)
        return artifact

    # ── optimization / incremental / publishing ───────────────────────────

    def optimize_artifacts(self, artifacts: List[ReasoningArtifact]) -> List[ReasoningArtifact]:
        """Dedups artifacts identical on (protocol, content_hash) — same
        shape as Phase 3's CrossDocumentCompiler.optimize_knowledge."""
        seen = set()
        out = []
        for a in artifacts:
            key = (a.protocol, a.content_hash())
            if key in seen:
                continue
            seen.add(key)
            out.append(a)
        return out

    def compile_incremental(self, protocol: str, *, affected_object_count: int = 0) -> ReasoningArtifact:
        """Recomputes (cheap — no file I/O or LLM calls, just in-memory
        composition of already-compiled tables) and hash-compares the
        result: an unchanged hash returns the SAME cached artifact
        (version untouched); a changed hash bumps the version and records
        history — the version/history/rollback tracking this phase asks
        for, without a new persistence layer."""
        protocol = (protocol or "").strip().lower()
        artifact = self.compile_reasoning(protocol, affected_object_count=affected_object_count)
        h = artifact.content_hash()

        if self._last_hash.get(protocol) == h:
            return self._cache[protocol]

        artifact.version = self._version.get(protocol, 0) + 1
        self._version[protocol] = artifact.version
        self._last_hash[protocol] = h
        self._cache[protocol] = artifact
        self._history.setdefault(protocol, []).append(artifact)
        return artifact

    def history_for(self, protocol: str) -> List[ReasoningArtifact]:
        return list(self._history.get((protocol or "").strip().lower(), []))

    def publish_artifacts(self, artifacts: List[ReasoningArtifact]) -> List[str]:
        """Converts via artifact_to_object and publishes through Phase 2's
        graph_ops.merge_into_graph, reused unchanged."""
        objects = [artifact_to_object(a) for a in artifacts]
        published, _issues = graph_ops.merge_into_graph(self.graph, objects)
        return [o.id for o in published]
