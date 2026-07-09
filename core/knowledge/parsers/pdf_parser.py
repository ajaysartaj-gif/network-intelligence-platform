"""
core/knowledge/parsers/pdf_parser.py
====================================
Extract plain text from a PDF file (vendor whitepapers, design guides,
TAC-case exports) so it can be chunked/embedded like any other document.
"""
from __future__ import annotations

from typing import Optional


def extract(path: str) -> Optional[str]:
    """Return the concatenated text of every page, or None if unreadable."""
    from pypdf import PdfReader  # local import: optional dependency

    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    return text or None
