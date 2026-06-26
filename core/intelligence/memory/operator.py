"""
core/intelligence/memory/operator.py
=====================================
Operator Preference Memory — learning the human it works for.

The same action can be right for one operator and wrong for another. One always
wants to review before anything touches the hub; one trusts the platform to just
fix interface-down at the edge; one only does risky work in a Saturday window;
one phrases everything as "fix" and means "diagnose first". An assistant that
doesn't learn its operator's habits stays a stranger forever. This memory
records what the operator approves, rejects, edits, and prefers, so Decision
Making can default to what THIS operator would want — and ask where they'd want
to be asked.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from core.intelligence.memory.store import MemoryStore


def _okey(operator: str, dimension: str, subject: str) -> str:
    raw = f"{(operator or 'default').lower()}|{dimension}|{subject.strip().lower()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


class OperatorPreferenceMemory(MemoryStore):
    table = "mem_operator"
    semantic = True
    columns = (
        ("operator", "TEXT"),
        ("dimension", "TEXT"),    # approval | risk_tolerance | window | phrasing | scope
        ("subject", "TEXT"),      # what it's about (a protocol, device-role, intent class)
        ("stance", "TEXT"),       # approve_auto | review_first | reject | prefer | avoid
        ("approvals", "INTEGER"),
        ("rejections", "INTEGER"),
    )

    def record_decision(self, operator: str, dimension: str, subject: str,
                        approved: bool, *, stance: str = "") -> str:
        key = _okey(operator, dimension, subject)
        ex = self._by_key(key)
        appr = int((ex or {}).get("approvals") or 0) + (1 if approved else 0)
        rej = int((ex or {}).get("rejections") or 0) + (0 if approved else 1)
        tot = appr + rej
        ratio = appr / tot if tot else 0.5
        inferred = stance or ("approve_auto" if ratio >= 0.85 and tot >= 4 else
                              "reject" if ratio <= 0.2 and tot >= 4 else "review_first")
        summary = (f"{operator or 'operator'} {dimension} «{subject}»: {inferred} "
                   f"({appr} approved / {rej} rejected)")
        return self.learn(key, summary, confidence=round(max(ratio, 1 - ratio), 4),
                          operator=(operator or "default").lower(),
                          dimension=dimension, subject=subject, stance=inferred,
                          approvals=appr, rejections=rej)

    def stance_for(self, operator: str, dimension: str, subject: str
                   ) -> Optional[Dict[str, Any]]:
        ex = self._by_key(_okey(operator, dimension, subject))
        if not ex:
            hits = self.recall_similar(subject, top_k=1,
                                       operator=(operator or "default").lower(),
                                       dimension=dimension)
            ex = hits[0] if hits else None
        if not ex:
            return None
        return {"stance": ex.get("stance"), "subject": ex.get("subject"),
                "approvals": int(ex.get("approvals") or 0),
                "rejections": int(ex.get("rejections") or 0),
                "confidence": ex.get("confidence")}

    def profile(self, operator: str = "default", limit: int = 30) -> List[Dict[str, Any]]:
        return self.top(limit=limit, operator=(operator or "default").lower())
