"""
Tests for Phase 3 of the RAG improvement pass: the evaluation harness
(core/knowledge/rag/evaluation.py) — context relevance (retrieval quality),
faithfulness, and answer relevance. None of this existed before this pass.

Reuses the existing labeled query set from tests/test_general_corpus.py
(_DOCS: doc_id -> filename/query/expect_phrase across 8 real technologies)
rather than fabricating a separate eval set — that table is already the
platform's one place mapping a realistic troubleshooting question to the
document that should answer it.
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
from core.knowledge.rag.evaluation import (
    EvalCase, mean_reciprocal_rank, score_answer_relevance, score_faithfulness,
    score_retrieval,
)
from core.knowledge.rag.rag_engine import RAGEngine
from tests.test_general_corpus import _CORPUS_GENERAL_DIR, _DOCS, _read_corpus_file


def _layer(tmp_path, name="rag-eval"):
    rag = RAGEngine(embedder=FakeEmbedder(), persist_dir=str(tmp_path / "chroma"),
                    collection_name=name)
    return EnterpriseKnowledgeLayer(rag=rag)


# ── Context relevance: retrieval-quality regression harness ─────────────────
def test_retrieval_eval_harness_reports_mrr_across_the_labeled_corpus(tmp_path):
    """
    The actual eval harness: ingest every _DOCS technology together (same
    'don't cross-contaminate' setup as test_general_corpus.py), run every
    labeled query, score each with score_retrieval, and report an aggregate
    MRR — a real regression signal future retrieval changes can be measured
    against, not just per-case pass/fail.
    """
    layer = _layer(tmp_path, name="eval-mixed")
    for doc_id, (filename, _query, _expect) in _DOCS.items():
        layer.ingest(KnowledgeRecord(
            doc_id=doc_id, title=filename.replace(".txt", "").replace("_", " "),
            content=_read_corpus_file(filename), source_type=SourceType.BEST_PRACTICE,
            tags=["general-corpus", doc_id]))

    scores = []
    for doc_id, (_filename, query, _expect) in _DOCS.items():
        case = EvalCase(query=query, expected_doc_ids=[doc_id])
        hits = layer.search(query, top_k=3)
        retrieved_ids = [h.doc_id for h in hits]
        scores.append(score_retrieval(case, retrieved_ids))

    mrr = mean_reciprocal_rank(scores)
    misses = [s for s in scores if not s.hit_at_1]
    assert mrr >= 0.75, f"MRR regressed to {mrr}; misses: {[m.query for m in misses]}"


def test_score_retrieval_precision_recall_reciprocal_rank():
    case = EvalCase(query="q", expected_doc_ids=["ospf"])
    perfect = score_retrieval(case, ["ospf", "bgp", "vrrp"])
    assert perfect.hit_at_1 and perfect.reciprocal_rank == 1.0
    assert perfect.precision_at_k == round(1 / 3, 4)
    assert perfect.recall_at_k == 1.0

    second_place = score_retrieval(case, ["bgp", "ospf", "vrrp"])
    assert not second_place.hit_at_1
    assert second_place.reciprocal_rank == 0.5

    total_miss = score_retrieval(case, ["bgp", "vrrp"])
    assert total_miss.reciprocal_rank == 0.0
    assert total_miss.recall_at_k == 0.0


def test_mean_reciprocal_rank_of_empty_list_is_zero_not_a_crash():
    assert mean_reciprocal_rank([]) == 0.0


# ── Faithfulness: must actually discriminate grounded vs. fabricated ───────
def test_faithfulness_scores_grounded_answer_higher_than_fabricated_one():
    evidence = ["OSPF neighbors stuck in EXSTART almost always indicate an MTU "
               "mismatch between the two interfaces, since DBD packets are the "
               "first ones sized to the configured interface MTU."]

    grounded_answer = ("The neighbors are stuck in EXSTART because of an MTU "
                       "mismatch between the interfaces.")
    fabricated_answer = "The router was manufactured with a faulty power supply unit."

    grounded = score_faithfulness(grounded_answer, evidence)
    fabricated = score_faithfulness(fabricated_answer, evidence)

    assert grounded.score > fabricated.score
    assert fabricated.ungrounded_claims


def test_faithfulness_llm_judge_path_used_when_ai_call_provided():
    def fake_ai(prompt: str) -> str:
        return '{"ungrounded_sentences": ["The router exploded."]}'

    result = score_faithfulness(
        "The interface is down. The router exploded.",
        ["Evidence says the interface is administratively down."],
        ai_call=fake_ai,
    )
    assert result.method == "llm"
    assert result.ungrounded_claims == ["The router exploded."]
    assert result.score == 0.5   # 1 of 2 sentences flagged


def test_faithfulness_falls_back_to_heuristic_when_llm_judge_output_is_broken():
    def broken_ai(prompt: str) -> str:
        return "not valid json at all"

    result = score_faithfulness(
        "OSPF neighbors need matching MTU to move past EXSTART.",
        ["OSPF requires matching MTU on both sides of a link to move past EXSTART."],
        ai_call=broken_ai,
    )
    assert result.method == "heuristic"   # silently degraded, did not crash


def test_faithfulness_empty_answer_is_trivially_faithful():
    assert score_faithfulness("", ["some evidence"]).score == 1.0


# ── Answer relevance: must discriminate on-topic vs. off-topic ─────────────
def test_answer_relevance_scores_on_topic_higher_than_off_topic():
    query = "why is the OSPF neighbor stuck in ExStart state"
    on_topic = "The OSPF neighbor is stuck in ExStart due to an MTU mismatch."
    off_topic = "Quarterly sales figures increased by twelve percent this year."

    on = score_answer_relevance(query, on_topic)
    off = score_answer_relevance(query, off_topic)
    assert on.score > off.score


def test_answer_relevance_llm_judge_path_used_when_ai_call_provided():
    def fake_ai(prompt: str) -> str:
        return '{"score": 0.9}'

    result = score_answer_relevance("q", "a", ai_call=fake_ai)
    assert result.method == "llm"
    assert result.score == 0.9


def test_answer_relevance_falls_back_to_heuristic_when_llm_judge_output_is_broken():
    def broken_ai(prompt: str) -> str:
        raise RuntimeError("API down")

    result = score_answer_relevance("ospf mtu mismatch", "ospf mtu mismatch fix", ai_call=broken_ai)
    assert result.method == "heuristic"
    assert result.score > 0.0
