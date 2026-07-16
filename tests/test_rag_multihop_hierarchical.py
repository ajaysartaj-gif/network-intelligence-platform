"""
Tests for Phase 4 of the RAG improvement pass: multi-hop query decomposition
(core/knowledge/rag/query_planning.py, EnterpriseKnowledgeLayer.multi_hop_search)
and coarse-to-fine hierarchical retrieval (EnterpriseKnowledgeLayer.
coarse_to_fine_search). Neither existed before this pass.
"""
import os
import sys
import types

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from core.knowledge.enterprise.knowledge_layer import (
    EnterpriseKnowledgeLayer, KnowledgeRecord, SourceType,
)
from core.knowledge.rag.embedder import FakeEmbedder
from core.knowledge.rag.query_planning import decompose_query
from core.knowledge.rag.rag_engine import RAGEngine
from tests.test_general_corpus import _DOCS, _read_corpus_file


def _layer(tmp_path, name="multihop-test"):
    rag = RAGEngine(embedder=FakeEmbedder(), persist_dir=str(tmp_path / "chroma"),
                    collection_name=name)
    return EnterpriseKnowledgeLayer(rag=rag)


# ── decompose_query ──────────────────────────────────────────────────────────
def test_decompose_query_without_ai_call_returns_single_hop():
    assert decompose_query("why is OSPF stuck in EXSTART") == ["why is OSPF stuck in EXSTART"]


def test_decompose_query_empty_string_returns_empty_list():
    assert decompose_query("") == []


def test_decompose_query_splits_compound_question_via_ai_call():
    def fake_ai(prompt: str) -> str:
        return ('{"subqueries": ["why is the OSPF neighbor down", '
               '"what is the vendor recommended fix for OSPF MTU mismatch"]}')

    subs = decompose_query("why is the OSPF neighbor down and what is the fix", ai_call=fake_ai)
    assert len(subs) == 2
    assert "OSPF neighbor down" in subs[0]


def test_decompose_query_respects_max_subqueries_cap():
    def fake_ai(prompt: str) -> str:
        return '{"subqueries": ["a", "b", "c", "d", "e"]}'

    subs = decompose_query("compound", ai_call=fake_ai, max_subqueries=2)
    assert len(subs) == 2


def test_decompose_query_falls_back_to_single_hop_on_broken_ai_output():
    def broken_ai(prompt: str) -> str:
        return "not json"

    assert decompose_query("q", ai_call=broken_ai) == ["q"]


def test_decompose_query_falls_back_when_ai_call_raises():
    def raising_ai(prompt: str) -> str:
        raise RuntimeError("down")

    assert decompose_query("q", ai_call=raising_ai) == ["q"]


def test_decompose_query_empty_subqueries_falls_back_to_original():
    def empty_ai(prompt: str) -> str:
        return '{"subqueries": []}'

    assert decompose_query("q", ai_call=empty_ai) == ["q"]


# ── multi_hop_search ──────────────────────────────────────────────────────────
def test_multi_hop_search_without_ai_call_degrades_to_single_hop(tmp_path):
    layer = _layer(tmp_path)
    layer.ingest(KnowledgeRecord(
        doc_id="eigrp", title="EIGRP", source_type=SourceType.BEST_PRACTICE,
        content=_read_corpus_file("eigrp.txt")))

    single = layer.search("EIGRP neighbor won't form", top_k=3)
    multi = layer.multi_hop_search("EIGRP neighbor won't form", ai_call=None, top_k=3)
    assert [h.doc_id for h in single] == [h.doc_id for h in multi]


def test_multi_hop_search_surfaces_both_topics_a_single_search_would_miss(tmp_path):
    """
    Ingest two DISTINCT-technology docs. A compound query naming both
    topics, searched as ONE vector, only has room for top_k hits total —
    engineer top_k=1 so a single-hop search can only return one document.
    Multi-hop, given a fake decomposition into the two clean sub-questions,
    must surface BOTH documents' relevant hits (one per hop).
    """
    layer = _layer(tmp_path)
    layer.ingest(KnowledgeRecord(
        doc_id="eigrp", title="EIGRP", source_type=SourceType.BEST_PRACTICE,
        content=_read_corpus_file("eigrp.txt")))
    layer.ingest(KnowledgeRecord(
        doc_id="vrrp", title="VRRP", source_type=SourceType.BEST_PRACTICE,
        content=_read_corpus_file("vrrp.txt")))

    compound = "EIGRP K-value mismatch and VRRP multiple routers claiming master"
    single = layer.search(compound, top_k=1)
    assert len(single) == 1   # only one document's worth of room

    def fake_ai(prompt: str) -> str:
        return ('{"subqueries": ["EIGRP K-value mismatch neighbor authentication", '
               '"VRRP multiple routers claiming master advertisement"]}')

    multi = layer.multi_hop_search(compound, ai_call=fake_ai, top_k=5, per_hop_k=3)
    doc_ids = {h.doc_id for h in multi}
    assert doc_ids == {"eigrp", "vrrp"}


def test_multi_hop_search_dedupes_keeping_highest_confidence(tmp_path):
    layer = _layer(tmp_path)
    layer.ingest(KnowledgeRecord(
        doc_id="eigrp", title="EIGRP", source_type=SourceType.BEST_PRACTICE,
        content=_read_corpus_file("eigrp.txt")))

    def fake_ai(prompt: str) -> str:
        return ('{"subqueries": ["EIGRP neighbor K-value mismatch", '
               '"EIGRP neighbor authentication failure"]}')

    multi = layer.multi_hop_search("EIGRP neighbor problems", ai_call=fake_ai, top_k=5, per_hop_k=3)
    # No duplicate (doc_id, chunk) pairs in the merged result.
    keys = [f"{h.doc_id}::{h.metadata.get('chunk', '')}" for h in multi]
    assert len(keys) == len(set(keys))


# ── coarse_to_fine_search ──────────────────────────────────────────────────────
def test_coarse_to_fine_search_still_finds_the_right_labeled_document(tmp_path):
    layer = _layer(tmp_path, name="coarse-fine-mixed")
    for doc_id, (filename, _query, _expect) in _DOCS.items():
        layer.ingest(KnowledgeRecord(
            doc_id=doc_id, title=filename.replace(".txt", "").replace("_", " "),
            content=_read_corpus_file(filename), source_type=SourceType.BEST_PRACTICE,
            tags=["general-corpus", doc_id]))

    # The _DOCS["eigrp"] query was only ever validated against an ISOLATED
    # single-doc collection (test_realistic_troubleshooting_query_retrieves_
    # own_content). Against all 8 mixed docs, use the query already proven
    # reliable at that scale (test_cross_technology_query_does_not_cross_
    # contaminate) rather than assume the isolated-context query transfers.
    query = "EIGRP K-value mismatch neighbor authentication"
    hits = layer.coarse_to_fine_search(query, top_k=3, coarse_doc_limit=3)
    assert hits
    assert hits[0].doc_id == "eigrp"


def test_coarse_to_fine_search_fine_pass_is_restricted_to_coarse_candidates(tmp_path, monkeypatch):
    """The fine-pass search() call must actually be scoped to doc_ids, not
    just coincidentally return the right thing — assert on the real
    mechanism, not the outcome alone."""
    layer = _layer(tmp_path, name="coarse-fine-scoped")
    for doc_id, (filename, _query, _expect) in _DOCS.items():
        layer.ingest(KnowledgeRecord(
            doc_id=doc_id, title=filename.replace(".txt", "").replace("_", " "),
            content=_read_corpus_file(filename), source_type=SourceType.BEST_PRACTICE,
            tags=["general-corpus", doc_id]))

    seen_doc_ids_kwarg = []
    real_search = layer.search

    def spy_search(query, **kwargs):
        if "doc_ids" in kwargs:
            seen_doc_ids_kwarg.append(kwargs["doc_ids"])
        return real_search(query, **kwargs)

    monkeypatch.setattr(layer, "search", spy_search)

    _filename, query, _expect = _DOCS["vrrp"]
    layer.coarse_to_fine_search(query, top_k=3, coarse_doc_limit=2)
    assert seen_doc_ids_kwarg, "fine pass never called search() with doc_ids"
    assert "vrrp" in seen_doc_ids_kwarg[0]
    assert len(seen_doc_ids_kwarg[0]) <= 2


def test_coarse_to_fine_search_returns_empty_when_corpus_is_empty(tmp_path):
    layer = _layer(tmp_path, name="coarse-fine-empty")
    assert layer.coarse_to_fine_search("anything", top_k=3) == []


def test_search_doc_ids_filter_restricts_results_directly(tmp_path):
    layer = _layer(tmp_path, name="doc-ids-filter")
    layer.ingest(KnowledgeRecord(
        doc_id="eigrp", title="EIGRP", source_type=SourceType.BEST_PRACTICE,
        content=_read_corpus_file("eigrp.txt")))
    layer.ingest(KnowledgeRecord(
        doc_id="vrrp", title="VRRP", source_type=SourceType.BEST_PRACTICE,
        content=_read_corpus_file("vrrp.txt")))

    hits = layer.search("neighbor", top_k=5, doc_ids=["eigrp"])
    assert hits
    assert all(h.doc_id == "eigrp" for h in hits)
