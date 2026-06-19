"""
core/knowledge/orchestrator.py
==============================
The central knowledge orchestrator.

Lookup priority (highest to lowest):
  1. Local SQLite cache         → instant, if fresh
  2. Vendor web fetcher          → web-scrape vendor docs (Cisco, Juniper, etc.)
  3. MCP sources (fallback)      → official vendor MCPs (e.g. Cisco DevNet)
  4. Stale cache                 → if web fetch + MCP both fail
  5. UNVERIFIED                  → AI guess, with warning badge

The fetcher-first ordering matches the operator's stated preference:
"first look for fetchers then go to MCP".
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


# ═══════════════════════════════════════════════════════════════════════════════
# KnowledgeOrchestrator
# ═══════════════════════════════════════════════════════════════════════════════

class KnowledgeOrchestrator:
    """Cache-first knowledge lookup with web-fetch then MCP fallback."""

    def __init__(
        self,
        enable_web_fetch: bool = True,
        enable_mcp:       bool = True,
    ):
        self.cache = get_cache()
        self.enable_web_fetch = enable_web_fetch
        self.enable_mcp = enable_mcp and MCP_AVAILABLE

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

        # ── 2. Web fetcher (PRIMARY — user's stated preference) ──────────────
        if self.enable_web_fetch:
            fetched = self._web_fetch(vendor, command, platform)
            if fetched:
                self.cache.upsert(fetched)
                logger.info(
                    f"Web FETCH OK: {vendor}/{command} from {fetched.citation.source_url}"
                )
                return fetched
            logger.debug(f"Web fetcher returned nothing for {vendor}/{command}")

        # ── 3. MCP sources (FALLBACK — only if fetcher returned nothing) ─────
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

    # ── Admin / stats ─────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        s = self.cache.stats()
        s["supported_vendors"] = supported_vendors()
        s["web_fetch_enabled"] = self.enable_web_fetch
        s["mcp_enabled"]       = self.enable_mcp

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
