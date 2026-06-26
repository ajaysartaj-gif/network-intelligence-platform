"""
core/intelligence/memory/failure.py
====================================
Failure Memory — scar tissue. What NOT to do, and why.

Procedural memory is the set of moves that work. Failure memory is the harder-
won, more valuable opposite: the moves that look reasonable and are wrong here.
"Don't bounce that interface to fix OSPF — last time it dropped the hub.",
"This 'fix' has failed 3 times; stop trying it.", "Saving before convergence
persisted a broken state." An engineer who only remembers successes keeps
walking into the same wall.

Each entry is a contraindication: an action (or signature) paired with the harm
it caused and how many times. Decision Making consults this BEFORE acting, to
veto or down-weight a candidate action the platform has been burned by.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from core.intelligence.memory.store import MemoryStore


def _hkey(action: str, context: str) -> str:
    raw = f"{action.strip().lower()}@@{context.strip().lower()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


class FailureMemory(MemoryStore):
    table = "mem_failure"
    semantic = True
    columns = (
        ("action", "TEXT"),       # the thing that went wrong / shouldn't be done
        ("context", "TEXT"),      # where it applies (protocol/device/intent)
        ("harm", "TEXT"),         # what bad thing happened
        ("signature", "TEXT"),    # ties back to the episodic recurrence signature
        ("occurrences", "INTEGER"),
        ("severity", "REAL"),     # 0..1
    )

    def record_scar(self, action: str, context: str, harm: str, *,
                    signature: str = "", severity: float = 0.6) -> str:
        key = _hkey(action, context)
        ex = self._by_key(key)
        occ = int((ex or {}).get("occurrences") or 0) + 1
        # the more often it has burned us, the more confident the veto.
        conf = min(0.98, 0.5 + 0.12 * occ)
        summary = f"AVOID «{action}» when {context}: {harm}"
        return self.learn(
            key, summary, confidence=conf,
            action=action, context=context, harm=harm, signature=signature,
            occurrences=occ, severity=float(severity))

    def contraindications(self, action_or_context: str,
                          top_k: int = 5, min_weight: float = 0.15
                          ) -> List[Dict[str, Any]]:
        """Scars relevant to a proposed action or its context."""
        return self.recall_similar(action_or_context, top_k=top_k,
                                   min_weight=min_weight)

    def worst(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self.top(limit=limit * 2)
        rows.sort(key=lambda r: (float(r.get("severity") or 0),
                                 int(r.get("occurrences") or 0)), reverse=True)
        return rows[:limit]
