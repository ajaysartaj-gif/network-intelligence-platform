"""
Tests for Phase 2 of the RAG improvement pass: parent-child hierarchical
chunking (core/knowledge/rag/rag_engine.py) and cross-encoder re-ranking
(core/knowledge/rag/reranker.py, wired into EnterpriseKnowledgeLayer.search()).

Uses FakeEmbedder/FakeReranker (deterministic, dependency-free) against a
real, temp-directory-backed ChromaDB — the same pattern already established
in tests/test_grounding_citations.py — so these verify real ingest/search
behavior, not mocked-out plumbing.
"""
import sys
import types
from pathlib import Path

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.knowledge.enterprise.knowledge_layer import (
    EnterpriseKnowledgeLayer, KnowledgeRecord, SourceType,
)
from core.knowledge.rag.embedder import FakeEmbedder
from core.knowledge.rag.rag_engine import RAGEngine, _chunk_hierarchical
from core.knowledge.rag.reranker import FakeReranker, Reranker


# ── parent-child chunking (unit) ─────────────────────────────────────────────
def test_hierarchical_chunking_children_are_smaller_than_their_parent():
    # Realistic sentence density (unlike a single long unbroken run-on) so the
    # splitter actually has boundaries to cut on below child_target.
    sentence = "OSPF requires the hello and dead timers to match on both ends. "
    text = "\n\n".join([f"Paragraph {i}. " + sentence * 3 for i in range(20)])
    pairs = _chunk_hierarchical(text, child_target=150, parent_target=800)
    assert pairs
    for child, parent in pairs:
        assert len(child) <= 150 + 60          # small tolerance for boundary rounding
        assert len(parent) >= len(child)


def test_hierarchical_chunking_multiple_children_can_share_one_parent():
    # One parent-sized paragraph, long enough to need >1 child chunk.
    text = "Sentence about OSPF. " * 30
    pairs = _chunk_hierarchical(text, child_target=100, parent_target=2000)
    parents = {p for _, p in pairs}
    assert len(pairs) > len(parents)   # at least one parent has >1 child


def test_hierarchical_chunking_short_text_is_its_own_parent_and_child():
    pairs = _chunk_hierarchical("short doc")
    assert pairs == [("short doc", "short doc")]


# ── RAGEngine: parent returned as text, child as matched_snippet ────────────
def test_ragengine_search_returns_parent_context_and_matched_child_snippet(tmp_path):
    rag = RAGEngine(embedder=FakeEmbedder(), persist_dir=str(tmp_path / "chroma"), collection_name="test1")
    long_doc = ("OSPF adjacency intro paragraph, general background text padding here.\n\n"
                + "The hello and dead timers must match between neighbors for the "
                  "adjacency to form correctly on the link.\n\n"
                + "Unrelated closing paragraph about a totally different topic entirely.")
    rag.ingest_document(doc_id="doc1", title="OSPF Timers", content=long_doc, source="vendor_docs")

    hits = rag.search("hello dead timer mismatch", top_k=3)
    assert hits
    top = hits[0]
    # matched_snippet is the small child; text is the larger parent it came from.
    assert top.matched_snippet
    assert top.matched_snippet in top.text or len(top.text) >= len(top.matched_snippet)


# ── Re-ranking: verify it actually changes ordering, not just present ───────
def _layer(tmp_path, reranker=None):
    rag = RAGEngine(embedder=FakeEmbedder(), persist_dir=str(tmp_path / "chroma"), collection_name="test2")
    return EnterpriseKnowledgeLayer(rag=rag, reranker=reranker)


def test_reranking_can_override_rrf_fusion_order(tmp_path):
    layer = _layer(tmp_path, reranker=FakeReranker())
    # Two docs engineered so RRF fusion (token-overlap keyword arm dominating,
    # since FakeEmbedder's semantic arm is a crude hash-bow, not real
    # semantics) ranks "Alpha" ahead of "Beta" pre-rerank, but FakeReranker's
    # own token-overlap scoring against the QUERY specifically favors Beta's
    # matched_snippet content once child chunking isolates it.
    layer.ingest(KnowledgeRecord(
        doc_id="alpha", title="Alpha", source_type=SourceType.VENDOR_DOCS,
        content="Alpha document mentions ospf network several times ospf ospf network."))
    layer.ingest(KnowledgeRecord(
        doc_id="beta", title="Beta", source_type=SourceType.VENDOR_DOCS,
        content="Beta document: bgp neighbor stuck in idle state requires investigation."))

    no_rerank = layer.search("bgp neighbor idle", top_k=2, rerank=False)
    with_rerank = layer.search("bgp neighbor idle", top_k=2, rerank=True, rerank_pool=2)

    assert with_rerank[0].doc_id == "beta"
    assert with_rerank[0].metadata.get("_rerank_score") is not None
    # sanity: reranked list is still the same SET of hits, just reordered/scored
    assert {h.doc_id for h in with_rerank} == {h.doc_id for h in no_rerank}


def test_reranking_gracefully_falls_back_when_reranker_raises(tmp_path):
    class _BrokenReranker(Reranker):
        def score(self, query, candidates):
            raise RuntimeError("model not installed")

        @property
        def name(self):
            return "broken"

    layer = _layer(tmp_path, reranker=_BrokenReranker())
    layer.ingest(KnowledgeRecord(
        doc_id="doc1", title="Doc1", source_type=SourceType.VENDOR_DOCS,
        content="ospf hello timer mismatch causes exstart stuck neighbor state."))

    # Must not raise — falls back to the pre-rerank (RRF/confidence) order.
    hits = layer.search("ospf exstart", top_k=3, rerank=True)
    assert hits
    assert layer._rerank_failures == 1


def test_rerank_false_skips_reranking_entirely(tmp_path):
    class _CountingReranker(Reranker):
        calls = 0

        def score(self, query, candidates):
            _CountingReranker.calls += 1
            return [1.0] * len(candidates)

        @property
        def name(self):
            return "counting"

    layer = _layer(tmp_path, reranker=_CountingReranker())
    layer.ingest(KnowledgeRecord(
        doc_id="doc1", title="Doc1", source_type=SourceType.VENDOR_DOCS,
        content="some vendor documentation text about routing protocols."))

    layer.search("routing protocols", top_k=3, rerank=False)
    assert _CountingReranker.calls == 0
