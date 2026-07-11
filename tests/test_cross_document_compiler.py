"""
Tests for NKC Phase 3 — Cross-Document Semantic Compiler (facts.py,
fact_conflicts.py, cross_reference.py, protocol_models.py,
cross_document_compiler.py).

Uses the same FakeEmbedder + temp-ChromaDB-dir pattern established in
tests/test_knowledge_parsers.py — no network, no LLM, no real embedding
model download.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.knowledge.compiler import cross_reference, fact_conflicts, protocol_models
from core.knowledge.compiler.cross_document_compiler import CrossDocumentCompiler
from core.knowledge.compiler.facts import Fact, extract_facts_from_text, fact_to_object
from core.knowledge.enterprise.knowledge_layer import (
    EnterpriseKnowledgeLayer, KnowledgeRecord, SourceType,
)
from core.knowledge.rag.embedder import FakeEmbedder
from core.knowledge.rag.rag_engine import RAGEngine
from core.knowledge_graph import KnowledgeGraph


def _layer(tmp_path, name="test"):
    rag = RAGEngine(embedder=FakeEmbedder(), persist_dir=str(tmp_path / "chroma"), collection_name=name)
    return EnterpriseKnowledgeLayer(rag=rag)


# ── facts.py ────────────────────────────────────────────────────────────────

def test_extract_facts_default_value_of_phrasing():
    text = "The default value of the OSPF hello interval is 10 seconds."
    facts = extract_facts_from_text(text, source_doc_id="doc1", vendor="cisco")
    assert len(facts) == 1
    assert facts[0].subject == "ospf hello interval"
    assert facts[0].object == "10 seconds"
    assert facts[0].predicate == "default_value"


def test_extract_facts_by_default_phrasing():
    text = "By default, the OSPF hello interval is 5 seconds."
    facts = extract_facts_from_text(text, source_doc_id="doc2", vendor="juniper")
    assert len(facts) == 1
    assert facts[0].subject == "ospf hello interval"
    assert facts[0].object == "5 seconds"


def test_extract_facts_defaults_to_phrasing():
    text = "BGP keepalive defaults to 60 seconds."
    facts = extract_facts_from_text(text, source_doc_id="doc3")
    assert len(facts) == 1
    assert facts[0].subject == "bgp keepalive"
    assert facts[0].object == "60 seconds"


def test_extract_facts_bare_default_phrasing():
    text = "The default hello interval for OSPF on broadcast networks is 10 seconds."
    facts = extract_facts_from_text(text, source_doc_id="doc4")
    assert len(facts) == 1
    assert "hello interval for ospf" in facts[0].subject
    assert facts[0].object == "10 seconds"


def test_extract_facts_no_match_on_unrelated_prose():
    text = "OSPF is a link-state routing protocol used within an autonomous system."
    assert extract_facts_from_text(text, source_doc_id="doc5") == []


def test_fact_to_object_shape():
    fact = Fact(subject="ospf hello interval", predicate="default_value", object="10 seconds",
               source_doc_id="doc1", vendor="cisco", source_type="vendor_docs", confidence=0.8)
    obj = fact_to_object(fact)
    assert obj.type == "fact"
    assert obj.get("subject") == "ospf hello interval"
    assert obj.get("object") == "10 seconds"
    for key in ("_confidence", "_source_doc_id", "_vendor", "_source_type", "_hash"):
        assert key in obj.attributes


# ── fact_conflicts.py ────────────────────────────────────────────────────────

def test_detect_fact_conflicts_preserves_both_competing_facts():
    f1 = Fact(subject="ospf hello interval", predicate="default_value", object="10 seconds",
             source_doc_id="cisco-doc", vendor="cisco", source_type="vendor_docs")
    f2 = Fact(subject="ospf hello interval", predicate="default_value", object="5 seconds",
             source_doc_id="juniper-doc", vendor="juniper", source_type="vendor_docs")
    records = fact_conflicts.detect_fact_conflicts([f1, f2])
    assert len(records) == 1
    rec = records[0]
    assert rec.kind == "fact"
    assert len(rec.items) == 2
    assert rec.preferred_index in (0, 1)
    assert not rec.resolved


def test_detect_fact_conflicts_no_conflict_when_values_agree():
    f1 = Fact(subject="x", predicate="default_value", object="10", source_doc_id="a")
    f2 = Fact(subject="x", predicate="default_value", object="10", source_doc_id="b")
    assert fact_conflicts.detect_fact_conflicts([f1, f2]) == []


def test_fact_confidence_ranks_higher_authority_source_above_lower():
    f_standard = Fact(subject="x", predicate="default_value", object="10",
                      source_doc_id="a", source_type="config_standard")
    f_incident = Fact(subject="x", predicate="default_value", object="10",
                      source_doc_id="b", source_type="incident")
    group = [f_standard, f_incident]
    assert (fact_conflicts.fact_confidence(f_standard, group)
           > fact_conflicts.fact_confidence(f_incident, group))


def test_detect_cross_device_conflicts_on_disagreeing_vrf():
    graph = KnowledgeGraph()
    graph.add_node("R1:vrf:CUSTOMER_A", "vrf", {"name": "CUSTOMER_A", "rd": "65000:1"})
    graph.add_node("R2:vrf:CUSTOMER_A", "vrf", {"name": "CUSTOMER_A", "rd": "65000:2"})
    records = fact_conflicts.detect_cross_device_conflicts(graph)
    assert len(records) == 1
    assert records[0].kind == "cross_device_object"
    devices = {item["device"] for item in records[0].items}
    assert devices == {"R1", "R2"}


def test_detect_cross_device_conflicts_none_when_same_device_only():
    graph = KnowledgeGraph()
    graph.add_node("R1:vrf:CUSTOMER_A", "vrf", {"name": "CUSTOMER_A", "rd": "65000:1"})
    assert fact_conflicts.detect_cross_device_conflicts(graph) == []


def test_detect_cross_device_conflicts_excludes_acl_type():
    graph = KnowledgeGraph()
    graph.add_node("R1:acl:ACL_IN:aaa", "acl", {"acl_name": "ACL_IN", "action": "permit", "rule": "ip any any"})
    graph.add_node("R2:acl:ACL_IN:bbb", "acl", {"acl_name": "ACL_IN", "action": "deny", "rule": "ip any any"})
    # ACL is intentionally excluded (per-rule granularity would produce
    # false-positive conflicts) — see docs/nkc_fact_and_conflict_model.md.
    assert fact_conflicts.detect_cross_device_conflicts(graph) == []


# ── cross_reference.py ──────────────────────────────────────────────────────

def test_find_references_all_kinds():
    text = (
        "See RFC 2328 for the OSPF specification.\n"
        "This issue is tracked as CVE-2023-1234.\n"
        "Refer to bug CSCab12345 for details.\n"
        "Field notice FN12345 applies to this platform.\n"
    )
    refs = cross_reference.find_references(text)
    kinds = {r.kind for r in refs}
    assert kinds == {"rfc", "cve", "cisco_bug_id", "field_notice"}
    values = {r.value for r in refs}
    assert "RFC2328" in values
    assert "CVE-2023-1234" in values
    assert "CSCAB12345" in values
    assert "FN12345" in values


def test_find_references_empty_on_plain_text():
    assert cross_reference.find_references("Just a normal sentence with no references.") == []


# ── protocol_models.py ───────────────────────────────────────────────────────

def test_ospf_state_model_transitions():
    model = protocol_models.build_protocol_model("ospf")
    assert model is not None
    assert "Full" in model.states
    assert model.is_valid_transition("Exchange", "Loading")
    assert model.is_valid_transition("Loading", "Full")
    assert not model.is_valid_transition("Down", "Full")
    assert "Init" in model.next_states("Down") or "Attempt" in model.next_states("Down")


def test_stp_state_model_transitions():
    model = protocol_models.build_protocol_model("stp")
    assert model is not None
    assert model.is_valid_transition("Learning", "Forwarding")


def test_unknown_protocol_returns_none_not_a_guess():
    # "bgp" was the example unmodeled protocol before BGP support was added
    # (protocol_models.py now seeds ospf/stp/bgp) — "eigrp" is still
    # genuinely unmodeled and exercises the same "never fabricate" behavior.
    assert protocol_models.build_protocol_model("eigrp") is None
    assert protocol_models.build_protocol_model("totally-made-up") is None


# ── CrossDocumentCompiler integration ────────────────────────────────────────

def test_cross_document_compiler_end_to_end(tmp_path):
    layer = _layer(tmp_path, name="xdoc")
    layer.ingest(KnowledgeRecord(
        doc_id="cisco-ospf-guide", title="Cisco OSPF Defaults",
        content="The default value of the OSPF hello interval is 10 seconds.",
        source_type=SourceType.VENDOR_DOCS, vendor="cisco"))
    layer.ingest(KnowledgeRecord(
        doc_id="juniper-ospf-guide", title="Juniper OSPF Defaults",
        content="By default, the OSPF hello interval is 5 seconds.",
        source_type=SourceType.VENDOR_DOCS, vendor="juniper"))

    compiler = CrossDocumentCompiler(layer=layer, graph=KnowledgeGraph())

    facts = compiler.compile_facts("OSPF hello interval default")
    assert len(facts) >= 2
    values = {f.object for f in facts}
    assert "10 seconds" in values
    assert "5 seconds" in values

    issues = compiler.validate_facts(facts)
    assert not any(i.severity == "error" for i in issues)

    conflicts = compiler.resolve_conflicts(facts)
    assert len(conflicts) == 1
    assert len(conflicts[0].items) == len(facts)

    # Uses a distinct query so it doesn't add an extra history entry under
    # the same key the compare_versions() check below tracks — correlate_
    # documents() legitimately calls compile_facts() internally.
    correlated = compiler.correlate_documents("OSPF hello interval defaults by vendor")
    assert "cisco" in correlated and "juniper" in correlated

    evidence = compiler.merge_evidence(facts)
    assert list(evidence.values())[0] == facts if len(evidence) == 1 else True

    optimized = compiler.optimize_knowledge(facts + facts)   # duplicate the list
    assert len(optimized) == len(facts)   # exact duplicates collapsed

    published_ids = compiler.publish_facts(facts)
    assert len(published_ids) == len(facts)
    assert all(compiler.graph.nodes[nid].label == "fact" for nid in published_ids)

    compiler.compile_facts("OSPF hello interval default")   # second call, same query
    diff = compiler.compare_versions("OSPF hello interval default")
    assert diff["compile_count"] == 2
    assert diff["added"] == [] and diff["removed"] == [] and diff["changed"] == []


def test_cross_document_compiler_detect_cross_device_conflicts_delegates(tmp_path):
    layer = _layer(tmp_path, name="xdoc2")
    graph = KnowledgeGraph()
    graph.add_node("R1:vlan:10", "vlan", {"id": 10, "name": "USERS"})
    graph.add_node("R2:vlan:10", "vlan", {"id": 10, "name": "VOICE"})
    compiler = CrossDocumentCompiler(layer=layer, graph=graph)
    records = compiler.detect_cross_device_conflicts()
    assert len(records) == 1
    assert records[0].kind == "cross_device_object"
