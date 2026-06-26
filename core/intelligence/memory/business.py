"""
core/intelligence/memory/business.py
=====================================
Business / Customer Memory — the context that turns "a router" into "the router
the payments team depends on at month-end".

Pure network skill treats every device as a graph node. An experienced operator
never does: they know which links carry revenue, which customer screams if a
prefix flaps, which box is under a strict change freeze, what the SLA penalty
is. That business context is what makes risk assessment real — blast radius is
not just how many nodes are affected, but how much they MATTER. This memory
carries per-entity criticality, owners, SLAs and change windows so Risk and
Decision can weight consequences by business impact, not just topology.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional

from core.intelligence.memory.store import MemoryStore


def _ekey(entity: str) -> str:
    return hashlib.sha1((entity or "").strip().lower().encode()).hexdigest()[:16]


class BusinessMemory(MemoryStore):
    table = "mem_business"
    semantic = True
    columns = (
        ("entity", "TEXT"),        # device / site / prefix / service
        ("criticality", "REAL"),   # 0..1
        ("owner", "TEXT"),
        ("sla", "TEXT"),
        ("freeze_windows", "TEXT"),  # json list of {dow,hour_start,hour_end}
        ("services", "TEXT"),        # json list of dependent services
    )

    def set_context(self, entity: str, *, criticality: float = 0.5,
                    owner: str = "", sla: str = "",
                    freeze_windows: Optional[List[Dict[str, Any]]] = None,
                    services: Optional[List[str]] = None) -> str:
        import json
        crit_label = ("critical" if criticality >= 0.8 else "high" if criticality >= 0.6
                      else "normal" if criticality >= 0.3 else "low")
        summary = f"{entity}: {crit_label} criticality" + (f", owner {owner}" if owner else "")
        return self.learn(_ekey(entity), summary, confidence=0.8,
                          entity=(entity or "").lower(), criticality=float(criticality),
                          owner=owner, sla=sla,
                          freeze_windows=json.dumps(freeze_windows or []),
                          services=json.dumps(services or []))

    def impact_of(self, entity: str) -> Dict[str, Any]:
        ex = self._by_key(_ekey(entity))
        if not ex:
            return {"known": False, "criticality": 0.3, "owner": "",
                    "services": [], "detail": "no business context on file"}
        import json
        return {"known": True, "criticality": float(ex.get("criticality") or 0.3),
                "owner": ex.get("owner") or "", "sla": ex.get("sla") or "",
                "services": json.loads(ex.get("services") or "[]"),
                "detail": ex.get("summary")}

    def in_freeze(self, entity: str, ts: float = 0.0) -> Dict[str, Any]:
        import json
        ex = self._by_key(_ekey(entity))
        if not ex:
            return {"frozen": False, "reason": "no windows on file"}
        ts = ts or time.time()
        lt = time.localtime(ts)
        for w in json.loads(ex.get("freeze_windows") or "[]"):
            if w.get("dow", lt.tm_wday) == lt.tm_wday and \
               int(w.get("hour_start", 0)) <= lt.tm_hour < int(w.get("hour_end", 24)):
                return {"frozen": True, "reason": f"change freeze on {entity}"}
        return {"frozen": False, "reason": ""}

    def critical_entities(self, threshold: float = 0.6, limit: int = 50
                          ) -> List[Dict[str, Any]]:
        rows = [r for r in self.top(limit=200)
                if float(r.get("criticality") or 0) >= threshold]
        return rows[:limit]
