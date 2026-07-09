"""
Tests for NKC Phase 4 — Reasoning Artifact Compiler (artifacts.py,
failure_signatures.py, reasoning_artifact_compiler.py).

No network, no LLM, no real embedding model.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.knowledge.compiler import failure_signatures
from core.knowledge.compiler.artifacts import artifact_to_object
from core.knowledge.compiler.reasoning_artifact_compiler import ReasoningArtifactCompiler
from core.vendor.adapters.cisco_ios_like import IosLikeAdapter
from core.vendor.models import NormalizedObject, VendorProfile
from core.knowledge_graph import KnowledgeGraph


# ── failure_signatures.py ────────────────────────────────────────────────

def test_ospf_signatures_include_exstart_mtu_and_init_hello_mismatch():
    sigs = failure_signatures.compile_failure_signatures("ospf")
    by_state = {s.stuck_state: s for s in sigs}
    assert "mtu" in by_state["ExStart"].likely_cause.lower()
    assert by_state["ExStart"].confidence >= 0.8
    assert "hello" in by_state["Init"].likely_cause.lower() or "area" in by_state["Init"].likely_cause.lower()


def test_ospf_2way_signature_notes_its_often_normal():
    sigs = failure_signatures.compile_failure_signatures("ospf")
    two_way = next(s for s in sigs if s.stuck_state == "2-Way")
    assert "normal" in two_way.likely_cause.lower()
    assert two_way.confidence < 0.5   # honestly hedged, not asserted as a failure


def test_stp_signature_present():
    sigs = failure_signatures.compile_failure_signatures("stp")
    assert any(s.stuck_state == "Blocking" for s in sigs)


def test_unmodeled_protocol_returns_empty_list_not_a_guess():
    assert failure_signatures.compile_failure_signatures("bgp") == []
    assert failure_signatures.compile_failure_signatures("vxlan") == []


def test_acl_deny_signature_from_compiled_acl_object():
    acl_obj = NormalizedObject(type="acl", id="R1:acl:ACL_IN:abc", device="R1",
                               attributes={"acl_name": "ACL_IN", "action": "deny", "rule": "ip any any"})
    permit_obj = NormalizedObject(type="acl", id="R1:acl:ACL_IN:def", device="R1",
                                  attributes={"acl_name": "ACL_IN", "action": "permit", "rule": "tcp any any eq 80"})
    sigs = failure_signatures.compile_acl_deny_signature([acl_obj, permit_obj])
    assert len(sigs) == 1
    assert "ACL_IN" in sigs[0].likely_cause
    assert sigs[0].confidence >= 0.85


# ── artifacts.py ──────────────────────────────────────────────────────────

def test_artifact_to_object_shape():
    compiler = ReasoningArtifactCompiler(graph=KnowledgeGraph())
    artifact = compiler.compile_reasoning("ospf")
    obj = artifact_to_object(artifact)
    assert obj.type == "reasoning_artifact"
    assert obj.get("protocol") == "ospf"
    for key in ("_confidence", "_extracted_by", "_compiler_version", "_hash"):
        assert key in obj.attributes


# ── ReasoningArtifactCompiler ────────────────────────────────────────────

def test_compile_root_causes_verification_remediation_decision_graph_risk():
    compiler = ReasoningArtifactCompiler(graph=KnowledgeGraph())

    causes = compiler.compile_root_causes("ospf")
    assert causes

    verification = compiler.compile_verification("ospf")
    assert verification and "show ip ospf neighbor" in verification[0].commands

    remediation = compiler.compile_remediation("ospf")
    assert remediation
    real_intents = set(IosLikeAdapter().supported_intents(VendorProfile()))
    for template in remediation:
        assert template.intent_name in real_intents   # never an invented intent

    decision_graph = compiler.compile_decision_graph("ospf")
    assert decision_graph is not None
    assert any(n.condition.endswith("'ExStart'") for n in decision_graph.nodes)

    risk = compiler.compile_risk("ospf", affected_object_count=5)
    assert risk.severity in ("low", "medium", "high")
    assert 0.0 <= risk.probability <= 1.0
    assert "GovernanceEngine" in risk.mitigation_reference


def test_compile_remediation_returns_empty_for_stp_no_matching_intent():
    compiler = ReasoningArtifactCompiler(graph=KnowledgeGraph())
    # No STP-related vendor-adapter intent exists yet — must not invent one.
    assert compiler.compile_remediation("stp") == []


def test_compile_troubleshooting_excludes_risk_compile_reasoning_includes_it():
    compiler = ReasoningArtifactCompiler(graph=KnowledgeGraph())
    workflow = compiler.compile_troubleshooting("ospf")
    assert workflow.risk is None

    full = compiler.compile_reasoning("ospf", affected_object_count=3)
    assert full.risk is not None
    assert full.failure_signatures and full.verification and full.remediation
    assert full.decision_graph is not None


def test_unmodeled_protocol_every_method_degrades_gracefully():
    compiler = ReasoningArtifactCompiler(graph=KnowledgeGraph())
    assert compiler.compile_root_causes("bgp") == []
    assert compiler.compile_verification("bgp") == []
    assert compiler.compile_remediation("bgp") == []
    assert compiler.compile_decision_graph("bgp") is None
    risk = compiler.compile_risk("bgp")
    assert risk.severity == "unknown"
    artifact = compiler.compile_reasoning("bgp")
    assert artifact.failure_signatures == []
    assert artifact.decision_graph is None


def test_optimize_artifacts_dedups_identical_content():
    compiler = ReasoningArtifactCompiler(graph=KnowledgeGraph())
    a1 = compiler.compile_reasoning("ospf")
    a2 = compiler.compile_reasoning("ospf")
    optimized = compiler.optimize_artifacts([a1, a2])
    assert len(optimized) == 1


def test_compile_incremental_skips_on_unchanged_then_versions_are_stable():
    compiler = ReasoningArtifactCompiler(graph=KnowledgeGraph())
    first = compiler.compile_incremental("ospf")
    assert first.version == 1

    second = compiler.compile_incremental("ospf")
    assert second.version == 1          # unchanged -> same cached artifact, no version bump
    assert second is first

    history = compiler.history_for("ospf")
    assert len(history) == 1            # only one real compile recorded


def test_publish_artifacts_writes_into_shared_knowledge_graph():
    graph = KnowledgeGraph()
    compiler = ReasoningArtifactCompiler(graph=graph)
    artifact = compiler.compile_reasoning("ospf")
    published_ids = compiler.publish_artifacts([artifact])
    assert len(published_ids) == 1
    assert graph.nodes[published_ids[0]].label == "reasoning_artifact"
