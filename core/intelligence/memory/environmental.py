"""
core/intelligence/memory/environmental.py
==========================================
Environmental Memory — what "normal" looks like here, and the local quirks.

Two networks running the same protocols still feel different to the engineer who
runs them. They know R2's stable router-id, that Site2's hub only answers on the
TCP fallback, that R3's CPU always runs hot, that this estate uses /30s on its
cores. That tacit "feel for the place" is what lets them spot when something is
off in one glance. This memory captures per-device/per-site baselines (the
observed-normal values of facts) and explicit quirks, so anomaly detection has a
reference and generation is grounded in how THIS network actually behaves.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from core.intelligence.memory.store import MemoryStore


def _bkey(entity: str, attribute: str) -> str:
    raw = f"{entity.strip().lower()}::{attribute.strip().lower()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


class EnvironmentalMemory(MemoryStore):
    table = "mem_environmental"
    semantic = True
    columns = (
        ("entity", "TEXT"),       # device ip/hostname or site
        ("attribute", "TEXT"),    # router_id, neighbor_set, reachable_via, mtu…
        ("normal", "TEXT"),       # the observed-normal value
        ("kind", "TEXT"),         # 'baseline' | 'quirk'
        ("observations", "INTEGER"),
    )

    def baseline(self, entity: str, attribute: str, value: str, *,
                 confidence: float = 0.6) -> str:
        key = _bkey(entity, attribute)
        ex = self._by_key(key)
        obs = int((ex or {}).get("observations") or 0) + 1
        # if the value changed, this is a baseline shift worth flagging via extra.
        changed = bool(ex and (ex.get("normal") or "") and ex.get("normal") != value)
        summary = f"{entity} {attribute} normally = {value}"
        return self.learn(key, summary, confidence=confidence,
                          entity=(entity or "").lower(), attribute=attribute,
                          normal=value, kind="baseline", observations=obs,
                          extra={"baseline_shifted": changed,
                                 "previous": ex.get("normal") if changed else ""})

    def quirk(self, entity: str, note: str, *, confidence: float = 0.7) -> str:
        key = _bkey(entity, "quirk:" + note[:40])
        return self.learn(key, f"QUIRK {entity}: {note}", confidence=confidence,
                          entity=(entity or "").lower(), attribute="quirk",
                          normal=note, kind="quirk", observations=1)

    def normal_for(self, entity: str, attribute: str) -> Optional[str]:
        ex = self._by_key(_bkey(entity, attribute))
        return ex.get("normal") if ex else None

    def is_anomalous(self, entity: str, attribute: str, value: str) -> Dict[str, Any]:
        norm = self.normal_for(entity, attribute)
        if norm is None:
            return {"known": False, "anomalous": False, "normal": None}
        anom = str(norm).strip().lower() != str(value).strip().lower()
        return {"known": True, "anomalous": anom, "normal": norm, "observed": value}

    def fingerprint(self, entity: str, limit: int = 30) -> List[Dict[str, Any]]:
        return self.top(limit=limit, entity=(entity or "").lower())
