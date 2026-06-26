"""
core/intelligence/memory/semantic.py
=====================================
Semantic Memory — durable, de-contextualised FACTS.

Episodic memory remembers *that something happened on a day*. Semantic memory
remembers *what is true* once the day no longer matters: "R2 is the Del1 hub",
"OSPF area 0 spans Del1 and Site2", "loopback0 sources the router-id here",
"Site2 hub is reachable only over the TCP-telnet fallback". An experienced
engineer carries hundreds of these and reasons from them instantly.

Facts are mined from repeated, consistent episodes (the same assertion seen
again and again across incidents/deployments) and reinforced each time they
recur, so a fact's confidence reflects how many independent observations back
it. Contradiction lowers confidence; sustained agreement raises it.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from core.intelligence.memory.store import MemoryStore


def _fkey(subject: str, predicate: str, obj: str) -> str:
    raw = f"{subject.strip().lower()}|{predicate.strip().lower()}|{obj.strip().lower()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


class SemanticMemory(MemoryStore):
    table = "mem_semantic"
    semantic = True
    columns = (
        ("subject", "TEXT"),     # the entity the fact is about (device/site/protocol)
        ("predicate", "TEXT"),   # relation: is_hub, sources_router_id, area, reachable_via…
        ("object", "TEXT"),      # the value
        ("scope", "TEXT"),       # 'network' (about this estate) | 'domain' (general truth)
    )

    def assert_fact(self, subject: str, predicate: str, obj: str, *,
                    scope: str = "network", confidence: float = 0.6,
                    source: str = "") -> str:
        summary = f"{subject} {predicate} {obj}".strip()
        return self.learn(
            _fkey(subject, predicate, obj), summary,
            confidence=confidence, extra={"source": source} if source else None,
            subject=(subject or "").lower(), predicate=(predicate or "").lower(),
            object=obj, scope=scope)

    def contradict(self, subject: str, predicate: str, obj: str) -> None:
        """A fact was observed to be false now — pull its confidence down."""
        ex = self._by_key(_fkey(subject, predicate, obj))
        if ex:
            self.reinforce(_fkey(subject, predicate, obj), by=0.0,
                           confidence=max(0.05, float(ex.get("confidence") or 0.5) - 0.3))

    def facts_about(self, subject: str, limit: int = 20) -> List[Dict[str, Any]]:
        return self.top(limit=limit, subject=(subject or "").lower())

    def known(self, query: str, top_k: int = 5,
              scope: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.recall_similar(query, top_k=top_k, scope=scope)
