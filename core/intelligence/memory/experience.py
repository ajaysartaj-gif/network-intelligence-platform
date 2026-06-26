"""
core/intelligence/memory/experience.py
=======================================
Experience Memory — the platform's self-model of its own competence.

An expert knows the shape of their own expertise: "I've done a thousand OSPF
adjacency fixes, I can do this in my sleep" versus "I've touched MPLS TE twice,
I should go slow and double-check." This memory accumulates, per domain
(protocol / task-type), how many times the platform has acted, how often it
succeeded, and whether it's trending better or worse — a competence curve.

Decision Making reads this to set autonomy: act confidently and maybe
autonomously where experience is deep and success high; slow down, ask, or
escalate where the platform is a novice. It is how the platform earns the right
to be trusted in a domain, instead of assuming it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.intelligence.memory.store import MemoryStore


class ExperienceMemory(MemoryStore):
    table = "mem_experience"
    semantic = False
    columns = (
        ("domain", "TEXT"),        # e.g. "ospf", "bgp", "interface", "save"
        ("attempts", "INTEGER"),
        ("successes", "INTEGER"),
        ("recent", "TEXT"),        # json ring buffer of last N outcomes (1/0)
    )
    _RING = 25

    def log(self, domain: str, success: bool) -> str:
        import json
        domain = (domain or "general").lower()
        ex = self._by_key(domain)
        att = int((ex or {}).get("attempts") or 0) + 1
        succ = int((ex or {}).get("successes") or 0) + (1 if success else 0)
        ring = []
        if ex:
            try:
                ring = json.loads(ex.get("recent") or "[]")
            except Exception:
                ring = []
        ring.append(1 if success else 0)
        ring = ring[-self._RING:]
        rate = succ / att if att else 0.0
        level = ("novice" if att < 5 else "competent" if att < 25 else
                 "proficient" if att < 100 else "expert")
        summary = f"{domain}: {level} — {succ}/{att} success ({rate:.0%})"
        return self.learn(domain, summary, confidence=round(rate, 4),
                          domain=domain, attempts=att, successes=succ,
                          recent=json.dumps(ring))

    def competence(self, domain: str) -> Dict[str, Any]:
        import json
        ex = self._by_key((domain or "general").lower())
        if not ex:
            return {"domain": domain, "attempts": 0, "success_rate": 0.0,
                    "level": "novice", "trend": 0.0, "autonomy_ok": False}
        att = int(ex.get("attempts") or 0)
        succ = int(ex.get("successes") or 0)
        rate = succ / att if att else 0.0
        try:
            ring = json.loads(ex.get("recent") or "[]")
        except Exception:
            ring = []
        half = max(1, len(ring) // 2)
        old = sum(ring[:half]) / half if ring else 0
        new = sum(ring[half:]) / max(1, len(ring) - half) if ring else 0
        level = ("novice" if att < 5 else "competent" if att < 25 else
                 "proficient" if att < 100 else "expert")
        return {"domain": domain, "attempts": att, "successes": succ,
                "success_rate": round(rate, 3), "level": level,
                "trend": round(new - old, 3),
                # earned autonomy: enough reps AND high, non-declining success.
                "autonomy_ok": att >= 25 and rate >= 0.85 and (new - old) >= -0.1}

    def profile(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [self.competence(r["domain"]) for r in self.recent(limit=limit)]
