"""
core/intelligence/memory/episodic.py
=====================================
Episodic Recall — remembering specific past *cases* as whole stories.

The OperationalMemory log already stores individual events. But an engineer
doesn't recall an outage as twelve disconnected log lines — they recall the
EPISODE: "the time the Site2 hub went unreachable, we found it was the telnet
fallback, we switched transport and it came back." This layer reconstructs those
episodes by stitching related events (shared signature / device / time-window)
into a single narrated case, and finds the most similar PAST case to a present
situation — case-based reasoning, the way experience is actually reused.

It owns no new store: it reads the episodic substrate (operational_memory) and
composes. That keeps one source of truth for raw events.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


def _mem():
    try:
        from core.intelligence.operational_memory import get_operational_memory
        return get_operational_memory()
    except Exception:
        return None


class EpisodicRecall:
    def __init__(self, window_s: float = 6 * 3600):
        self.window_s = window_s

    def similar_cases(self, situation: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """Find past situations like this one and return them as narrated cases."""
        mem = _mem()
        if not mem:
            return []
        seeds = mem.similar(situation, top_k=top_k * 2)
        cases, seen = [], set()
        for s in seeds:
            sig = s.get("signature") or ""
            anchor = (sig, s.get("device", ""))
            if anchor in seen:
                continue
            seen.add(anchor)
            cases.append(self._build_case(s))
            if len(cases) >= top_k:
                break
        return cases

    def case_for_signature(self, signature: str) -> Optional[Dict[str, Any]]:
        mem = _mem()
        if not mem or not signature:
            return None
        rows = mem.by_signature(signature, limit=50)
        if not rows:
            return None
        return self._narrate(signature, rows)

    def _build_case(self, seed: Dict[str, Any]) -> Dict[str, Any]:
        mem = _mem()
        sig = seed.get("signature") or ""
        related: List[Dict[str, Any]] = []
        if sig and mem:
            related = mem.by_signature(sig, limit=50)
        if not related and mem and seed.get("device"):
            ts = float(seed.get("ts") or time.time())
            hist = mem.device_history(seed["device"], limit=50)
            related = [h for h in hist
                       if abs(float(h.get("ts") or 0) - ts) <= self.window_s]
        related = related or [seed]
        return self._narrate(sig or seed.get("device", "case"), related)

    @staticmethod
    def _narrate(anchor: str, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        evs = sorted(events, key=lambda e: float(e.get("ts") or 0))
        by_type = {}
        for e in evs:
            by_type.setdefault(e.get("event_type", "event"), []).append(e)
        resolved = any(e.get("outcome") == "success"
                       for e in by_type.get("remediation", []) + by_type.get("deployment_outcome", []))
        root = next((e.get("summary") for e in by_type.get("root_cause", [])), "")
        fix = next((e.get("detail") or e.get("summary")
                    for e in by_type.get("remediation", []) if e.get("outcome") == "success"), "")
        device = next((e.get("device") for e in evs if e.get("device")), "")
        story = " → ".join(e.get("summary", "") for e in evs[:8] if e.get("summary"))
        return {"anchor": anchor, "device": device, "events": len(evs),
                "resolved": resolved, "root_cause": root, "known_fix": fix,
                "story": story,
                "started": evs[0].get("ts") if evs else None,
                "ended": evs[-1].get("ts") if evs else None}
