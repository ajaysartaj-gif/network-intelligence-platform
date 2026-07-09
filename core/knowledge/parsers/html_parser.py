"""
core/knowledge/parsers/html_parser.py
======================================
Strip a locally-saved HTML document (a scraped/archived vendor doc page,
an internal wiki export) down to its readable text. Reuses BeautifulSoup,
already a platform dependency for the live vendor fetchers.
"""
from __future__ import annotations

from typing import Optional


def extract(path: str) -> Optional[str]:
    from bs4 import BeautifulSoup  # local import: optional dependency

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        html = f.read()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    text = "\n".join(lines)
    return text or None
