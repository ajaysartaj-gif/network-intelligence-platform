"""
core/knowledge/rag/reranker.py
==============================
Pluggable cross-encoder re-ranking, same shape as embedder.py's Embedder.

Reciprocal Rank Fusion (in enterprise/knowledge_layer.py) combines two
independently-scored rankings, but neither arm ever jointly reads the query
and a candidate's full text together — a cross-encoder does exactly that,
scoring (query, candidate) pairs directly, which is a materially stronger
relevance signal than fusing two independent single-text scores.

Uses sentence-transformers' CrossEncoder — the SAME package already required
for embeddings, so this adds no new dependency. Reranking a top-K pool (not
the whole corpus) keeps the cost bounded: cross-encoders are too slow to run
over every candidate, only over the handful already shortlisted by fusion.

FakeReranker is deterministic and dependency-free, used by tests to verify
rerank-then-truncate wiring without downloading a model.
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

logger = logging.getLogger("NetBrain.Knowledge.RAG.Reranker")


class Reranker(ABC):
    """Scores each (query, candidate_text) pair independently and jointly —
    higher score = more relevant. Not a full ranking API: callers sort."""

    @abstractmethod
    def score(self, query: str, candidates: List[str]) -> List[float]:
        """One relevance score per candidate, same order as the input list."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Identifier (model name), surfaced in metrics/logs."""


class CrossEncoderReranker(Reranker):
    """
    sentence-transformers CrossEncoder, run locally on CPU. Free, offline,
    no API key — same dependency as LocalEmbedder.

    Default model cross-encoder/ms-marco-MiniLM-L-6-v2: small, well-proven
    for passage re-ranking, downloaded once from Hugging Face on first use
    and cached locally thereafter. Loading is lazy so importing this module
    never blocks or requires the model to be present.
    """
    DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self, model_name: Optional[str] = None):
        self._model_name = model_name or self.DEFAULT_MODEL
        self._model = None

    def _ensure_loaded(self):
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is required for cross-encoder re-ranking "
                    "(same package embeddings already use). "
                    "Install it: pip install sentence-transformers"
                ) from exc
            except Exception as exc:
                # Same torch-version failure mode documented in embedder.py's
                # LocalEmbedder._ensure_loaded — surface a fixable message
                # instead of a cryptic internal AttributeError/NameError.
                raise RuntimeError(
                    "Cross-encoder model failed to load — likely an incompatible "
                    "installed torch version (sentence-transformers requires "
                    f"torch>=2.4). Original error: {type(exc).__name__}: {exc}. "
                    "Fix: upgrade torch in this environment "
                    "(`pip install --upgrade torch`)."
                ) from exc
            logger.info(f"Loading cross-encoder re-ranker: {self._model_name}")
            self._model = CrossEncoder(self._model_name)

    def score(self, query: str, candidates: List[str]) -> List[float]:
        if not candidates:
            return []
        self._ensure_loaded()
        pairs = [(query, c) for c in candidates]
        raw = self._model.predict(pairs)
        return [float(x) for x in raw]

    @property
    def name(self) -> str:
        return self._model_name


class FakeReranker(Reranker):
    """
    Deterministic, dependency-free reranker for tests. Scores by token
    overlap between query and candidate (like the keyword arm), NOT the same
    signal as semantic/fusion score — enough to verify that reranking
    actually changes ordering versus the pre-rerank order, without a real
    cross-encoder model.
    """

    @staticmethod
    def _tokens(s: str) -> set:
        return set(re.findall(r"[a-z0-9]+", (s or "").lower()))

    def score(self, query: str, candidates: List[str]) -> List[float]:
        q = self._tokens(query)
        out = []
        for c in candidates:
            ct = self._tokens(c)
            overlap = len(q & ct)
            out.append(overlap / (len(q) or 1))
        return out

    @property
    def name(self) -> str:
        return "fake-reranker"


# ── Singleton accessor ──────────────────────────────────────────────────────
_reranker: Optional[Reranker] = None


def get_reranker() -> Reranker:
    """
    The one place that decides which re-ranking backend is used. To switch
    models, or to swap in an API-based reranker later, implement Reranker
    and return it here — no other RAG code changes.
    """
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoderReranker()
    return _reranker


def set_reranker(reranker: Reranker) -> None:
    """Override the reranker (used by tests to inject FakeReranker)."""
    global _reranker
    _reranker = reranker
