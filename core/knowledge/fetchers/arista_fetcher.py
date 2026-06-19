"""
core/knowledge/fetchers/arista_fetcher.py
=========================================
Arista EOS documentation fetcher.

Arista publishes docs at:
  - arista.com/en/um-eos/  (EOS User Manual)
  - arista.com/en/support/product-documentation
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from core.knowledge.fetchers.base_fetcher import VendorFetcher, BS4_OK, REQUESTS_OK

logger = logging.getLogger("NetBrain.Knowledge.AristaFetcher")


class AristaFetcher(VendorFetcher):
    """Arista EOS documentation fetcher."""

    vendor_key   = "arista"
    display_name = "Arista Networks"
    trusted_domains = ["arista.com"]

    DDG_SEARCH_URL = "https://html.duckduckgo.com/html/?q={query}"
    MAX_CANDIDATES = 4

    def search_candidates(
        self,
        command: str,
        platform: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        if not REQUESTS_OK:
            return []

        queries = [
            f'"{command}" EOS "command reference" site:arista.com',
            f'"{command}" EOS site:arista.com',
        ]

        seen: set = set()
        candidates: List[Tuple[str, str]] = []
        for q in queries:
            for url, title in self._duckduckgo_search(q):
                if url in seen:
                    continue
                if "arista.com" not in url:
                    continue
                seen.add(url)
                candidates.append((url, title))
                if len(candidates) >= self.MAX_CANDIDATES:
                    return candidates
        return candidates

    def _duckduckgo_search(self, query: str) -> List[Tuple[str, str]]:
        try:
            import requests
            from urllib.parse import unquote
            url = self.DDG_SEARCH_URL.format(query=quote_plus(query))
            r = requests.get(url, timeout=self.HTTP_TIMEOUT,
                             headers={"User-Agent": self.USER_AGENT})
            if r.status_code != 200:
                return []
            soup = self._get_soup(r.text)
            if not soup:
                return []
            out: List[Tuple[str, str]] = []
            for a in soup.find_all("a", class_="result__a", limit=15):
                href = a.get("href", "")
                title = self._clean_text(a.get_text(), 200)
                m = re.search(r"uddg=([^&]+)", href)
                real_url = unquote(m.group(1)) if m else href
                if real_url.startswith("http"):
                    out.append((real_url, title))
            return out
        except Exception as exc:
            logger.debug(f"DDG search failed: {exc}")
            return []

    def parse_page(
        self,
        html: str,
        url: str,
        command: str,
    ) -> Optional[Dict[str, str]]:
        if not BS4_OK:
            return None
        soup = self._get_soup(html)
        if not soup:
            return None
        if not self._extract_command_match(html, command):
            return None

        page_title = soup.title.get_text().strip() if soup.title else ""

        # Arista usually shows commands in <pre> or <code> blocks
        syntax = ""
        for tag in ("pre", "code"):
            for elem in soup.find_all(tag, limit=5):
                txt = elem.get_text().strip()
                if command.lower() in txt.lower() and len(txt) < 500:
                    syntax = txt
                    break
            if syntax:
                break

        # Description from first decent <p>
        description = ""
        for p in soup.find_all("p", limit=10):
            txt = p.get_text().strip()
            if len(txt) > 50:
                description = txt
                break

        # EOS version mentions
        version_match = re.search(r"EOS\s+\d+\.\d+(?:\.\d+)?", soup.get_text())
        min_version = version_match.group(0) if version_match else ""

        if not (syntax or description):
            return None

        return {
            "syntax":         self._clean_text(syntax, 500),
            "description":    self._clean_text(description, 1500),
            "example_output": "",
            "min_version":    self._clean_text(min_version, 200),
            "page_title":     page_title,
        }
