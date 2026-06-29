"""
NRIE · Knowledge · Standards
============================
Declares the CATEGORIES of organizational standards the domain recognises. The
actual standard records are stored via Organizational Memory; this file is the
controlled vocabulary, not the content.
"""
from __future__ import annotations
from typing import List

ORGANIZATIONAL_STANDARD_KINDS: List[str] = [
    "engineering_standard",
    "naming_standard",
    "address_standard",
    "architecture_decision",
    "lesson_learned",
    "runbook",
    "vendor_standard",
    "business_exception",
    "compliance_policy",
]


def is_known_kind(kind: str) -> bool:
    return kind in ORGANIZATIONAL_STANDARD_KINDS
