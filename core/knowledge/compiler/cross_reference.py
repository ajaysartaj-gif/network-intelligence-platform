"""
core/knowledge/compiler/cross_reference.py
=============================================
Cross-Reference Engine — deterministic detection of RFC/CVE/vendor-bug/
field-notice references in text. Unlike general fact extraction
(facts.py), these ARE syntactically fixed, unambiguous patterns, so
regex extraction is fully reliable, not just "best effort."
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

_PATTERNS: List[Tuple[str, "re.Pattern"]] = [
    ("rfc", re.compile(r"\bRFC\s?(\d{1,5})\b", re.IGNORECASE)),
    ("cve", re.compile(r"\b(CVE-\d{4}-\d{4,7})\b", re.IGNORECASE)),
    ("cisco_bug_id", re.compile(r"\b(CSC[a-z]{2}\d{5})\b", re.IGNORECASE)),
    ("field_notice", re.compile(r"\b(FN\d{4,})\b", re.IGNORECASE)),
]


@dataclass
class Reference:
    kind: str            # "rfc" | "cve" | "cisco_bug_id" | "field_notice"
    value: str           # normalized value, e.g. "RFC2328", "CVE-2023-1234"
    context_line: str


def find_references(text: str) -> List[Reference]:
    """Scans `text` line by line (so each reference keeps its own context)
    for the reference patterns above. A line may yield multiple references
    of different kinds."""
    refs: List[Reference] = []
    for line in (text or "").splitlines():
        for kind, pattern in _PATTERNS:
            for m in pattern.finditer(line):
                value = f"RFC{m.group(1)}" if kind == "rfc" else m.group(1).upper()
                refs.append(Reference(kind=kind, value=value, context_line=line.strip()))
    return refs
