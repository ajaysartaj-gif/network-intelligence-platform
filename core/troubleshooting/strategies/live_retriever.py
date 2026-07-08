"""
LiveRAGRetriever — points knowledge/rag_engine.py's KnowledgeEngine at the
platform's real semantic RAG (core.knowledge.rag) instead of the hand-rolled
keyword-overlap LexicalRetriever the dead pipeline was built and tested with.

FallbackRetriever wraps both: try the live index first (production default),
fall back to the offline lexical retriever over the curated corpus/ files if
the live store has no hits yet (not ingested), or if its dependencies
(chromadb / sentence-transformers) aren't installed in a given environment.
This keeps the existing offline test suite (tests/test_mismatch_ospf.py etc.)
working unmodified while making the live index the real production path.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from knowledge.rag_engine import Chunk, Retriever

logger = logging.getLogger(__name__)


class LiveRAGRetriever(Retriever):
    """Adapts core.knowledge.rag's embeddings-based RAGEngine to the
    knowledge/rag_engine.py Retriever interface. No retrieval logic of its own —
    it only reshapes RAGHit -> Chunk."""

    def __init__(self):
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from core.knowledge.rag import get_rag_engine
            self._engine = get_rag_engine()
        return self._engine

    def retrieve(self, query: str, k: int = 6) -> List[Chunk]:
        try:
            hits = self._get_engine().search(query, top_k=k)
        except Exception as exc:  # chromadb/embedding deps missing, store locked, etc.
            logger.info("Live RAG retrieval unavailable (%s); caller should fall back.", exc)
            return []
        return [
            Chunk(
                doc=h.doc_id or h.title or "rag",
                section=str(h.metadata.get("chunk", "")),
                text=h.text,
                rel=h.metadata.get("rel", ""),
            )
            for h in hits
        ]


class FallbackRetriever(Retriever):
    """Try `primary`; if it returns nothing, try `secondary`. Either seam is
    swappable independently (this is what makes the live-vs-offline choice a
    config change, not a code change)."""

    def __init__(self, primary: Retriever, secondary: Retriever):
        self.primary = primary
        self.secondary = secondary

    def retrieve(self, query: str, k: int = 6) -> List[Chunk]:
        chunks = self.primary.retrieve(query, k)
        if chunks:
            return chunks
        return self.secondary.retrieve(query, k)


def ensure_corpus_ingested(corpus_dir: str, relationship_types: Optional[List[str]] = None) -> int:
    """Idempotently loads corpus/*.txt into the live RAG index (via the same
    RAGEngine.ingest_document used by rag_ingest.py), tagged with the
    relationship_type each file documents so LiveRAGRetriever's scoped filter
    works. Safe to call on every request: ingest_document upserts by doc_id, so
    re-ingesting an unchanged file is a cheap no-op, not a duplicate.

    Returns the number of files ingested this call (0 if the live RAG isn't
    available in this environment — callers should treat that as "use the
    offline fallback" rather than an error).
    """
    try:
        from core.knowledge.rag import get_rag_engine
        from knowledge.corpus_loader import load_corpus
    except Exception as exc:
        logger.info("Live RAG not available for corpus ingestion (%s).", exc)
        return 0
    try:
        chunks = load_corpus(corpus_dir)
    except Exception as exc:
        logger.warning("Could not load corpus at %s: %s", corpus_dir, exc)
        return 0

    eng = get_rag_engine()
    by_doc = {}
    for c in chunks:
        by_doc.setdefault(c.doc, []).append(c)

    ingested = 0
    for doc_id, doc_chunks in by_doc.items():
        rel = next((c.rel for c in doc_chunks if c.rel), "")
        if relationship_types and rel and rel not in relationship_types:
            continue
        text = "\n\n".join(c.text for c in doc_chunks)
        try:
            eng.ingest_document(
                doc_id=doc_id, title=doc_id, content=text,
                source="knowledge_package_corpus", extra={"rel": rel} if rel else None,
            )
            ingested += 1
        except Exception as exc:
            logger.warning("Corpus ingestion failed for %s: %s", doc_id, exc)
    return ingested
