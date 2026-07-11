"""
core/knowledge/doc_downloader/classify.py
==========================================
One shared doc-type classifier, reused by every vendor source so the
pdf_downloads/<vendor>/<doc_type>/ hierarchy stays consistent regardless
of which source populated it.

Categories match what was asked for, with one rename made transparently:
"IOS command" -> "command_reference". IOS is Cisco's own OS name, but the
underlying category (CLI/command-syntax documentation) applies to every
vendor, not just Cisco — so the folder is named for the concept, not one
vendor's product name.
"""
from __future__ import annotations

import re
from typing import Dict, List

DOC_TYPES = ["configuration", "troubleshooting", "white_paper", "data_sheet", "command_reference"]

# Ordered most-specific-first: a title/path can match multiple keyword
# groups (e.g. "Troubleshooting Configuration Guide"), so checks run in
# priority order and the first match wins rather than scoring every
# category — troubleshooting content is rarely mis-filed as configuration
# in practice, but the reverse (a configuration guide that happens to
# mention "issues") is common enough that troubleshooting must be checked
# first.
_KEYWORDS: List[tuple] = [
    ("troubleshooting", re.compile(r"troubleshoot|tsd\b|resolving|diagnos", re.I)),
    ("command_reference", re.compile(r"command[\s_-]?reference|cli[\s_-]?reference|"
                                     r"ios[\s_-]?command|command[\s_-]?guide", re.I)),
    ("data_sheet", re.compile(r"data[\s_-]?sheet|datasheet|specifications?\b", re.I)),
    ("white_paper", re.compile(r"white[\s_-]?paper|solution[\s_-]?brief", re.I)),
    ("configuration", re.compile(r"configur|deployment|setup|getting[\s_-]?started|install", re.I)),
]


def classify_doc_type(title: str = "", path: str = "") -> str:
    """Returns one of DOC_TYPES, defaulting to "configuration" (the most
    common category in practice, and a reasonable default for a guide
    whose title/path gives no clearer signal — never silently invents a
    6th category to avoid a default)."""
    haystack = f"{title} {path}"
    for doc_type, pattern in _KEYWORDS:
        if pattern.search(haystack):
            return doc_type
    return "configuration"


def safe_filename(title: str, fallback: str, ext: str = ".pdf") -> str:
    """Sanitizes a title into a filesystem-safe filename, keeping it
    readable rather than hashing it away."""
    base = re.sub(r"[^\w\s.-]", "", title or "").strip()
    base = re.sub(r"\s+", "_", base)
    base = base[:150] or fallback
    return base if base.lower().endswith(ext) else base + ext
