"""
core/knowledge/fetchers/base_fetcher.py
=======================================
Abstract base class for every vendor-specific web fetcher.

Each vendor (Cisco, Juniper, Arista, etc.) implements VendorFetcher to:
  1. Search for a command in the vendor's documentation
  2. Fetch the matching doc page
  3. Parse syntax / description / examples
  4. Return a KnowledgeEntry with proper citation
"""
from __future__ import annotations

import logging
import os
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

try:
    from bs4 import BeautifulSoup
    BS4_OK = True
except ImportError:
    BS4_OK = False

from core.knowledge.base import (
    Citation,
    ConfidenceLevel,
    KnowledgeEntry,
)
from core.knowledge.cache.ttl_policy import get_ttl

logger = logging.getLogger("AI Net Studio.Knowledge.Fetcher")


class SearchBackendBlocked(Exception):
    """Raised when the search backend itself refused to search (e.g. an
    anti-bot challenge response), as opposed to searching successfully and
    finding zero relevant results. This distinction used to be silently
    lost — every vendor fetcher's own except-clause logged it at DEBUG
    level and returned an empty list identically to a genuine "nothing
    matched" — so every live vendor-doc lookup across all 9 vendors could
    (and did) fail completely silently with no indication anywhere that
    the search backend was the problem, not the query."""


def _get_secret(name: str) -> str:
    """Same 3-tier lookup as core.ai_engine.get_api_key (Streamlit secrets
    -> os.environ -> .env file in repo root), generalized to any named
    key instead of hardcoded to GROQ_API_KEY. Kept local rather than
    importing ai_engine, which is Groq-specific and pulls in the OpenAI
    client just for a string lookup."""
    try:
        import streamlit as st
        val = st.secrets.get(name, "")
        if val and str(val).strip():
            return str(val).strip()
    except Exception:
        pass
    val = os.environ.get(name, "").strip()
    if val:
        return val
    try:
        from dotenv import load_dotenv
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        env_path = os.path.join(repo_root, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=False)
            val = os.environ.get(name, "").strip()
            if val:
                return val
    except Exception:
        pass
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# Vendor Fetcher base class
# ═══════════════════════════════════════════════════════════════════════════════

class VendorFetcher(ABC):
    """
    Each vendor implements: vendor_key, search_url_template, parse_page().
    The base class handles HTTP, timeouts, error handling.
    """

    # Subclasses MUST override these
    vendor_key:    str = "unknown"     # e.g. 'cisco', 'juniper'
    display_name:  str = "Unknown"     # e.g. 'Cisco', 'Juniper Networks'
    trusted_domains: List[str] = []    # e.g. ['cisco.com']

    # Network defaults
    HTTP_TIMEOUT  = 10
    MAX_PAGE_SIZE = 200_000        # don't fetch >200KB; abort large pages
    USER_AGENT    = "AI Net Studio-AI/1.0 (network-intelligence-platform)"

    # Keyless HTML search endpoint every vendor fetcher searches against.
    # Was duplicated verbatim across all 9 vendor fetcher files — moved
    # here as the single shared implementation (see _duckduckgo_search
    # below) so a fix to the search mechanism benefits every vendor at
    # once instead of needing 9 identical edits. Now the FALLBACK, not
    # the primary path — see _web_search.
    DDG_SEARCH_URL = "https://html.duckduckgo.com/html/?q={query}"

    # Real, key-based search API — the durable replacement for the
    # keyless DDG scrape above, which DuckDuckGo's own anti-bot detection
    # now reliably defeats. Tavily was chosen (over Brave, whose free tier
    # was killed in Feb 2026 and now requires a card on file; over the
    # classic Bing Web Search API, which Microsoft has been retiring; and
    # over Google Custom Search, which needs a separate Cloud project +
    # Custom Search Engine ID, not just a key) for a genuinely
    # card-free 1,000-credit/month tier and a JSON API built specifically
    # for this exact use case — grounding an AI agent's answer in real web
    # content, returning already-extracted text instead of raw HTML to
    # scrape.
    TAVILY_SEARCH_URL = "https://api.tavily.com/search"
    # Tavily's Extract endpoint — given a real doc-page URL, returns clean,
    # already-parsed content. This is the durable replacement for every
    # vendor's own bespoke BeautifulSoup parse_page() (Cisco's
    # _find_command_section/_extract_syntax/etc.), which broke every time
    # a vendor's docs site changed its HTML structure. Used only at
    # INGESTION time (see ingest_via_search_and_extract), never as a
    # per-query runtime dependency during live troubleshooting — the old
    # HTML parser stays the fallback until this path is fully validated.
    TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"

    def __init__(self):
        if not REQUESTS_OK:
            logger.warning(f"[{self.vendor_key}] requests not installed — web fetching disabled")

    # ── Public API ────────────────────────────────────────────────────────────

    def supports_vendor(self, vendor: str) -> bool:
        return (vendor or "").lower() == self.vendor_key

    def fetch(
        self,
        command: str,
        platform: Optional[str] = None,
    ) -> Optional[KnowledgeEntry]:
        """Main entry — search, fetch, parse. Returns None on failure."""
        if not REQUESTS_OK:
            return None

        try:
            # Step 1: search for candidate URLs
            candidates = self.search_candidates(command, platform)
            if not candidates:
                logger.info(f"[{self.vendor_key}] no candidate URLs for '{command}'")
                return None
        except SearchBackendBlocked as exc:
            # Distinct from "searched successfully, found nothing" —
            # surfaced at WARNING (not swallowed at DEBUG) specifically so
            # this is visible in logs instead of silently degrading every
            # live vendor-doc lookup to "no grounding available" with no
            # trace of why.
            logger.warning(
                f"[{self.vendor_key}] live doc lookup for '{command}' unavailable: {exc}")
            return None

        try:

            # Step 2: try each candidate until one parses successfully
            for url, title in candidates:
                if not self._is_trusted_url(url):
                    continue
                entry = self._try_fetch_and_parse(url, title, command, platform)
                if entry:
                    return entry

            logger.info(f"[{self.vendor_key}] all candidates failed for '{command}'")
            return None

        except Exception as exc:
            logger.warning(f"[{self.vendor_key}] fetch error for '{command}': {exc}")
            return None

    # ── Required overrides ────────────────────────────────────────────────────

    @abstractmethod
    def search_candidates(
        self,
        command: str,
        platform: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        """
        Return a list of (url, title) candidate doc pages for this command.
        Implementations vary — some use direct URL patterns, others scrape
        a vendor doc search page.
        """
        raise NotImplementedError

    @abstractmethod
    def parse_page(
        self,
        html: str,
        url: str,
        command: str,
    ) -> Optional[Dict[str, str]]:
        """
        Parse a doc page HTML for: syntax, description, example_output, min_version.
        Return a dict with these keys or None if the page doesn't have the command.
        """
        raise NotImplementedError

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _web_search(self, query: str) -> List[Tuple[str, str]]:
        """The entry point every vendor's search_candidates() calls. Tries
        the real, key-based Tavily Search API first; only falls back to
        the keyless DuckDuckGo scrape if no TAVILY_API_KEY is configured
        at all — that scrape is kept as a last resort for a deployment
        without a key, not because it's expected to work (DuckDuckGo's own
        anti-bot detection now reliably defeats it — see
        SearchBackendBlocked's docstring)."""
        has_key = bool(_get_secret("TAVILY_API_KEY"))
        if has_key:
            results = self._tavily_search(query)
            # A configured key that legitimately found nothing is a real
            # "no results" — falling through to the DDG scrape here would
            # produce a confusing SECOND failure mode instead of trusting
            # the real search API's own answer.
            return results
        return self._duckduckgo_search(query)

    def _tavily_search(self, query: str) -> List[Tuple[str, str]]:
        """Real search via the Tavily Search API
        (https://docs.tavily.com/documentation/api-reference/endpoint/search),
        genuinely free (1,000 credits/month, no credit card) and built
        specifically for grounding an AI agent's answer in real web
        content. Returns [] with no exception if no key is configured (the
        caller, _web_search, only calls this once it already confirmed a
        key exists) — genuine API failures (bad key, rate limit, outage)
        raise SearchBackendBlocked so they're visible the same way a
        blocked DDG scrape is, rather than silently degrading."""
        key = _get_secret("TAVILY_API_KEY")
        if not key:
            return []
        try:
            payload = {"query": query, "max_results": 10}
            # Tavily's own include_domains filter narrows results to this
            # fetcher's trusted vendor domain server-side — more reliable
            # than embedding "site:cisco.com" as query text (which a
            # generic search API has no obligation to honor exactly).
            if self.trusted_domains:
                payload["include_domains"] = list(self.trusted_domains)
            r = requests.post(
                self.TAVILY_SEARCH_URL,
                json=payload,
                headers={"Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                        "User-Agent": self.USER_AGENT},
                timeout=self.HTTP_TIMEOUT,
            )
            if r.status_code != 200:
                raise SearchBackendBlocked(
                    f"Tavily Search API returned HTTP {r.status_code} for query {query!r}")
            data = r.json()
            results = data.get("results") or []
            out: List[Tuple[str, str]] = []
            for item in results:
                url = item.get("url", "")
                title = self._clean_text(item.get("title", ""), 200)
                if url.startswith("http"):
                    out.append((url, title))
            return out
        except SearchBackendBlocked:
            raise
        except Exception as exc:
            raise SearchBackendBlocked(f"Tavily Search API request failed: {exc}") from exc

    def _tavily_extract(self, urls: List[str]) -> Dict[str, str]:
        """Real content extraction via the Tavily Extract API — given real
        doc-page URLs (from _tavily_search), returns {url: raw_content}
        for whichever ones succeeded. Ingestion-time only (see
        ingest_via_search_and_extract); returns {} with no exception if no
        key is configured, same convention as _tavily_search."""
        key = _get_secret("TAVILY_API_KEY")
        if not key or not urls:
            return {}
        try:
            r = requests.post(
                self.TAVILY_EXTRACT_URL,
                json={"urls": urls},
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                        "User-Agent": self.USER_AGENT},
                timeout=self.HTTP_TIMEOUT,
            )
            if r.status_code != 200:
                raise SearchBackendBlocked(
                    f"Tavily Extract API returned HTTP {r.status_code} for {len(urls)} URL(s)")
            data = r.json()
            return {item.get("url", ""): item.get("raw_content", "")
                    for item in (data.get("results") or []) if item.get("url")}
        except SearchBackendBlocked:
            raise
        except Exception as exc:
            raise SearchBackendBlocked(f"Tavily Extract API request failed: {exc}") from exc

    def ingest_via_search_and_extract(
        self, command: str, platform: Optional[str] = None,
    ) -> Optional[KnowledgeEntry]:
        """The NEW ingestion path this fetcher's callers should prefer:
        Tavily Search finds trusted candidate doc pages, Tavily Extract
        pulls their real content, and the result is normalized into a
        KnowledgeEntry ready to persist into the local knowledge store
        (KnowledgeCacheDB and/or EnterpriseKnowledgeLayer/RAG — see
        core.knowledge.orchestrator.KnowledgeOrchestrator._web_fetch and
        core.knowledge.enterprise.pipelines.fetch_and_ingest_vendor_doc,
        both of which persist whatever this returns).

        Deliberately NOT the per-query runtime path — this is meant to be
        called only on a genuine local-knowledge miss (cache + RAG both
        came up empty) or by an explicit, scheduled/manual knowledge
        refresh, never on every troubleshooting query; the whole point is
        that a persisted result here means the NEXT query for the same
        command is a local cache hit; not a repeat API call.

        Returns None (never raises) when no TAVILY_API_KEY is configured
        or nothing usable was found — callers should fall back to the
        older fetch() (raw HTML + per-vendor BeautifulSoup parsing) in
        that case; that fallback is kept deliberately until this path is
        fully validated in production, not because it's expected to work
        well (DuckDuckGo's own anti-bot detection already defeats its
        search step for most callers — see SearchBackendBlocked)."""
        if not _get_secret("TAVILY_API_KEY"):
            return None
        try:
            candidates = self.search_candidates(command, platform)
        except SearchBackendBlocked as exc:
            logger.warning(f"[{self.vendor_key}] ingest search failed for '{command}': {exc}")
            return None
        trusted = [(url, title) for url, title in candidates if self._is_trusted_url(url)]
        if not trusted:
            return None
        try:
            extracted = self._tavily_extract([url for url, _ in trusted[:3]])
        except SearchBackendBlocked as exc:
            logger.warning(f"[{self.vendor_key}] ingest extract failed for '{command}': {exc}")
            return None
        for url, title in trusted:
            raw_content = extracted.get(url, "")
            if raw_content and self._extract_command_match(raw_content, command):
                now = datetime.utcnow().isoformat()
                return KnowledgeEntry(
                    vendor=self.vendor_key, platform=platform or "", command=command.strip(),
                    syntax="", description=self._clean_text(raw_content, 1500),
                    example_output="", min_version="",
                    citation=Citation(
                        source_name=f"{self.vendor_key}_tavily_ingest", source_type="web",
                        source_url=url, source_title=title or self.display_name,
                        vendor=self.vendor_key, confidence=ConfidenceLevel.HIGH, fetched_at=now,
                    ),
                    fetched_at=now, verified_at=now, ttl_days=get_ttl(self.vendor_key),
                )
        return None

    def _duckduckgo_search(self, query: str) -> List[Tuple[str, str]]:
        """Return [(url, title), ...] from DuckDuckGo's keyless HTML search
        endpoint. Shared by every vendor fetcher (was duplicated 9x
        verbatim before this).

        Raises SearchBackendBlocked when DDG returns anything other than
        200 — in practice this endpoint now reliably returns 202 (an
        anti-bot interstitial, not real results) for automated requests
        regardless of query or User-Agent, confirmed by direct testing.
        The previous code treated this identically to "0 results" and
        swallowed it at DEBUG level, which is why every vendor's live
        doc lookup could fail with literally no visible indication
        anywhere that the search backend — not the query — was the
        actual problem."""
        try:
            from urllib.parse import quote_plus, unquote
            url = self.DDG_SEARCH_URL.format(query=quote_plus(query))
            r = requests.get(url, timeout=self.HTTP_TIMEOUT,
                             headers={"User-Agent": self.USER_AGENT})
            if r.status_code != 200:
                raise SearchBackendBlocked(
                    f"DuckDuckGo search returned HTTP {r.status_code} for query "
                    f"{query!r} (likely bot-detection, not a real result page)")
            soup = self._get_soup(r.text)
            if not soup:
                return []
            out: List[Tuple[str, str]] = []
            for a in soup.find_all("a", class_="result__a", limit=20):
                href = a.get("href", "")
                title = self._clean_text(a.get_text(), 200)
                if not href:
                    continue
                m = re.search(r"uddg=([^&]+)", href)
                real_url = unquote(m.group(1)) if m else href
                if real_url.startswith("http"):
                    out.append((real_url, title))
            return out
        except SearchBackendBlocked:
            raise
        except Exception as exc:
            raise SearchBackendBlocked(f"DuckDuckGo search request failed: {exc}") from exc

    def _is_trusted_url(self, url: str) -> bool:
        """Only fetch from declared trusted vendor domains."""
        if not url or not self.trusted_domains:
            return False
        return any(d in url for d in self.trusted_domains)

    def _try_fetch_and_parse(
        self,
        url: str,
        page_title: str,
        command: str,
        platform: Optional[str],
    ) -> Optional[KnowledgeEntry]:
        try:
            html = self._fetch_html(url)
            if not html:
                return None

            parsed = self.parse_page(html, url, command)
            if not parsed:
                return None

            now = datetime.utcnow().isoformat()
            entry = KnowledgeEntry(
                vendor=self.vendor_key,
                platform=platform or "",
                command=command.strip(),
                syntax=parsed.get("syntax", ""),
                description=parsed.get("description", ""),
                example_output=parsed.get("example_output", ""),
                min_version=parsed.get("min_version", ""),
                citation=Citation(
                    source_name=f"{self.vendor_key}_fetcher",
                    source_type="web",
                    source_url=url,
                    source_title=parsed.get("page_title", page_title) or self.display_name,
                    vendor=self.vendor_key,
                    confidence=ConfidenceLevel.HIGH,
                    fetched_at=now,
                ),
                fetched_at=now,
                verified_at=now,
                ttl_days=get_ttl(self.vendor_key),
            )
            return entry

        except Exception as exc:
            logger.debug(f"[{self.vendor_key}] parse failed for {url}: {exc}")
            return None

    def _fetch_html(self, url: str) -> Optional[str]:
        if not REQUESTS_OK:
            return None
        try:
            r = requests.get(
                url,
                timeout=self.HTTP_TIMEOUT,
                headers={"User-Agent": self.USER_AGENT},
                stream=True,
            )
            if r.status_code != 200:
                logger.debug(f"[{self.vendor_key}] HTTP {r.status_code} for {url}")
                return None

            # Cap size — abort if too big
            content = b""
            for chunk in r.iter_content(chunk_size=8192):
                content += chunk
                if len(content) > self.MAX_PAGE_SIZE:
                    logger.debug(f"[{self.vendor_key}] page too large at {url}")
                    return None

            return content.decode("utf-8", errors="ignore")

        except requests.RequestException as exc:
            logger.debug(f"[{self.vendor_key}] HTTP error for {url}: {exc}")
            return None

    # ── HTML helpers (shared across all fetchers) ─────────────────────────────

    @staticmethod
    def _get_soup(html: str) -> Optional[Any]:
        if not BS4_OK:
            return None
        try:
            return BeautifulSoup(html, "html.parser")
        except Exception:
            return None

    @staticmethod
    def _clean_text(text: str, max_chars: int = 1500) -> str:
        """Collapse whitespace, trim to max."""
        if not text:
            return ""
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]

    @staticmethod
    def _extract_command_match(html: str, command: str) -> bool:
        """Quick check — does this page mention the exact command?"""
        if not html or not command:
            return False
        # Case-insensitive substring match — full command appears
        return command.lower() in html.lower()
