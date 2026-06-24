"""
core/knowledge/rag/rag_engine.py
================================
The real RAG engine: ingest knowledge → chunk → embed → persist in
ChromaDB, then retrieve by SEMANTIC similarity (not keyword overlap).

This replaces the previous keyword-overlap "RAG" (which scored matches by
counting shared tokens, so "OSPF stuck in EXSTART" couldn't find a runbook
titled "adjacency fails at exchange state" — no words in common). With
embeddings, those map to nearby vectors and retrieve correctly.

Two ingestion entry points, matching the two knowledge sources the
operator chose to load (phased):
  - ingest_document(): vendor docs, runbooks, design guides.
  - ingest_incident(): past incidents / resolved configs (symptom →
    resolution), so prior fixes surface for similar new problems.

Storage is a local, persistent ChromaDB collection (cosine space). The
embedding backend is whatever core.knowledge.rag.embedder.get_embedder()
returns (local sentence-transformers today; swappable to an API later).
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.knowledge.rag.embedder import Embedder, get_embedder

logger = logging.getLogger("NetBrain.Knowledge.RAG.Engine")

_DEFAULT_PERSIST_DIR = os.environ.get(
    "NETBRAIN_RAG_DIR", ".netbrain_rag_chroma"
)
_DEFAULT_COLLECTION = "netbrain_knowledge"


@dataclass
class RAGHit:
    """One retrieved chunk with its relevance score and provenance."""
    text: str
    score: float                     # cosine similarity in [0, 1]; higher = closer
    source: str = "rag"              # 'runbook' | 'incident' | 'vendor_doc' | ...
    title: str = ""
    doc_id: str = ""
    vendor: str = ""
    platform: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


def _chunk_text(text: str, target_chars: int = 900, overlap: int = 150) -> List[str]:
    """
    Split text into overlapping chunks on paragraph/sentence boundaries
    where possible, so a retrieved chunk reads as a coherent unit rather
    than a mid-sentence fragment. Overlap preserves context that would
    otherwise be cut at a boundary.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= target_chars:
        return [text]

    # Prefer paragraph boundaries, then sentence boundaries.
    paras = re.split(r"\n\s*\n", text)
    units: List[str] = []
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if len(p) <= target_chars:
            units.append(p)
        else:
            # Break an over-long paragraph on sentence ends.
            sentences = re.split(r"(?<=[.!?])\s+", p)
            buf = ""
            for s in sentences:
                if len(buf) + len(s) + 1 <= target_chars:
                    buf = f"{buf} {s}".strip()
                else:
                    if buf:
                        units.append(buf)
                    buf = s
            if buf:
                units.append(buf)

    # Greedily pack units into chunks near target size, with overlap tail.
    chunks: List[str] = []
    buf = ""
    for u in units:
        if len(buf) + len(u) + 1 <= target_chars:
            buf = f"{buf}\n{u}".strip()
        else:
            if buf:
                chunks.append(buf)
            # carry an overlap tail from the previous chunk for continuity
            tail = buf[-overlap:] if overlap and buf else ""
            buf = f"{tail}\n{u}".strip() if tail else u
    if buf:
        chunks.append(buf)
    return chunks


class RAGEngine:
    """Semantic retrieval over a persistent ChromaDB collection."""

    def __init__(
        self,
        embedder: Optional[Embedder] = None,
        persist_dir: str = _DEFAULT_PERSIST_DIR,
        collection_name: str = _DEFAULT_COLLECTION,
    ):
        self.embedder = embedder or get_embedder()
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self._client = None
        self._col = None

    # ── lazy Chroma init (so importing/constructing never blocks) ────────────
    def _ensure(self):
        if self._col is not None:
            return
        import chromadb
        self._client = chromadb.PersistentClient(path=self.persist_dir)
        # cosine space + tag the collection with the embedder name so a store
        # built with one model isn't silently queried with a different one.
        self._col = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine", "embedder": self.embedder.name},
        )

    # ── ingestion ────────────────────────────────────────────────────────────
    def ingest_document(
        self,
        doc_id: str,
        title: str,
        content: str,
        vendor: str = "",
        platform: str = "",
        source: str = "runbook",
        extra: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Chunk, embed, and upsert a document. Re-ingesting the same doc_id
        overwrites its chunks (idempotent), so re-running ingestion refreshes
        rather than duplicates. Returns the number of chunks stored.
        """
        self._ensure()
        chunks = _chunk_text(content)
        if not chunks:
            return 0

        # Remove any prior chunks for this doc_id first (handles shrinking docs).
        try:
            self._col.delete(where={"doc_id": doc_id})
        except Exception:
            pass

        ids = [f"{doc_id}::chunk{i}" for i in range(len(chunks))]
        # Embed title+chunk together so the heading's terms inform the vector.
        embeddings = self.embedder.embed([f"{title}\n{c}" for c in chunks])
        metadatas = [
            {
                "doc_id": doc_id, "title": title or doc_id,
                "vendor": (vendor or "").lower(), "platform": (platform or "").lower(),
                "source": source, "chunk": i,
                **{k: str(v) for k, v in (extra or {}).items()},
            }
            for i in range(len(chunks))
        ]
        self._col.upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)
        logger.info(f"Ingested doc '{doc_id}' ({source}) — {len(chunks)} chunk(s)")
        return len(chunks)

    def ingest_incident(
        self,
        incident_id: str,
        symptom: str,
        resolution: str,
        vendor: str = "",
        platform: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Store a past incident as symptom → resolution. The symptom drives
        retrieval (a new problem phrased differently still matches), and the
        resolution is what gets surfaced to help fix it.
        """
        title = f"Incident: {(symptom or '').strip()[:80]}"
        body = f"Symptom:\n{symptom}\n\nResolution:\n{resolution}"
        return self.ingest_document(
            incident_id, title, body, vendor=vendor, platform=platform,
            source="incident", extra=extra,
        )

    # ── retrieval ────────────────────────────────────────────────────────────
    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
        vendor: Optional[str] = None,
        source: Optional[str] = None,
    ) -> List[RAGHit]:
        """
        Semantic search. Returns hits sorted best-first, filtered to those at
        or above min_score (cosine similarity). Optional vendor/source filters
        narrow the search.
        """
        query = (query or "").strip()
        if not query:
            return []
        self._ensure()
        if self._col.count() == 0:
            return []

        where: Dict[str, Any] = {}
        if vendor:
            where["vendor"] = vendor.lower()
        if source:
            where["source"] = source

        q_emb = self.embedder.embed_one(query)
        res = self._col.query(
            query_embeddings=[q_emb],
            n_results=max(1, top_k),
            where=where or None,
        )

        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]

        hits: List[RAGHit] = []
        for doc, meta, dist in zip(docs, metas, dists):
            meta = meta or {}
            score = 1.0 - float(dist)   # cosine distance -> similarity
            if score < min_score:
                continue
            hits.append(RAGHit(
                text=doc, score=score,
                source=meta.get("source", "rag"),
                title=meta.get("title", ""),
                doc_id=meta.get("doc_id", ""),
                vendor=meta.get("vendor", ""),
                platform=meta.get("platform", ""),
                metadata=meta,
            ))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits

    # ── admin ────────────────────────────────────────────────────────────────
    def count(self) -> int:
        self._ensure()
        return self._col.count()

    def reset(self) -> None:
        """Drop and recreate the collection (clears all ingested knowledge)."""
        self._ensure()
        name = self.collection_name
        try:
            self._client.delete_collection(name)
        except Exception:
            pass
        self._col = self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine", "embedder": self.embedder.name},
        )

    def stats(self) -> Dict[str, Any]:
        self._ensure()
        return {
            "chunks": self._col.count(),
            "embedder": self.embedder.name,
            "persist_dir": self.persist_dir,
            "collection": self.collection_name,
        }


# ── singleton accessor ──────────────────────────────────────────────────────
_engine: Optional[RAGEngine] = None


def get_rag_engine() -> RAGEngine:
    global _engine
    if _engine is None:
        _engine = RAGEngine()
    return _engine
