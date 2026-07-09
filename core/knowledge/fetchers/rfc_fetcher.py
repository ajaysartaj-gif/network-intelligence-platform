"""
core/knowledge/fetchers/rfc_fetcher.py
=======================================
IETF RFC fetcher. RFCs aren't vendor/command-scoped like the VendorFetcher
subclasses (there's no "vendor" or CLI command to look up), so this is a
small standalone module rather than a VendorFetcher — same trusted-domain
and size-cap discipline as core/knowledge/fetchers/base_fetcher.py.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, Optional

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

logger = logging.getLogger("NetBrain.Knowledge.RFCFetcher")

TRUSTED_DOMAIN = "rfc-editor.org"
HTTP_TIMEOUT = 10
MAX_PAGE_SIZE = 500_000
USER_AGENT = "NetBrain-AI/1.0 (network-intelligence-platform)"


def fetch_rfc_text(number: int) -> Optional[Dict[str, str]]:
    """
    Fetch the plain-text body of RFC `number` from rfc-editor.org.
    Returns {"title": ..., "content": ...} or None on failure.
    """
    if not REQUESTS_OK:
        logger.warning("requests not installed — RFC fetch disabled")
        return None

    url = f"https://www.rfc-editor.org/rfc/rfc{int(number)}.txt"
    if TRUSTED_DOMAIN not in url:
        return None

    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT,
                         headers={"User-Agent": USER_AGENT}, stream=True)
        if r.status_code != 200:
            logger.info(f"RFC {number}: HTTP {r.status_code}")
            return None

        content = b""
        for chunk in r.iter_content(chunk_size=8192):
            content += chunk
            if len(content) > MAX_PAGE_SIZE:
                logger.info(f"RFC {number}: too large, aborting")
                return None

        text = content.decode("utf-8", errors="ignore").strip()
        if not text:
            return None

        # First non-blank line after the RFC boilerplate header is usually
        # the title; fall back to a generic label if the format is unusual.
        title_match = re.search(r"\n\s*\n\s*(.+?)\n", text[:2000])
        title = title_match.group(1).strip() if title_match else f"RFC {number}"

        return {"title": title, "content": text}

    except requests.RequestException as exc:
        logger.info(f"RFC {number}: fetch error: {exc}")
        return None
