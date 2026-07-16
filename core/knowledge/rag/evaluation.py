"""
core/knowledge/rag/evaluation.py
=================================
RAG evaluation harness: context relevance (retrieval quality), faithfulness,
and answer relevance. None of this existed before — retrieval changes could
only be "eyeballed" against a handful of hand-written assertions. This module
gives those same signals a name and a reusable, scorable API so future
retrieval changes (chunking, re-ranking, query planning) can be measured
against a baseline instead of guessed at.

Each metric has a DETERMINISTIC fallback (token-overlap — no LLM call, no
network, no flakiness) so this harness always runs in CI, plus an optional
ai_call hook for a genuine LLM-graded judgment when one is available — same
pluggable-degradation philosophy already used by embedder.py/reranker.py.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional


_STOPWORDS = frozenset((
    "the a an is are was were be been of in on at to for with by from and or "
    "but because since it this that these those as so than then if while "
    "not no do does did has have had will would can could should may might"
).split())


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _content_tokens(text: str) -> set:
    """Tokens with common stopwords removed. A fabricated claim can reuse a
    query/evidence's framing words ("the neighbors are stuck in EXSTART...")
    while the actual substance is invented — counting stopword overlap as
    'grounded' would let exactly that kind of answer slip past undetected."""
    return _tokens(text) - _STOPWORDS


def _strip_json_fence(raw: str) -> str:
    return re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.M).strip()


# ── Context relevance (retrieval quality) ────────────────────────────────────
@dataclass
class EvalCase:
    """One labeled query with its known-correct source document(s)."""
    query: str
    expected_doc_ids: List[str]
    notes: str = ""


@dataclass
class RetrievalScore:
    query: str
    expected_doc_ids: List[str]
    retrieved_doc_ids: List[str]
    hit_at_1: bool
    precision_at_k: float
    recall_at_k: float
    reciprocal_rank: float


def score_retrieval(case: EvalCase, retrieved_doc_ids: List[str]) -> RetrievalScore:
    """
    Deterministic IR metrics against a known-correct set of doc_ids — no LLM
    judge needed here, since the eval set itself already tells us which
    document SHOULD answer each query.
    """
    expected = set(case.expected_doc_ids)
    retrieved = list(retrieved_doc_ids)
    hits = [d for d in retrieved if d in expected]
    hit_at_1 = bool(retrieved) and retrieved[0] in expected
    precision = len(hits) / len(retrieved) if retrieved else 0.0
    recall = len(set(hits)) / len(expected) if expected else 0.0
    rr = 0.0
    for rank, d in enumerate(retrieved, start=1):
        if d in expected:
            rr = 1.0 / rank
            break
    return RetrievalScore(query=case.query, expected_doc_ids=sorted(expected),
                          retrieved_doc_ids=retrieved, hit_at_1=hit_at_1,
                          precision_at_k=round(precision, 4), recall_at_k=round(recall, 4),
                          reciprocal_rank=round(rr, 4))


def mean_reciprocal_rank(scores: List[RetrievalScore]) -> float:
    if not scores:
        return 0.0
    return round(sum(s.reciprocal_rank for s in scores) / len(scores), 4)


# ── Faithfulness ─────────────────────────────────────────────────────────────
@dataclass
class FaithfulnessScore:
    score: float                                     # [0,1]
    ungrounded_claims: List[str] = field(default_factory=list)
    method: str = "heuristic"                         # "heuristic" | "llm"


def score_faithfulness(answer: str, evidence_texts: List[str],
                       ai_call: Optional[Callable[[str], str]] = None,
                       overlap_threshold: float = 0.3) -> FaithfulnessScore:
    """
    Does every claim in `answer` trace back to `evidence_texts`? This is the
    same grounding discipline as the troubleshooting engine's
    Hypothesis.has_grounded_evidence from earlier this session, applied to
    generated RAG answers instead of hypothesis evidence — an answer sentence
    with no real support in the retrieved evidence is exactly the failure
    mode RAG exists to prevent (the model inventing something the corpus
    never actually said).

    With ai_call: one LLM-judge call identifies ungrounded sentences
    directly. Without (or on judge failure): a deterministic per-sentence
    token-overlap heuristic against the evidence — lower fidelity, but always
    available, so this harness never depends on a live model to run in CI.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer or "") if s.strip()]
    if not sentences:
        return FaithfulnessScore(score=1.0, method="heuristic")

    if ai_call is not None:
        try:
            prompt = (
                "You are checking whether an ANSWER's claims are actually "
                "supported by the EVIDENCE below. List any sentence from the "
                "ANSWER that makes a claim NOT supported by the EVIDENCE.\n\n"
                f"EVIDENCE:\n{chr(10).join(evidence_texts)}\n\nANSWER:\n{answer}\n\n"
                'STRICT JSON: {"ungrounded_sentences": []}'
            )
            d = json.loads(_strip_json_fence(ai_call(prompt) or ""))
            ungrounded = [str(x) for x in d.get("ungrounded_sentences", [])]
            score = 1.0 - (len(ungrounded) / len(sentences))
            return FaithfulnessScore(score=round(max(0.0, score), 4),
                                     ungrounded_claims=ungrounded, method="llm")
        except Exception:
            pass   # fall through to the deterministic heuristic

    evidence_tokens: set = set()
    for e in evidence_texts:
        evidence_tokens |= _content_tokens(e)
    ungrounded: List[str] = []
    overlaps: List[float] = []
    for s in sentences:
        st = _content_tokens(s)
        if not st:
            overlaps.append(1.0)   # a stopword-only sentence makes no claim to ground
            continue
        overlap = len(st & evidence_tokens) / len(st)
        overlaps.append(overlap)
        if overlap < overlap_threshold:
            ungrounded.append(s)
    # Continuous average overlap, not a binary per-sentence bucket at the
    # threshold — a sentence that's mostly-but-not-fully grounded should
    # pull the score down proportionally, not round up to a full pass.
    score = sum(overlaps) / len(overlaps)
    return FaithfulnessScore(score=round(score, 4), ungrounded_claims=ungrounded, method="heuristic")


# ── Answer relevance ──────────────────────────────────────────────────────────
@dataclass
class AnswerRelevanceScore:
    score: float                # [0,1]
    method: str = "heuristic"    # "heuristic" | "llm"


def score_answer_relevance(query: str, answer: str,
                           ai_call: Optional[Callable[[str], str]] = None) -> AnswerRelevanceScore:
    """
    Does `answer` actually address `query`? With ai_call: one LLM-judge call
    scoring 0-1. Without (or on judge failure): deterministic token-overlap
    between query and answer — a crude but always-available proxy.
    """
    if ai_call is not None:
        try:
            prompt = (
                "Score 0.0-1.0 how directly this ANSWER addresses this QUERY "
                "(1.0 = fully addresses it, 0.0 = does not address it at all).\n\n"
                f"QUERY: {query}\nANSWER: {answer}\n\n"
                'STRICT JSON: {"score": 0.0}'
            )
            d = json.loads(_strip_json_fence(ai_call(prompt) or ""))
            return AnswerRelevanceScore(score=round(max(0.0, min(1.0, float(d.get("score", 0.0)))), 4),
                                        method="llm")
        except Exception:
            pass

    q = _content_tokens(query)
    a = _content_tokens(answer)
    if not q:
        return AnswerRelevanceScore(score=0.0, method="heuristic")
    overlap = len(q & a) / len(q)
    return AnswerRelevanceScore(score=round(min(1.0, overlap), 4), method="heuristic")
