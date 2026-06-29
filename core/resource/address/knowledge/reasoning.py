"""
NRIE · Knowledge · Reasoning (descriptor)
=========================================
Declares the reasoning QUESTIONS the address domain can pose to the EXISTING
Reasoning Engine. NO AI or inference is implemented here (out of scope for this
PR) — this is a contract surface so later PRs reuse the platform reasoning rather
than build a parallel one.
"""
from __future__ import annotations
from typing import Dict

# question key -> human description (resolved by core.reasoning_layer later)
REASONING_SURFACE: Dict[str, str] = {
    "impact_of_change": "what depends on this resource (via Knowledge Graph)",
    "context_for_resource": "what business context applies to this resource",
    "applicable_standards": "which organizational standards govern this resource",
}

# explicit boundary marker for reviewers
IMPLEMENTS_AI = False
