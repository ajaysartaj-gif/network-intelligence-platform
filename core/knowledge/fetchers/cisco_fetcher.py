"""
core/knowledge/fetchers/cisco_fetcher.py
========================================
Cisco-specific documentation fetcher.

Cisco's doc structure varies by IOS version, platform family, and product
line.  Rather than hardcoding URL patterns that break with every release,
this fetcher uses a search-first strategy:

  1. Build vendor-scoped queries that work via DuckDuckGo HTML search
     (no API key, no rate limit for low volume).
  2. Parse candidate result URLs and filter to trusted Cisco domains.
  3. Fetch the HTML and extract command details.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urljoin

from core.knowledge.fetchers.base_fetcher import VendorFetcher, BS4_OK, REQUESTS_OK

logger = logging.getLogger("NetBrain.Knowledge.CiscoFetcher")


class CiscoFetcher(VendorFetcher):
    """Cisco IOS / IOS-XE / NX-OS / ASA / XR documentation fetcher."""

    vendor_key   = "cisco"
    display_name = "Cisco"
    trusted_domains = ["cisco.com"]

    # Use DuckDuckGo HTML endpoint — no API key, works server-side
    DDG_SEARCH_URL = "https://html.duckduckgo.com/html/?q={query}"

    # Platform → query hint mapping
    PLATFORM_HINTS = {
        "ios":     "IOS XE",
        "ios-xe":  "IOS XE",
        "nx-os":   "NX-OS Nexus",
        "asa":     "ASA Security",
        "ios-xr":  "IOS XR",
    }

    MAX_CANDIDATES = 5

    # ── Search for candidate doc pages ────────────────────────────────────────

    def search_candidates(
        self,
        command: str,
        platform: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        """
        Build search queries and return list of (url, title) tuples.
        """
        if not REQUESTS_OK:
            return []

        platform_hint = self.PLATFORM_HINTS.get((platform or "").lower(), "IOS")

        # Build multiple query strategies, most specific first
        queries = [
            f'"{command}" "{platform_hint}" "command reference" site:cisco.com',
            f'"{command}" "command reference" site:cisco.com',
            f'"{command}" site:cisco.com',
        ]

        seen: set = set()
        candidates: List[Tuple[str, str]] = []

        for q in queries:
            results = self._duckduckgo_search(q)
            for url, title in results:
                if url in seen:
                    continue
                # Filter: must be from cisco.com and look like docs
                if "cisco.com" not in url:
                    continue
                # Prefer /td/docs/, /support/, /command-reference/
                if not any(p in url for p in ("/td/docs/", "/support/", "/command-reference/", "/command/")):
                    continue
                seen.add(url)
                candidates.append((url, title))
                if len(candidates) >= self.MAX_CANDIDATES:
                    return candidates

        return candidates

    def _duckduckgo_search(self, query: str) -> List[Tuple[str, str]]:
        """Return [(url, title), ...] from DuckDuckGo HTML results."""
        try:
            import requests
            url = self.DDG_SEARCH_URL.format(query=quote_plus(query))
            r = requests.get(
                url,
                timeout=self.HTTP_TIMEOUT,
                headers={"User-Agent": self.USER_AGENT},
            )
            if r.status_code != 200:
                return []

            soup = self._get_soup(r.text)
            if not soup:
                return []

            out: List[Tuple[str, str]] = []
            for a in soup.find_all("a", class_="result__a", limit=20):
                href = a.get("href", "")
                title = self._clean_text(a.get_text(), 200)
                if not href:
                    continue
                # DDG wraps real URL in their redirect; extract uddg=
                m = re.search(r"uddg=([^&]+)", href)
                if m:
                    from urllib.parse import unquote
                    real_url = unquote(m.group(1))
                else:
                    real_url = href
                if real_url.startswith("http"):
                    out.append((real_url, title))
            return out

        except Exception as exc:
            logger.debug(f"DuckDuckGo search failed: {exc}")
            return []

    # ── Parse a Cisco doc page ────────────────────────────────────────────────

    def parse_page(
        self,
        html: str,
        url: str,
        command: str,
    ) -> Optional[Dict[str, str]]:
        """
        Extract syntax, description, example output from a Cisco doc page.
        Cisco pages typically structure command refs with these HTML markers:
          - <h1>, <h2>, <h3> for command names
          - <pre> blocks for syntax
          - Descriptive paragraphs before/after
        """
        if not BS4_OK:
            return None
        soup = self._get_soup(html)
        if not soup:
            return None

        # Reject if the page doesn't actually contain the command
        if not self._extract_command_match(html, command):
            return None

        page_title = soup.title.get_text().strip() if soup.title else ""

        # Find the section containing our command
        cmd_section = self._find_command_section(soup, command)
        if not cmd_section:
            # Fallback: search whole document
            cmd_section = soup

        # Extract syntax (Cisco often puts it in <pre> or <samp> or <code>)
        syntax = self._extract_syntax(cmd_section, command)

        # Extract description (first descriptive paragraph)
        description = self._extract_description(cmd_section, command)

        # Extract example output
        example = self._extract_example(cmd_section)

        # Extract min IOS version if mentioned
        min_version = self._extract_min_version(cmd_section)

        if not (syntax or description):
            return None

        return {
            "syntax":         self._clean_text(syntax, 500),
            "description":    self._clean_text(description, 1500),
            "example_output": self._clean_text(example, 1500),
            "min_version":    self._clean_text(min_version, 200),
            "page_title":     page_title,
        }

    # ── Section-level extraction helpers ──────────────────────────────────────

    def _find_command_section(self, soup: Any, command: str) -> Optional[Any]:
        """Find the heading that introduces the command, return its section."""
        cmd_lower = command.lower().strip()

        # Look in h1..h4 for the command name
        for tag in ("h1", "h2", "h3", "h4"):
            for h in soup.find_all(tag):
                if cmd_lower in h.get_text().lower():
                    # Collect siblings until the next heading of same/higher level
                    return self._collect_section_siblings(h)
        return None

    @staticmethod
    def _collect_section_siblings(heading: Any) -> Any:
        """Return a 'virtual' container with the heading and following content."""
        from bs4 import BeautifulSoup, Tag
        container = BeautifulSoup("<div></div>", "html.parser").div
        container.append(heading.__copy__())
        sib = heading.find_next_sibling()
        same_level = ("h1", "h2", "h3", "h4")
        max_steps = 50
        steps = 0
        while sib and steps < max_steps:
            if getattr(sib, "name", None) in same_level:
                break
            container.append(sib.__copy__() if hasattr(sib, "__copy__") else sib)
            sib = sib.find_next_sibling() if hasattr(sib, "find_next_sibling") else None
            steps += 1
        return container

    def _extract_syntax(self, section: Any, command: str) -> str:
        """Pull the syntax line — usually inside <pre>, <code>, or <samp>."""
        for tag in ("pre", "samp", "code"):
            for elem in section.find_all(tag, limit=5):
                text = elem.get_text().strip()
                if command.lower() in text.lower() and len(text) < 500:
                    return text
        # Fallback: any line that starts with the command
        text = section.get_text()
        for line in text.split("\n"):
            ln = line.strip()
            if ln.lower().startswith(command.lower()) and len(ln) < 300:
                return ln
        return command  # at minimum, return the command itself

    def _extract_description(self, section: Any, command: str) -> str:
        """First descriptive paragraph that explains the command."""
        # Look for <p> tags
        for p in section.find_all("p", limit=10):
            text = p.get_text().strip()
            # Skip empty, very short, or "Available Languages" boilerplate
            if len(text) < 30:
                continue
            if any(skip in text.lower() for skip in (
                "available languages", "download options",
                "bias-free language", "log in to save",
            )):
                continue
            # The description usually starts with "To " or "Use" or "This command"
            return text
        return ""

    def _extract_example(self, section: Any) -> str:
        """Find a sample output / example block."""
        # Look for <pre> blocks that look like CLI output (multiple lines, contains #)
        for pre in section.find_all("pre", limit=5):
            text = pre.get_text().strip()
            if "\n" in text and ("#" in text or "$" in text or ">" in text):
                if len(text) < 2000:
                    return text
        return ""

    def _extract_min_version(self, section: Any) -> str:
        """Look for 'Command History' or version mentions."""
        text = section.get_text()
        # Common patterns
        patterns = [
            r"IOS\s*XE\s*\d+\.\d+(?:\.\d+)?",
            r"IOS\s*\d+\.\d+(?:\(\d+\))?",
            r"NX-OS\s*\d+\.\d+(?:\(\d+\))?",
            r"Release\s+\d+\.\d+",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(0)
        return ""
