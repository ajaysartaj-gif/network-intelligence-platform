"""
core/knowledge/fetchers/huawei_fetcher.py
==========================================
Huawei VRP (datacom) documentation fetcher — same search-first pattern as
fortinet_fetcher.py: DuckDuckGo HTML search (no API key), filtered to
Huawei's trusted support domain, then HTML parse for syntax/description.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from core.knowledge.fetchers.base_fetcher import VendorFetcher, BS4_OK, REQUESTS_OK

logger = logging.getLogger("AI Net Studio.Knowledge.HuaweiFetcher")


class HuaweiFetcher(VendorFetcher):
    """Huawei VRP / NE / CloudEngine documentation fetcher."""

    vendor_key   = "huawei"
    display_name = "Huawei"
    trusted_domains = ["support.huawei.com"]
    MAX_CANDIDATES = 4

    def search_candidates(
        self,
        command: str,
        platform: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        if not REQUESTS_OK:
            return []

        queries = [
            f'"{command}" VRP "command reference"',
            f'"{command}" Huawei CloudEngine',
        ]

        seen: set = set()
        candidates: List[Tuple[str, str]] = []
        for q in queries:
            for url, title in self._web_search(q):
                if url in seen or "support.huawei.com" not in url:
                    continue
                seen.add(url)
                candidates.append((url, title))
                if len(candidates) >= self.MAX_CANDIDATES:
                    return candidates
        return candidates


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

        syntax = ""
        for elems in (soup.find_all("pre", limit=5), soup.find_all("code", limit=5)):
            for elem in elems:
                txt = elem.get_text().strip()
                if command.lower() in txt.lower() and len(txt) < 500:
                    syntax = txt
                    break
            if syntax:
                break

        description = ""
        for p in soup.find_all("p", limit=10):
            txt = p.get_text().strip()
            if len(txt) > 50:
                description = txt
                break

        version_match = re.search(r"V\d{3}R\d{3}[A-Z0-9]*", soup.get_text())
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
