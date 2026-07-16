"""
core/knowledge/enterprise/knowledge_layer.py
============================================
Enterprise Knowledge Layer — an EXTENSION of the existing RAG engine.

It does NOT rewrite RAG. It wraps the existing RAGEngine (same ChromaDB
collection, same Embedder, same semantic search) and adds the enterprise
capabilities on top:

  • Multiple typed knowledge sources (vendor docs, RFCs, runbooks, incident
    reports, config standards, best practices, successful remediations).
  • Metadata-based retrieval (filter by source/vendor/platform/tag/version).
  • Document versioning (re-ingest creates a new version; old versions are
    retained and marked superseded; search returns latest by default).
  • Duplicate prevention (content-hash dedup — identical content is skipped).
  • Source ranking (per-source-type authority weights).
  • Confidence scoring (semantic similarity × source authority × recency).
  • Hybrid search (semantic + keyword + metadata, fused with RRF).
  • Automatic ingestion pipelines (see pipelines in this package).
  • Capability-registry surface: health(), metrics(), confidence(),
    source_statistics(), retrieval_latency().

Everything the existing system did still works; this only adds.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import deque, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.knowledge.rag.rag_engine import RAGEngine, RAGHit, get_rag_engine, _chunk_text, _chunk_hierarchical

logger = logging.getLogger("AI Net Studio.Knowledge.Enterprise")


# ── Source taxonomy + authority ranking ─────────────────────────────────────
class SourceType(str, Enum):
    CONFIG_STANDARD = "config_standard"   # your mandated standards (highest authority)
    GOLDEN_CONFIG   = "golden_config"     # known-good reference configs
    VENDOR_DOCS     = "vendor_docs"       # official vendor documentation
    YANG_MODEL      = "yang_model"        # YANG/OpenConfig schema definitions
    RFC             = "rfc"               # IETF RFCs
    RELEASE_NOTES   = "release_notes"     # vendor release/bug-fix notes
    DESIGN_GUIDE    = "design_guide"      # vendor/internal design guides
    BEST_PRACTICE   = "best_practice"     # curated best practices
    WHITEPAPER      = "whitepaper"        # vendor/industry whitepapers
    REMEDIATION     = "remediation"       # previous SUCCESSFUL remediations
    RUNBOOK         = "runbook"           # internal runbooks / procedures
    BUG_REPORT      = "bug_report"        # TAC cases / bug-database entries
    INCIDENT        = "incident"          # incident reports (symptom->resolution)
    CUSTOMER_DOC    = "customer_doc"      # customer-provided documentation
    INTERNAL_WIKI   = "internal_wiki"     # internal wiki pages


# Authority weight per source type (0..1). Higher = more authoritative when
# results tie. Tunable — this is policy, not a hardcoded truth.
SOURCE_RANK: Dict[str, float] = {
    SourceType.CONFIG_STANDARD.value: 1.00,
    SourceType.GOLDEN_CONFIG.value:   0.95,
    SourceType.VENDOR_DOCS.value:     0.90,
    SourceType.YANG_MODEL.value:      0.88,
    SourceType.RFC.value:             0.85,
    SourceType.RELEASE_NOTES.value:   0.82,
    SourceType.DESIGN_GUIDE.value:    0.80,
    SourceType.BEST_PRACTICE.value:   0.75,
    SourceType.WHITEPAPER.value:      0.70,
    SourceType.REMEDIATION.value:     0.72,
    SourceType.RUNBOOK.value:         0.65,
    SourceType.BUG_REPORT.value:      0.62,
    SourceType.INCIDENT.value:        0.60,
    SourceType.CUSTOMER_DOC.value:    0.55,
    SourceType.INTERNAL_WIKI.value:   0.55,
}
_DEFAULT_RANK = 0.50


@dataclass
class KnowledgeRecord:
    """A single unit of knowledge to ingest."""
    doc_id: str
    title: str
    content: str
    source_type: SourceType
    vendor: str = ""
    platform: str = ""
    tags: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EnterpriseHit:
    """A retrieved chunk enriched with confidence + provenance + version."""
    text: str                   # parent-level context (full section, for generation)
    confidence: float           # fused [0,1]
    semantic_score: float
    keyword_score: float
    source_type: str
    source_rank: float
    title: str
    doc_id: str
    version: int
    vendor: str
    platform: str
    tags: List[str]
    matched_snippet: str = ""   # the small child chunk that actually matched
    metadata: Dict[str, Any] = field(default_factory=dict)


def _content_hash(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


class EnterpriseKnowledgeLayer:
    """Wraps RAGEngine, adding enterprise knowledge capabilities."""

    def __init__(self, rag: Optional[RAGEngine] = None,
                 source_rank: Optional[Dict[str, float]] = None,
                 reranker: Optional[object] = None):
        self.rag = rag or get_rag_engine()
        self.source_rank = dict(SOURCE_RANK)
        if source_rank:
            self.source_rank.update(source_rank)
        self._reranker = reranker   # None => lazily use the module singleton
        # retrieval latency ring buffer (seconds)
        self._latencies: deque = deque(maxlen=200)
        self._ingest_count = 0
        self._dedup_skipped = 0
        self._rerank_failures = 0

    # internal: ensure the underlying Chroma collection is live and return it
    def _col(self):
        self.rag._ensure()
        return self.rag._col

    # ── INGEST with versioning + dedup ───────────────────────────────────────
    def ingest(self, record: KnowledgeRecord) -> Dict[str, Any]:
        """
        Versioned, deduplicated ingest. Returns a summary dict.

        - Dedup: if the latest stored version of this doc_id has identical
          content, skip (no new version).
        - Versioning: different content => version = latest+1; prior versions
          are retained but marked superseded=true so default search returns
          only the latest.
        """
        col = self._col()
        src = record.source_type.value if isinstance(record.source_type, SourceType) else str(record.source_type)
        chash = _content_hash(record.content)

        # Find existing versions of this doc_id.
        try:
            existing = col.get(where={"doc_id": record.doc_id}, include=["metadatas"])
            metas = existing.get("metadatas", []) or []
        except Exception:
            metas = []

        latest_ver = 0
        latest_hash = None
        for m in metas:
            v = int(m.get("version", 1))
            if v > latest_ver:
                latest_ver = v
                latest_hash = m.get("content_hash")

        # Dedup: identical content as the current latest => skip.
        if latest_hash == chash and latest_ver > 0:
            self._dedup_skipped += 1
            return {"doc_id": record.doc_id, "skipped": True, "reason": "duplicate content",
                    "version": latest_ver}

        new_ver = latest_ver + 1

        # Mark previous latest version chunks as superseded (retain history).
        if latest_ver > 0:
            try:
                old = col.get(where={"doc_id": record.doc_id},
                              include=["metadatas"])
                old_ids = old.get("ids", []) or []
                old_metas = old.get("metadatas", []) or []
                if old_ids:
                    # Write back CLEAN primitive metadata with superseded=True so
                    # the flag reliably persists (Chroma rejects/!persists non-
                    # primitive values; rebuild each dict explicitly).
                    fixed = []
                    for mm in old_metas:
                        nm = {k: v for k, v in (mm or {}).items()
                              if isinstance(v, (str, int, float, bool))}
                        nm["superseded"] = True
                        fixed.append(nm)
                    col.update(ids=old_ids, metadatas=fixed)
            except Exception as exc:
                logger.debug(f"version-supersede update failed: {exc}")

        # Chunk + embed + upsert new version (parent-child hierarchical: small
        # child chunks embedded for precise matching, larger parent sections
        # stored as the retrievable document for full generation context).
        pairs = _chunk_hierarchical(record.content)
        if not pairs:
            return {"doc_id": record.doc_id, "skipped": True, "reason": "empty content"}
        children = [c for c, _ in pairs]
        parents = [p for _, p in pairs]
        ids = [f"{record.doc_id}::v{new_ver}::chunk{i}" for i in range(len(pairs))]
        embeddings = self.rag.embedder.embed([f"{record.title}\n{c}" for c in children])
        now = time.time()
        metadatas = [{
            "doc_id": record.doc_id, "title": record.title or record.doc_id,
            "vendor": (record.vendor or "").lower(), "platform": (record.platform or "").lower(),
            "source": src, "source_type": src,
            "chunk": i, "version": new_ver, "content_hash": chash,
            "superseded": False, "ingested_at": now,
            "tags": ",".join(record.tags), "matched_snippet": children[i],
            **{k: str(v) for k, v in (record.extra or {}).items()},
        } for i in range(len(pairs))]
        col.upsert(ids=ids, embeddings=embeddings, documents=parents, metadatas=metadatas)
        self._ingest_count += 1
        return {"doc_id": record.doc_id, "skipped": False, "version": new_ver,
                "chunks": len(pairs), "source_type": src}

    # ── CONFIDENCE scoring ───────────────────────────────────────────────────
    def _recency_factor(self, ingested_at: float) -> float:
        # Decays from 1.0 (fresh) toward ~0.5 over ~365 days. Never below 0.4.
        if not ingested_at:
            return 0.6
        age_days = max(0.0, (time.time() - float(ingested_at)) / 86400.0)
        return max(0.4, 1.0 - min(age_days / 365.0, 1.0) * 0.5)

    def confidence(self, semantic_score: float, source_type: str,
                   ingested_at: float = 0.0) -> float:
        """
        Blend semantic similarity, source authority and recency into one
        confidence value in [0,1]. Exposed for the capability registry.
        """
        rank = self.source_rank.get(source_type, _DEFAULT_RANK)
        rec = self._recency_factor(ingested_at)
        score = 0.60 * max(0.0, min(1.0, semantic_score)) + 0.25 * rank + 0.15 * rec
        return round(max(0.0, min(1.0, score)), 4)

    # ── HYBRID search: semantic + keyword + metadata, fused with RRF, ─────────
    # then cross-encoder re-ranked
    def search(
        self,
        query: str,
        top_k: int = 5,
        source_types: Optional[List[str]] = None,
        vendor: Optional[str] = None,
        platform: Optional[str] = None,
        tags: Optional[List[str]] = None,
        include_superseded: bool = False,
        mode: str = "hybrid",        # "hybrid" | "semantic" | "keyword"
        candidate_pool: int = 40,
        rerank: bool = True,
        rerank_pool: int = 20,
        doc_ids: Optional[List[str]] = None,
    ) -> List[EnterpriseHit]:
        t0 = time.time()
        try:
            hits = self._search_impl(query, top_k, source_types, vendor, platform,
                                     tags, include_superseded, mode, candidate_pool,
                                     rerank, rerank_pool, doc_ids)
            return hits
        finally:
            self._latencies.append(time.time() - t0)

    # ── Multi-hop: decompose a compound question, search each hop, merge ────
    def multi_hop_search(self, query: str, ai_call: Optional[Callable[[str], str]] = None,
                         top_k: int = 5, per_hop_k: int = 5, **search_kwargs) -> List[EnterpriseHit]:
        """
        Decompose `query` into independent sub-queries (or treat it as one
        hop, if decomposition is unavailable or the question isn't actually
        compound — see query_planning.decompose_query), search() each
        separately, then merge — deduped by (doc_id, chunk), keeping each
        hit's HIGHEST confidence across whichever hop surfaced it — and
        re-sort by that confidence. A single embedding search treats a
        compound question as one vector, where the two sub-questions
        compete for the same top-k slots; this gives each its own pass.
        """
        from core.knowledge.rag.query_planning import decompose_query
        subqueries = decompose_query(query, ai_call=ai_call)
        merged: Dict[str, EnterpriseHit] = {}
        for sq in subqueries:
            for hit in self.search(sq, top_k=per_hop_k, **search_kwargs):
                key = f"{hit.doc_id}::{hit.metadata.get('chunk', '')}"
                if key not in merged or hit.confidence > merged[key].confidence:
                    merged[key] = hit
        ordered = sorted(merged.values(), key=lambda h: h.confidence, reverse=True)
        return ordered[:top_k]

    # ── Hierarchical: coarse document-level pass, then a focused fine pass ──
    def coarse_to_fine_search(self, query: str, top_k: int = 5,
                              coarse_doc_limit: int = 5, **search_kwargs) -> List[EnterpriseHit]:
        """
        Two-stage retrieval: a broad first pass identifies which DOCUMENTS
        are relevant at all, then a second, focused pass searches ONLY
        within those documents. Once a corpus spans many large documents, a
        flat single-pass search makes a several-hundred-page vendor doc
        compete chunk-for-chunk against every other document on every
        query; narrowing to candidate documents first is both cheaper and
        more precise for the final ranking.

        The coarse pass keeps re-ranking on (default): re-ranking is what
        makes document-level ordering reliable in the first place, so
        disabling it here to save time would sacrifice exactly the accuracy
        this stage exists to get right. The savings versus one flat search
        come from restricting the FINE pass to fewer documents, not from
        skipping quality in the pass that picks them.
        """
        coarse_hits = self.search(query, top_k=coarse_doc_limit * 3, **search_kwargs)
        candidate_doc_ids: List[str] = []
        seen: set = set()
        for h in coarse_hits:
            if h.doc_id and h.doc_id not in seen:
                seen.add(h.doc_id)
                candidate_doc_ids.append(h.doc_id)
            if len(candidate_doc_ids) >= coarse_doc_limit:
                break
        if not candidate_doc_ids:
            return []
        return self.search(query, top_k=top_k, doc_ids=candidate_doc_ids, **search_kwargs)

    def _rerank(self, query: str, hits: List[EnterpriseHit], rerank_pool: int) -> List[EnterpriseHit]:
        """Re-score the top `rerank_pool` fused hits with a cross-encoder,
        against each hit's precise matched_snippet (not the larger parent
        text — cross-encoders have limited context, and the snippet is the
        actual match target). Falls back to the existing RRF/confidence
        ordering unchanged if the reranker is unavailable — everything the
        fusion step already did still works; this only adds a stronger
        re-ordering on top when it can."""
        if not hits:
            return hits
        pool = hits[:rerank_pool]
        rest = hits[rerank_pool:]
        try:
            reranker = self._reranker
            if reranker is None:
                from core.knowledge.rag.reranker import get_reranker
                reranker = get_reranker()
            texts = [h.matched_snippet or h.text for h in pool]
            scores = reranker.score(query, texts)
        except Exception as exc:
            self._rerank_failures += 1
            logger.info(f"Re-ranking unavailable ({exc}); keeping fusion order.")
            return hits
        for h, s in zip(pool, scores):
            h.metadata["_rerank_score"] = round(float(s), 5)
        pool.sort(key=lambda h: h.metadata.get("_rerank_score", 0.0), reverse=True)
        return pool + rest

    def _where(self, source_types, vendor, platform, include_superseded, doc_ids=None) -> Dict[str, Any]:
        clauses = []
        if not include_superseded:
            clauses.append({"superseded": False})
        if vendor:
            clauses.append({"vendor": vendor.lower()})
        if platform:
            clauses.append({"platform": platform.lower()})
        if source_types:
            clauses.append({"source_type": {"$in": list(source_types)}})
        if doc_ids:
            clauses.append({"doc_id": {"$in": list(doc_ids)}})
        if not clauses:
            return {}
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

    def _search_impl(self, query, top_k, source_types, vendor, platform,
                     tags, include_superseded, mode, candidate_pool,
                     rerank=True, rerank_pool=20, doc_ids=None):
        col = self._col()
        if col.count() == 0:
            return []
        where = self._where(source_types, vendor, platform, include_superseded, doc_ids)
        q_tokens = set(_tokens(query))

        # ── Semantic arm (reuses the existing embedder + Chroma cosine) ──
        sem_ranked: List[Tuple[str, float, str, Dict]] = []  # (id, score, doc, meta)
        if mode in ("hybrid", "semantic"):
            q_emb = self.rag.embedder.embed_one(query)
            res = col.query(query_embeddings=[q_emb], n_results=candidate_pool,
                            where=where or None,
                            include=["documents", "metadatas", "distances"])
            ids = (res.get("ids") or [[]])[0]
            docs = (res.get("documents") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            dists = (res.get("distances") or [[]])[0]
            for i, d, m, dist in zip(ids, docs, metas, dists):
                sem_ranked.append((i, 1.0 - float(dist), d, m or {}))

        # ── Keyword arm (BM25-lite token overlap over a metadata-filtered pool) ──
        kw_ranked: List[Tuple[str, float, str, Dict]] = []
        if mode in ("hybrid", "keyword"):
            pool = col.get(where=where or None, include=["documents", "metadatas"],
                           limit=max(candidate_pool * 4, 200))
            pids = pool.get("ids", []) or []
            pdocs = pool.get("documents", []) or []
            pmetas = pool.get("metadatas", []) or []
            scored = []
            for i, d, m in zip(pids, pdocs, pmetas):
                dt = set(_tokens(d)) | set(_tokens((m or {}).get("title", "")))
                if not dt:
                    continue
                overlap = len(q_tokens & dt)
                if overlap:
                    # length-normalized overlap
                    scored.append((i, overlap / (len(q_tokens) or 1), d, m or {}))
            scored.sort(key=lambda x: x[1], reverse=True)
            kw_ranked = scored[:candidate_pool]

        # Optional tag filter (post-filter, since tags are stored as CSV string)
        def _tag_ok(meta) -> bool:
            if not tags:
                return True
            have = set((meta.get("tags", "") or "").split(","))
            return all(t in have for t in tags)

        # ── Reciprocal Rank Fusion across the two arms ──
        K = 60.0
        fused: Dict[str, Dict[str, Any]] = {}
        for rank, (i, sc, d, m) in enumerate(sem_ranked):
            if not _tag_ok(m):
                continue
            fused.setdefault(i, {"doc": d, "meta": m, "rrf": 0.0, "sem": 0.0, "kw": 0.0})
            fused[i]["rrf"] += 1.0 / (K + rank)
            fused[i]["sem"] = sc
        for rank, (i, sc, d, m) in enumerate(kw_ranked):
            if not _tag_ok(m):
                continue
            fused.setdefault(i, {"doc": d, "meta": m, "rrf": 0.0, "sem": 0.0, "kw": 0.0})
            fused[i]["rrf"] += 1.0 / (K + rank)
            fused[i]["kw"] = sc

        # ── Build hits with confidence (RRF fuses ranking; confidence scores
        #    authority/recency/semantic for the operator) ──
        hits: List[EnterpriseHit] = []
        for i, f in fused.items():
            m = f["meta"]
            stype = m.get("source_type", m.get("source", "rag"))
            conf = self.confidence(f["sem"], stype, float(m.get("ingested_at", 0) or 0))
            hits.append(EnterpriseHit(
                text=f["doc"], confidence=conf,
                semantic_score=round(f["sem"], 4), keyword_score=round(f["kw"], 4),
                source_type=stype, source_rank=self.source_rank.get(stype, _DEFAULT_RANK),
                title=m.get("title", ""), doc_id=m.get("doc_id", ""),
                version=int(m.get("version", 1)),
                vendor=m.get("vendor", ""), platform=m.get("platform", ""),
                tags=[t for t in (m.get("tags", "") or "").split(",") if t],
                matched_snippet=m.get("matched_snippet", ""),
                metadata={**m, "_rrf": round(f["rrf"], 5)},
            ))

        # Final ordering: fused RRF first, then confidence (source authority +
        # recency) as the tie-breaker so the most authoritative wins ties.
        hits.sort(key=lambda h: (h.metadata.get("_rrf", 0), h.confidence), reverse=True)
        if rerank:
            hits = self._rerank(query, hits, rerank_pool)
        return hits[:top_k]

    # ── Capability-registry surface ──────────────────────────────────────────
    def health(self) -> Dict[str, Any]:
        try:
            col = self._col()
            n = col.count()
            status = "active" if n > 0 else "partial"
            detail = (f"{n} chunks across {len(self.source_statistics().get('by_source', {}))} "
                      f"source types" if n else "Knowledge layer ready; no documents ingested yet")
            return {"status": status, "detail": detail, "chunks": n}
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}

    def metrics(self) -> Dict[str, Any]:
        lat = self.retrieval_latency()
        return {
            "total_chunks": self._safe_count(),
            "ingested_docs_session": self._ingest_count,
            "dedup_skipped_session": self._dedup_skipped,
            "embedder": self.rag.embedder.name,
            "source_statistics": self.source_statistics(),
            "retrieval_latency_ms": lat,
        }

    def source_statistics(self) -> Dict[str, Any]:
        """Counts per source type + version spread + latest ingest times."""
        out = {"by_source": {}, "versions": {}, "latest_ingest": {}}
        try:
            col = self._col()
            data = col.get(include=["metadatas"], limit=100000)
            for m in (data.get("metadatas", []) or []):
                s = m.get("source_type", m.get("source", "unknown"))
                out["by_source"][s] = out["by_source"].get(s, 0) + 1
                doc = m.get("doc_id", "")
                v = int(m.get("version", 1))
                out["versions"][doc] = max(out["versions"].get(doc, 0), v)
                ts = float(m.get("ingested_at", 0) or 0)
                if ts and ts > out["latest_ingest"].get(s, 0):
                    out["latest_ingest"][s] = ts
        except Exception as exc:
            out["error"] = str(exc)
        out["distinct_documents"] = len(out["versions"])
        return out

    def retrieval_latency(self) -> Dict[str, float]:
        if not self._latencies:
            return {"count": 0, "avg_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0}
        vals = sorted(self._latencies)
        def pct(p):
            idx = min(len(vals) - 1, int(p * len(vals)))
            return round(vals[idx] * 1000, 2)
        return {
            "count": len(vals),
            "avg_ms": round(sum(vals) / len(vals) * 1000, 2),
            "p50_ms": pct(0.50), "p95_ms": pct(0.95),
        }

    def _safe_count(self) -> int:
        try:
            return self._col().count()
        except Exception:
            return 0


# ── Singleton ───────────────────────────────────────────────────────────────
_layer: Optional[EnterpriseKnowledgeLayer] = None


def get_knowledge_layer() -> EnterpriseKnowledgeLayer:
    global _layer
    if _layer is None:
        _layer = EnterpriseKnowledgeLayer()
    return _layer
