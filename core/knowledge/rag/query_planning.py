"""
core/knowledge/rag/query_planning.py
=====================================
Multi-hop query decomposition.

A single embedding search treats a compound question ("why is the OSPF
neighbor down AND what's the vendor-recommended fix") as one vector — the
two sub-questions compete for the same top-k slots and neither gets a
clean, focused retrieval pass. Decomposing into independent sub-queries
first, searching each separately, then merging results gives each
sub-question its own shot at the corpus.

Same pluggable-degradation philosophy as embedder.py/reranker.py: an
optional ai_call does the actual decomposition; without one (or on judge
failure/degenerate output), the query is treated as a single hop — a
one-item plan is still a completely valid multi-hop plan, so this always
degrades to "just search it" rather than blocking.
"""
from __future__ import annotations

import json
import re
from typing import Callable, List, Optional


def _strip_json_fence(raw: str) -> str:
    return re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.M).strip()


def decompose_query(query: str, ai_call: Optional[Callable[[str], str]] = None,
                    max_subqueries: int = 3) -> List[str]:
    """
    Split a compound question into independently-searchable sub-queries.
    Returns [query] unchanged if ai_call is absent, raises, returns
    unparseable output, or genuinely decides the question is already atomic.
    """
    query = (query or "").strip()
    if not query:
        return []
    if ai_call is None:
        return [query]
    try:
        prompt = (
            "Does this question contain MULTIPLE distinct things to look up "
            "(not just one question phrased with several clauses)? If yes, "
            "split it into independent, separately-searchable sub-questions "
            f"(at most {max_subqueries}). If it's really one question, "
            "return it unchanged as the only item.\n\n"
            f"QUESTION: {query}\n\n"
            'STRICT JSON: {"subqueries": ["..."]}'
        )
        d = json.loads(_strip_json_fence(ai_call(prompt) or ""))
        subs = [str(s).strip() for s in d.get("subqueries", []) if str(s).strip()]
        return subs[:max_subqueries] if subs else [query]
    except Exception:
        return [query]
