"""
core/knowledge/fetchers/paloalto_fetcher.py
===========================================
Palo Alto Networks PAN-OS documentation fetcher.

Docs at docs.paloaltonetworks.com — clean structure with CLI Quick Start
and per-release command references.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from core.knowledge.fetchers.base_fetcher import VendorFetcher, BS4_OK, REQUESTS_OK

logger = logging.getLogger("AI Net Studio.Knowledge.PaloAltoFetcher")


class PaloAltoFetcher(VendorFetcher):
    """Palo Alto PAN-OS documentation fetcher."""

    vendor_key   = "paloalto"
    display_name = "Palo Alto Networks"
    trusted_domains = ["paloaltonetworks.com"]
    MAX_CANDIDATES = 4

    def search_candidates(
        self,
        command: str,
        platform: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        if not REQUESTS_OK:
            return []

        queries = [
            f'"{command}" PAN-OS "CLI"',
            f'"{command}" PAN-OS',
        ]

        seen: set = set()
        candidates: List[Tuple[str, str]] = []
        for q in queries:
            for url, title in self._web_search(q):
                if url in seen:
                    continue
                if "paloaltonetworks.com" not in url:
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

        # PAN docs use <pre class="programlisting"> or <code>
        syntax = ""
        for css_class in ("programlisting", "code", "screen"):
            for elem in soup.find_all(class_=css_class, limit=5):
                txt = elem.get_text().strip()
                if command.lower() in txt.lower() and len(txt) < 500:
                    syntax = txt
                    break
            if syntax:
                break

        # Description from first content paragraph
        description = ""
        for p in soup.find_all("p", limit=10):
            txt = p.get_text().strip()
            if len(txt) > 50:
                description = txt
                break

        # PAN-OS version mention
        version_match = re.search(r"PAN-OS\s+\d+(?:\.\d+)*", soup.get_text())
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
