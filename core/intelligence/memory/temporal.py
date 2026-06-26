"""
core/intelligence/memory/temporal.py
=====================================
Temporal Memory — the platform's sense of WHEN.

Networks have rhythms. Failures cluster at backup windows and shift changes;
nobody wants a risky change at 4pm on a Friday; a given link has a mean time
between failures. An engineer carries all of this implicitly — "don't touch
that at month-end", "this flaps every night around 2am". This memory learns the
temporal distribution of events (by hour-of-day and day-of-week) and per-device
mean-time-between-failures, so Prediction can answer "is now an unusually risky
time?" and Decision can answer "should this wait for a safer window?".
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from core.intelligence.memory.store import MemoryStore


class TemporalMemory(MemoryStore):
    table = "mem_temporal"
    semantic = False
    columns = (
        ("scope", "TEXT"),       # 'failure' rhythm, or a device id for MTBF
        ("hour_hist", "TEXT"),   # json [24] counts
        ("dow_hist", "TEXT"),    # json [7] counts
        ("last_event_ts", "REAL"),
        ("intervals", "TEXT"),   # json: recent inter-event gaps (s) for MTBF
        ("events", "INTEGER"),
    )
    _MAXINT = 50

    def observe_event(self, scope: str, ts: float = 0.0,
                      is_failure: bool = True) -> str:
        ts = ts or time.time()
        lt = time.localtime(ts)
        ex = self._by_key(scope)
        hh = json.loads(ex.get("hour_hist")) if ex and ex.get("hour_hist") else [0] * 24
        dd = json.loads(ex.get("dow_hist")) if ex and ex.get("dow_hist") else [0] * 7
        ints = json.loads(ex.get("intervals")) if ex and ex.get("intervals") else []
        hh[lt.tm_hour] += 1
        dd[lt.tm_wday] += 1
        last = float(ex.get("last_event_ts") or 0) if ex else 0.0
        if last and ts > last:
            ints.append(ts - last)
            ints = ints[-self._MAXINT:]
        events = int((ex or {}).get("events") or 0) + 1
        mtbf = (sum(ints) / len(ints)) if ints else 0.0
        summary = (f"{scope}: {events} events; MTBF "
                   f"{(mtbf/3600):.1f}h" if mtbf else f"{scope}: {events} events")
        return self.learn(scope, summary, confidence=min(0.95, 0.4 + 0.02 * events),
                          scope=scope, hour_hist=json.dumps(hh),
                          dow_hist=json.dumps(dd), last_event_ts=ts,
                          intervals=json.dumps(ints), events=events)

    def risk_now(self, scope: str = "failure", ts: float = 0.0) -> Dict[str, Any]:
        """How unusual (busy) is the current hour/day vs this scope's history?"""
        ts = ts or time.time()
        lt = time.localtime(ts)
        ex = self._by_key(scope)
        if not ex:
            return {"scope": scope, "elevated": False, "hour_factor": 1.0,
                    "dow_factor": 1.0, "detail": "no temporal history"}
        hh = json.loads(ex.get("hour_hist") or "[]") or [0] * 24
        dd = json.loads(ex.get("dow_hist") or "[]") or [0] * 7
        hmean = (sum(hh) / 24) or 1
        dmean = (sum(dd) / 7) or 1
        hf = hh[lt.tm_hour] / hmean
        df = dd[lt.tm_wday] / dmean
        return {"scope": scope, "hour_factor": round(hf, 2),
                "dow_factor": round(df, 2),
                "elevated": hf >= 1.6 or df >= 1.6,
                "detail": f"hour×{hf:.1f}, day×{df:.1f} vs typical"}

    def mtbf_hours(self, scope: str) -> float:
        ex = self._by_key(scope)
        if not ex:
            return 0.0
        ints = json.loads(ex.get("intervals") or "[]")
        return round((sum(ints) / len(ints) / 3600), 2) if ints else 0.0
