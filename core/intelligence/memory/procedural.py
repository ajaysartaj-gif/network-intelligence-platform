"""
core/intelligence/memory/procedural.py
=======================================
Procedural Memory — HOW to do things; the platform's hands.

Semantic memory knows that OSPF needs matching MTU; procedural memory knows the
exact command sequence that fixed an MTU mismatch on IOS last time, and that it
worked 9 times out of 10. This is the engineer who, faced with a familiar task,
doesn't re-derive it from first principles — they reach for the procedure their
fingers already know, and trust it in proportion to how often it has worked.

A procedure is keyed by (protocol, normalised intent). Each successful contract
reinforces it and refreshes its known-good command body; each failure of the
same intent lowers its success rate. Recall returns the highest-success
procedure for an intent so Decision Making can prefer a proven path over a
freshly-generated guess.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from core.intelligence.memory.store import MemoryStore


def _norm_intent(intent: str) -> str:
    return re.sub(r"\d+", "#", (intent or "").strip().lower())


def _pkey(protocol: str, intent: str) -> str:
    raw = f"{(protocol or '').lower()}::{_norm_intent(intent)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


class ProceduralMemory(MemoryStore):
    table = "mem_procedural"
    semantic = True
    columns = (
        ("protocol", "TEXT"),
        ("intent", "TEXT"),
        ("commands", "TEXT"),    # json: the known-good command body
        ("successes", "INTEGER"),
        ("attempts", "INTEGER"),
    )

    def learn_outcome(self, intent: str, protocol: str, commands: List[str],
                      success: bool, device: str = "") -> str:
        key = _pkey(protocol, intent)
        ex = self._by_key(key)
        succ = int((ex or {}).get("successes") or 0) + (1 if success else 0)
        att = int((ex or {}).get("attempts") or 0) + 1
        rate = succ / att if att else 0.0
        # keep the command body from the most recent SUCCESS; never overwrite a
        # known-good body with a failed attempt's commands.
        body = commands
        if not success and ex:
            try:
                body = json.loads(ex.get("commands") or "[]") or commands
            except Exception:
                body = commands
        summary = f"Procedure for «{intent}» ({protocol or 'generic'}): {rate:.0%} success over {att}"
        return self.learn(
            key, summary, confidence=round(rate, 4),
            protocol=(protocol or "").lower(), intent=intent,
            commands=json.dumps(body), successes=succ, attempts=att,
            extra={"last_device": device})

    def best_for(self, intent: str, protocol: str = "",
                 min_rate: float = 0.5) -> Optional[Dict[str, Any]]:
        ex = self._by_key(_pkey(protocol, intent))
        if not ex:
            # fall back to semantic recall across procedures
            hits = self.recall_similar(intent, top_k=1)
            ex = hits[0] if hits else None
            if not ex:
                return None
        att = int(ex.get("attempts") or 0)
        succ = int(ex.get("successes") or 0)
        rate = succ / att if att else 0.0
        if rate < min_rate:
            return None
        try:
            cmds = json.loads(ex.get("commands") or "[]")
        except Exception:
            cmds = []
        return {"intent": ex.get("intent"), "protocol": ex.get("protocol"),
                "commands": cmds, "success_rate": round(rate, 3),
                "attempts": att, "successes": succ}

    def playbooks(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.top(limit=limit)
