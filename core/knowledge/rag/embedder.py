"""
core/knowledge/rag/embedder.py
==============================
Pluggable embedding layer for the RAG engine.

Everything that turns text into vectors goes through the Embedder
interface, so the embedding backend is a swappable implementation detail.
Today we run LocalEmbedder (sentence-transformers, free + offline) because
the configured LLM provider (Groq) has no embeddings endpoint. If an
embeddings API is adopted later (OpenAI, Voyage, etc.), add one class that
implements the same interface and change a single line in get_embedder() —
no other RAG code changes.

FakeEmbedder is deterministic and dependency-free, used by tests to verify
the ingest→store→retrieve pipeline without downloading a model.
"""
from __future__ import annotations

import os
import hashlib
import logging
import math
from abc import ABC, abstractmethod
from typing import List, Optional

logger = logging.getLogger("NetBrain.Knowledge.RAG.Embedder")


class Embedder(ABC):
    """Turns text into fixed-length unit vectors (cosine-ready)."""

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts. Returns one vector per input text."""

    def embed_one(self, text: str) -> List[float]:
        return self.embed([text])[0]

    @property
    @abstractmethod
    def dim(self) -> int:
        """Vector dimensionality."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Identifier (model name) — also tags the vector store so a store
        built with one embedder isn't silently queried with another."""


class LocalEmbedder(Embedder):
    """
    sentence-transformers, run locally on CPU. Free, offline, no API key.

    Default model BAAI/bge-small-en-v1.5: ~130MB, 384-dim, strong on
    technical/IR text. The model is downloaded once from Hugging Face on
    first use and cached locally thereafter. Loading is lazy so importing
    this module never blocks or requires the model to be present.
    """
    DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

    def __init__(self, model_name: Optional[str] = None):
        self._model_name = (
            model_name
            or os.environ.get("NETBRAIN_RAG_EMBED_MODEL")
            or self.DEFAULT_MODEL
        )
        self._model = None
        self._dim: Optional[int] = None

    def _ensure_loaded(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is required for local embeddings. "
                    "Install it: pip install sentence-transformers"
                ) from exc
            logger.info(f"Loading local embedding model: {self._model_name}")
            self._model = SentenceTransformer(self._model_name)
            self._dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        self._ensure_loaded()
        # normalize_embeddings=True -> unit vectors, so cosine distance in the
        # vector store is a clean similarity measure.
        vecs = self._model.encode(
            texts, normalize_embeddings=True, convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vecs.tolist()

    @property
    def dim(self) -> int:
        self._ensure_loaded()
        return self._dim or 0

    @property
    def name(self) -> str:
        return self._model_name


class FakeEmbedder(Embedder):
    """
    Deterministic, dependency-free embedder for tests. Builds a normalized
    bag-of-words vector by hashing tokens into a fixed-dim space, so texts
    that share vocabulary land closer in cosine space — enough to verify
    retrieval ordering without a real model.
    """
    def __init__(self, dim: int = 96):
        self._dim = dim

    def embed(self, texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for t in texts:
            vec = [0.0] * self._dim
            for tok in (t or "").lower().split():
                h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
                vec[h % self._dim] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return f"fake-{self._dim}"


# ── Singleton accessor ──────────────────────────────────────────────────────
_embedder: Optional[Embedder] = None


def get_embedder() -> Embedder:
    """
    The one place that decides which embedding backend RAG uses. To switch
    to an API embedder later, implement Embedder and return it here.
    """
    global _embedder
    if _embedder is None:
        _embedder = LocalEmbedder()
    return _embedder


def set_embedder(embedder: Embedder) -> None:
    """Override the embedder (used by tests to inject FakeEmbedder)."""
    global _embedder
    _embedder = embedder
