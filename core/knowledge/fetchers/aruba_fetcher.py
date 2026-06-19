"""
core/knowledge/fetchers/aruba_fetcher.py
========================================
HPE Aruba (AOS-CX / AOS / ArubaOS-Switch) documentation fetcher.

Trusted domains:
  - arubanetworking.hpe.com  (newer HPE-branded docs)
  - arubanetworks.com         (legacy Aruba docs, still maintained)
  - hpe.com/psnow             (HPE Product Documentation)

Doc path patterns:
  /techdocs/AOS-CX/<version>/HTML/<book-id>/...
  /techdocs/AOS-CX/help_portal/Content/...
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from core.knowledge.fetchers.base_fetcher import VendorFetcher, BS4_OK, REQUESTS_OK

logger = logging.getLogger("NetBrain.Knowledge.ArubaFetcher")


class ArubaFetcher(VendorFetcher):
    """HPE Aruba AOS-CX / ArubaOS / ArubaOS-Switch documentation fetcher."""

    vendor_key   = "aruba"
    display_name = "HPE Aruba Networking"
    trusted_domains = [
        "arubanetworking.hpe.com",
        "arubanetworks.com",
        "hpe.com",
    ]

    DDG_SEARCH_URL = "https://html.duckduckgo.com/html/?q={query}"
    MAX_CANDIDATES = 4

    # Platform → query hint mapping
    PLATFORM_HINTS = {
        "arubaos":    "ArubaOS",
        "aos-cx":     "AOS-CX",
        "aoss":       "ArubaOS-Switch",
    }

    def search_candidates(
        self,
        command: str,
        platform: Optional[str] = None,
    ) -> List[Tuple[str, str]]:
        if not REQUESTS_OK:
            return []

        platform_hint = self.PLATFORM_HINTS.get((platform or "").lower(), "AOS-CX")

        queries = [
            f'"{command}" "{platform_hint}" "Command-Line Interface" site:arubanetworking.hpe.com',
            f'"{command}" "{platform_hint}" CLI Reference site:arubanetworking.hpe.com',
            f'"{command}" "AOS-CX" CLI site:arubanetworks.com',
            f'"{command}" ArubaOS CLI site:arubanetworking.hpe.com',
        ]

        seen: set = set()
        candidates: List[Tuple[str, str]] = []
        for q in queries:
            for url, title in self._duckduckgo_search(q):
                if url in seen:
                    continue
                if not any(d in url for d in self.trusted_domains):
                    continue
                # Prefer techdocs paths
                if not any(p in url for p in ("/techdocs/", "/docDisplay", "/psnow/")):
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

        # Aruba uses <pre class="codeblock">, <code>, or plain <pre>
        syntax = ""
        for css_class in ("codeblock", "syntax", "cmd"):
            elem = soup.find(class_=css_class)
            if elem:
                txt = elem.get_text().strip()
                if command.lower() in txt.lower() and len(txt) < 500:
                    syntax = txt
                    break

        if not syntax:
            for pre in soup.find_all("pre", limit=5):
                txt = pre.get_text().strip()
                if command.lower() in txt.lower() and len(txt) < 500:
                    syntax = txt
                    break

        # Description — Aruba uses <p class="p"> in DITA-converted docs
        description = ""
        for p in soup.find_all("p", limit=15):
            txt = p.get_text().strip()
            if len(txt) < 40:
                continue
            if any(skip in txt.lower() for skip in (
                "copyright", "warranty", "trademark", "hewlett packard",
                "table of contents", "links to third-party",
            )):
                continue
            description = txt
            break

        # Example output: Aruba shows it in <pre class="screen"> or <samp>
        example = ""
        for css_class in ("screen", "output"):
            elem = soup.find(class_=css_class)
            if elem:
                example = elem.get_text().strip()
                break

        # AOS-CX version mention
        version_match = re.search(
            r"AOS-CX\s+\d+\.\d+(?:\.\d+)?|ArubaOS\s+\d+(?:\.\d+)+",
            soup.get_text(),
        )
        min_version = version_match.group(0) if version_match else ""

        if not (syntax or description):
            return None

        return {
            "syntax":         self._clean_text(syntax, 500),
            "description":    self._clean_text(description, 1500),
            "example_output": self._clean_text(example, 1500),
            "min_version":    self._clean_text(min_version, 200),
            "page_title":     page_title,
        }
