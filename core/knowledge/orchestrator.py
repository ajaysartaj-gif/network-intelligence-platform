"""
core/knowledge/orchestrator.py
==============================
The central knowledge orchestrator.

Lookup priority (highest to lowest):
  1. Local SQLite cache         → instant, if fresh
  2. RAG (PRIMARY)              → semantic retrieval over ingested runbooks
                                   and past incidents (local, offline)
  3. Vendor web fetcher          → web-scrape vendor docs (Cisco, Juniper, etc.)
  4. MCP sources (fallback)      → official vendor MCPs (e.g. Cisco DevNet)
  5. Stale cache                 → if RAG + web + MCP all miss
  6. UNVERIFIED                  → AI guess, with warning badge

RAG is primary over MCP per the operator's requirement: curated local
knowledge is consulted first; only a weak semantic match (below the score
cutoff) falls through to live web/MCP sources.
"""
from __future__ import annotations

import concurrent.futures
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.knowledge.base import (
    Citation,
    ConfidenceLevel,
    KnowledgeEntry,
    detect_vendor,
    detect_platform,
)
from core.knowledge.cache.cache_db import get_cache
from core.knowledge.cache.ttl_policy import get_ttl
from core.knowledge.vendor_router import get_fetcher, supported_vendors

logger = logging.getLogger("NetBrain.Knowledge.Orchestrator")

# ── MCP layer (optional — falls back if package missing) ─────────────────────
try:
    from core.knowledge.mcp import get_mcp_sources_for_vendor
    MCP_AVAILABLE = True
except ImportError as _mi:
    logger.warning(f"MCP layer unavailable: {_mi}")
    MCP_AVAILABLE = False

# ── RAG layer (optional — primary source, falls back if package missing) ─────
try:
    from core.knowledge.rag import get_rag_engine, RAGHit
    RAG_AVAILABLE = True
except ImportError as _ri:
    logger.warning(f"RAG layer unavailable: {_ri}")
    RAG_AVAILABLE = False

# Minimum cosine similarity for a RAG hit to be trusted over web/MCP. Below
# this, the local match is too weak and we fall through to live sources.
# Tunable via env because the cutoff depends on the embedding model.
import os
_RAG_MIN_SCORE = float(os.environ.get("NETBRAIN_RAG_MIN_SCORE", "0.45"))


# ═══════════════════════════════════════════════════════════════════════════════
# KnowledgeOrchestrator
# ═══════════════════════════════════════════════════════════════════════════════

class KnowledgeOrchestrator:
    """Cache-first knowledge lookup with web-fetch then MCP fallback."""

    def __init__(
        self,
        enable_web_fetch: bool = True,
        enable_mcp:       bool = True,
        enable_rag:       bool = True,
    ):
        self.cache = get_cache()
        self.enable_web_fetch = enable_web_fetch
        self.enable_mcp = enable_mcp and MCP_AVAILABLE
        self.enable_rag = enable_rag and RAG_AVAILABLE

    # ── Single lookup ─────────────────────────────────────────────────────────

    def lookup(
        self,
        vendor: str,
        command: str,
        platform: Optional[str] = None,
    ) -> KnowledgeEntry:
        """
        Look up one command. ALWAYS returns a KnowledgeEntry (never None) —
        if nothing's found, returns an UNVERIFIED entry so the operator
        sees the AI guess with a warning.
        """
        vendor = (vendor or "").lower().strip()
        command = (command or "").strip()
        platform = (platform or "").lower().strip()

        if not vendor or not command:
            return KnowledgeEntry.unverified(vendor, command, "Missing vendor or command")

        # ── 1. Cache lookup ───────────────────────────────────────────────────
        cached = self.cache.get(vendor, command, platform)
        if cached and not cached.is_stale():
            cached.citation.confidence = ConfidenceLevel.MEDIUM
            cached.citation.notes = (
                f"Cached {cached.age_days()} day(s) ago · originally from {cached.citation.source_name}"
            )
            logger.debug(f"Cache HIT: {vendor}/{command}")
            return cached

        # ── 2. RAG (PRIMARY — curated local knowledge: runbooks/incidents) ──
        # Semantic retrieval over ingested knowledge runs BEFORE web/MCP, per
        # the requirement that RAG be primary over MCP. Only a sufficiently
        # strong match (>= _RAG_MIN_SCORE) is trusted; a weak local match
        # falls through to live sources rather than returning something stale.
        if self.enable_rag:
            rag_entry = self._rag_lookup(vendor, command, platform)
            if rag_entry:
                logger.info(f"RAG HIT (primary): {vendor}/{command}")
                return rag_entry
            logger.debug(f"RAG below threshold for {vendor}/{command}, falling through")

        # ── 3. Web fetcher ───────────────────────────────────────────────────
        if self.enable_web_fetch:
            fetched = self._web_fetch(vendor, command, platform)
            if fetched:
                self.cache.upsert(fetched)
                logger.info(
                    f"Web FETCH OK: {vendor}/{command} from {fetched.citation.source_url}"
                )
                return fetched
            logger.debug(f"Web fetcher returned nothing for {vendor}/{command}")

        # ── 4. MCP sources (FALLBACK — only after RAG and fetcher) ───────────
        if self.enable_mcp:
            mcp_entry = self._mcp_lookup(vendor, command, platform)
            if mcp_entry:
                self.cache.upsert(mcp_entry)
                logger.info(
                    f"MCP FETCH OK: {vendor}/{command} via {mcp_entry.citation.source_name}"
                )
                return mcp_entry
            logger.debug(f"MCP returned nothing for {vendor}/{command}")

        # ── 4. Stale cache fallback ──────────────────────────────────────────
        if cached:
            cached.citation.confidence = ConfidenceLevel.LOW
            cached.citation.notes = (
                f"Stale cache ({cached.age_days()} days old, TTL {cached.ttl_days}d) — "
                "could not refresh from web or MCP"
            )
            logger.debug(f"Stale cache served: {vendor}/{command}")
            return cached

        # ── 5. Unverified ────────────────────────────────────────────────────
        logger.debug(f"No knowledge found: {vendor}/{command}")
        return KnowledgeEntry.unverified(
            vendor, command,
            f"No cache, no web fetch, no MCP coverage for {vendor}",
        )

    # ── Batch lookup (parallel) ───────────────────────────────────────────────

    def lookup_batch(
        self,
        vendor: str,
        commands: List[str],
        platform: Optional[str] = None,
        max_workers: int = 4,
    ) -> Dict[str, KnowledgeEntry]:
        """
        Look up multiple commands in parallel.
        Returns {command: KnowledgeEntry}.
        """
        if not commands:
            return {}

        # Cache lookups are fast — do them serially first
        results: Dict[str, KnowledgeEntry] = {}
        needs_remote: List[str] = []

        for cmd in commands:
            cached = self.cache.get(vendor, cmd, platform or "")
            if cached and not cached.is_stale():
                cached.citation.confidence = ConfidenceLevel.MEDIUM
                cached.citation.notes = f"Cached {cached.age_days()} day(s) ago"
                results[cmd] = cached
            else:
                needs_remote.append(cmd)

        # Remote lookups (fetcher first, MCP fallback) in parallel
        if needs_remote and (self.enable_web_fetch or self.enable_mcp):
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
                fut_to_cmd = {
                    ex.submit(self._remote_lookup, vendor, cmd, platform): cmd
                    for cmd in needs_remote
                }
                for fut in concurrent.futures.as_completed(fut_to_cmd, timeout=60):
                    cmd = fut_to_cmd[fut]
                    try:
                        entry = fut.result()
                        if entry:
                            self.cache.upsert(entry)
                            results[cmd] = entry
                        else:
                            stale = self.cache.get(vendor, cmd, platform or "")
                            if stale:
                                stale.citation.confidence = ConfidenceLevel.LOW
                                results[cmd] = stale
                            else:
                                results[cmd] = KnowledgeEntry.unverified(vendor, cmd)
                    except Exception as exc:
                        logger.debug(f"Batch remote lookup failed for {cmd}: {exc}")
                        results[cmd] = KnowledgeEntry.unverified(vendor, cmd, str(exc))

        # Anything still missing → UNVERIFIED
        for cmd in commands:
            if cmd not in results:
                results[cmd] = KnowledgeEntry.unverified(vendor, cmd)

        return results

    # ── Remote lookup: fetcher → MCP fallback ─────────────────────────────────

    def _remote_lookup(
        self,
        vendor: str,
        command: str,
        platform: Optional[str],
    ) -> Optional[KnowledgeEntry]:
        """Web fetcher first, then MCP fallback."""
        if self.enable_web_fetch:
            entry = self._web_fetch(vendor, command, platform)
            if entry:
                return entry
        if self.enable_mcp:
            entry = self._mcp_lookup(vendor, command, platform)
            if entry:
                return entry
        return None

    def _web_fetch(
        self,
        vendor: str,
        command: str,
        platform: Optional[str],
    ) -> Optional[KnowledgeEntry]:
        fetcher = get_fetcher(vendor)
        if not fetcher:
            logger.debug(f"No fetcher for vendor '{vendor}'")
            return None
        return fetcher.fetch(command, platform)

    def _mcp_lookup(
        self,
        vendor: str,
        command: str,
        platform: Optional[str],
    ) -> Optional[KnowledgeEntry]:
        if not MCP_AVAILABLE:
            return None
        try:
            sources = get_mcp_sources_for_vendor(vendor)
        except Exception as exc:
            logger.debug(f"MCP source lookup failed: {exc}")
            return None

        for src in sources:
            try:
                entry = src.lookup(vendor, command, platform)
                if entry:
                    return entry
            except Exception as exc:
                logger.debug(f"MCP source {src.source_name} failed: {exc}")
                continue
        return None

    # ── RAG (primary) ─────────────────────────────────────────────────────────

    def _rag_lookup(
        self,
        vendor: str,
        command: str,
        platform: Optional[str],
    ) -> Optional[KnowledgeEntry]:
        """
        Semantic retrieval over ingested knowledge. Returns a KnowledgeEntry
        only if the top hit clears _RAG_MIN_SCORE; otherwise None so the
        caller falls through to web/MCP.
        """
        if not RAG_AVAILABLE:
            return None
        try:
            engine = get_rag_engine()
            # vendor filter only when we actually have ingested that vendor;
            # an over-narrow filter on an empty store would suppress good hits.
            hits = engine.search(command, top_k=3, min_score=_RAG_MIN_SCORE,
                                  vendor=vendor or None)
            if not hits:
                # retry without vendor filter (knowledge may be vendor-agnostic)
                hits = engine.search(command, top_k=3, min_score=_RAG_MIN_SCORE)
            if not hits:
                return None
            return self._rag_hit_to_entry(hits[0], vendor, command, platform)
        except Exception as exc:
            logger.debug(f"RAG lookup failed: {exc}")
            return None

    def _rag_hit_to_entry(
        self, hit: "RAGHit", vendor: str, command: str, platform: Optional[str],
    ) -> KnowledgeEntry:
        # Confidence scales with similarity; a strong semantic match is HIGH.
        if hit.score >= 0.7:
            conf = ConfidenceLevel.HIGH
        elif hit.score >= 0.55:
            conf = ConfidenceLevel.MEDIUM
        else:
            conf = ConfidenceLevel.LOW
        src_label = {
            "incident": "Past incident (RAG)",
            "runbook": "Runbook (RAG)",
            "vendor_doc": "Vendor doc (RAG)",
        }.get(hit.source, f"{hit.source} (RAG)")
        return KnowledgeEntry(
            vendor=vendor or hit.vendor,
            platform=platform or hit.platform,
            command=command,
            description=hit.text,
            citation=Citation(
                source_name=f"rag::{hit.source}",
                source_type="rag",
                source_title=hit.title or src_label,
                vendor=vendor or hit.vendor,
                confidence=conf,
                notes=f"{src_label} · semantic match {hit.score:.2f} · doc '{hit.doc_id}'",
            ),
        )

    def rag_query(
        self,
        query: str,
        top_k: int = 5,
        min_score: Optional[float] = None,
        vendor: Optional[str] = None,
        source: Optional[str] = None,
    ) -> List["RAGHit"]:
        """
        Free-text semantic retrieval over the knowledge base — the entry point
        for the AI chat to pull grounding context (runbooks, past incidents)
        for an arbitrary question, not just a command lookup. Returns raw
        RAGHits (empty list if RAG unavailable or nothing relevant).
        """
        if not self.enable_rag:
            return []
        try:
            engine = get_rag_engine()
            return engine.search(
                query, top_k=top_k,
                min_score=_RAG_MIN_SCORE if min_score is None else min_score,
                vendor=vendor, source=source,
            )
        except Exception as exc:
            logger.debug(f"rag_query failed: {exc}")
            return []

    # ── Admin / stats ─────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        s = self.cache.stats()
        s["supported_vendors"] = supported_vendors()
        s["web_fetch_enabled"] = self.enable_web_fetch
        s["mcp_enabled"]       = self.enable_mcp
        s["rag_enabled"]       = self.enable_rag
        if self.enable_rag:
            try:
                s["rag"] = get_rag_engine().stats()
            except Exception:
                s["rag"] = {"error": "unavailable"}

        # MCP source health
        if self.enable_mcp:
            try:
                from core.knowledge.mcp import get_mcp_sources
                s["mcp_sources"] = [src.health_check() for src in get_mcp_sources()]
            except Exception:
                s["mcp_sources"] = []
        else:
            s["mcp_sources"] = []

        return s

    def force_refresh(
        self,
        vendor: str,
        command: str,
        platform: Optional[str] = None,
    ) -> KnowledgeEntry:
        """Bypass cache and re-fetch from source."""
        self.cache.delete(vendor, command, platform or "")
        return self.lookup(vendor, command, platform)

    def clear_cache(self) -> int:
        return self.cache.clear_all()


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton accessor
# ═══════════════════════════════════════════════════════════════════════════════

_orchestrator_instance: Optional[KnowledgeOrchestrator] = None


def get_orchestrator() -> KnowledgeOrchestrator:
    """Singleton accessor."""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = KnowledgeOrchestrator()
    return _orchestrator_instance
