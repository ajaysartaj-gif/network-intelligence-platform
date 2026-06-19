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

logger = logging.getLogger("NetBrain.Knowledge.Fetcher")


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
    USER_AGENT    = "NetBrain-AI/1.0 (network-intelligence-platform)"

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
