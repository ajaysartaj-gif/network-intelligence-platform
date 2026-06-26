"""
core/intelligence/forecasting/signals.py
=========================================
Where forecasters get their evidence.

Every signal here is read from a REAL source — the episodic operational log, the
derived memories (already fed by real outcomes), or a live engine when present —
and every read degrades gracefully to a neutral value when its source is absent,
so a forecaster never crashes for lack of a subsystem; it simply forecasts with
less evidence and says so via lower confidence.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple


def _mem():
    try:
        from core.intelligence.operational_memory import get_operational_memory
        return get_operational_memory()
    except Exception:
        return None


def _sys():
    try:
        from core.intelligence.memory import get_memory_system
        return get_memory_system()
    except Exception:
        return None


# ── reliability / failure signals ───────────────────────────────────────────
def device_failure_history(device: str, limit: int = 50) -> List[Dict[str, Any]]:
    m = _mem()
    if not m or not device:
        return []
    try:
        hist = m.device_history(device, limit=limit)
        return [h for h in hist if h.get("outcome") == "failure"]
    except Exception:
        return []


def recent_failure_rate(device: str, window_s: float = 7 * 24 * 3600) -> float:
    """Failures per day for a device over a recent window."""
    fails = device_failure_history(device)
    if not fails:
        return 0.0
    cutoff = time.time() - window_s
    recent = [f for f in fails if float(f.get("ts") or 0) >= cutoff]
    return len(recent) / max(1.0, window_s / (24 * 3600))


def mtbf_seconds(scope: str) -> float:
    s = _sys()
    if not s:
        return 0.0
    try:
        return s.temporal.mtbf_hours(scope) * 3600
    except Exception:
        return 0.0


def recurring_failures(min_count: int = 2) -> List[Dict[str, Any]]:
    m = _mem()
    if not m:
        return []
    try:
        return m.recurring_failures(min_count=min_count, limit=100)
    except Exception:
        return []


# ── change / deployment signals ─────────────────────────────────────────────
def procedure_stats(intent: str, protocol: str) -> Optional[Dict[str, Any]]:
    s = _sys()
    if not s:
        return None
    try:
        return s.procedural.best_for(intent, protocol, min_rate=0.0)
    except Exception:
        return None


def domain_competence(domain: str) -> Dict[str, Any]:
    s = _sys()
    if not s:
        return {"attempts": 0, "success_rate": 0.5, "level": "novice", "trend": 0.0}
    try:
        return s.experience.competence(domain)
    except Exception:
        return {"attempts": 0, "success_rate": 0.5, "level": "novice", "trend": 0.0}


def contraindications(probe: str) -> List[Dict[str, Any]]:
    s = _sys()
    if not s:
        return []
    try:
        return s.failure.contraindications(probe, top_k=4)
    except Exception:
        return []


def rollback_events(limit: int = 100) -> List[Dict[str, Any]]:
    m = _mem()
    if not m:
        return []
    try:
        return m.temporal(event_type="rollback", limit=limit)
    except Exception:
        return []


# ── temporal / human-factors signals ────────────────────────────────────────
def temporal_risk(scope: str) -> Dict[str, Any]:
    s = _sys()
    if not s:
        return {"elevated": False, "hour_factor": 1.0, "dow_factor": 1.0}
    try:
        return s.temporal.risk_now(scope)
    except Exception:
        return {"elevated": False, "hour_factor": 1.0, "dow_factor": 1.0}


def fatigue_factor(ts: float = 0.0) -> Tuple[float, str]:
    """Human-factors risk multiplier from time-of-day/week (aviation/medicine)."""
    lt = time.localtime(ts or time.time())
    f, why = 1.0, []
    if lt.tm_hour >= 22 or lt.tm_hour < 6:
        f *= 1.5; why.append("out-of-hours")
    if lt.tm_wday == 4 and lt.tm_hour >= 15:
        f *= 1.3; why.append("Friday afternoon")
    if lt.tm_wday >= 5:
        f *= 1.15; why.append("weekend")
    return f, ", ".join(why) or "normal hours"


def operator_recent_actions(operator: str, window_s: float = 3600) -> int:
    m = _mem()
    if not m:
        return 0
    try:
        since = time.time() - window_s
        evs = m.temporal(since=since, limit=200)
        return sum(1 for e in evs if (e.get("operator") or "") == operator)
    except Exception:
        return 0


# ── live telemetry / capacity signals ───────────────────────────────────────
def device_health_score(hostname: str) -> Optional[float]:
    """0..100 health if a telemetry engine is wired; else None."""
    try:
        from core.telemetry_engine import TelemetryEngine  # noqa
        # The engine needs state; we only read if a shared instance exposes it.
        import app
        eng = getattr(app, "telemetry_engine", None) or getattr(app, "_telemetry", None)
        if eng and hasattr(eng, "get_device_health_score"):
            hs = eng.get_device_health_score(hostname)
            return float(hs.get("score")) if isinstance(hs, dict) and "score" in hs else None
    except Exception:
        return None
    return None


def metric_series(subject: str, metric: str) -> List[Tuple[float, float]]:
    """(ts,value) history for a metric from environmental baselines' samples, if
    recorded. Returns [] when no series is available — the forecaster then says
    it cannot yet project that metric."""
    s = _sys()
    if not s:
        return []
    try:
        rows = s.environmental.fingerprint(subject, limit=50)
        out = []
        for r in rows:
            if r.get("attribute") == metric:
                series = (r.get("extra") or {}).get("series") or []
                for pt in series:
                    if isinstance(pt, (list, tuple)) and len(pt) == 2:
                        out.append((float(pt[0]), float(pt[1])))
        return sorted(out)
    except Exception:
        return []


# ── inventory / vendor / aging signals ──────────────────────────────────────
def device_meta(device: str) -> Dict[str, Any]:
    """Vendor/os/age facts from environmental + semantic memory, if learned."""
    s = _sys()
    meta: Dict[str, Any] = {}
    if not s:
        return meta
    try:
        for r in s.environmental.fingerprint(device, limit=30):
            attr = r.get("attribute")
            if attr in ("vendor", "os_version", "model", "install_date",
                        "uptime_s", "router_id"):
                meta[attr] = r.get("normal")
    except Exception:
        pass
    return meta


def vendor_failure_rate(vendor: str) -> Tuple[float, int]:
    """Historical failure fraction for a vendor across the estate."""
    s = _sys()
    if not s or not vendor:
        return 0.0, 0
    try:
        comp = s.experience.competence(f"vendor:{vendor.lower()}")
        att = int(comp.get("attempts") or 0)
        return (1 - float(comp.get("success_rate") or 1.0)), att
    except Exception:
        return 0.0, 0


# ── topology / blast-radius signals ─────────────────────────────────────────
def topology_graph(site: str = "") -> Dict[str, List[str]]:
    """Adjacency {node: [neighbors]} from the live topology cache, if built."""
    try:
        from core.topology.topology_cache import get_topology_cache
        cache = get_topology_cache()
        data = getattr(cache, "_data", {}) or {}
        adj: Dict[str, List[str]] = {}
        for snap in (data.values() if not site else [data.get(site, {})]):
            links = (snap or {}).get("links") or []
            for l in links:
                a, b = None, None
                if isinstance(l, dict):
                    a, b = l.get("source") or l.get("a"), l.get("target") or l.get("b")
                elif isinstance(l, (list, tuple)) and len(l) >= 2:
                    a, b = l[0], l[1]
                if a and b:
                    adj.setdefault(str(a), []).append(str(b))
                    adj.setdefault(str(b), []).append(str(a))
        return adj
    except Exception:
        return {}


def business_impact(entity: str) -> Dict[str, Any]:
    s = _sys()
    if not s:
        return {"criticality": 0.3, "services": [], "known": False}
    try:
        return s.business.impact_of(entity)
    except Exception:
        return {"criticality": 0.3, "services": [], "known": False}


# ── compliance / drift signals ──────────────────────────────────────────────
def last_known_good_age(device: str) -> Optional[float]:
    """Seconds since the last verified-good deployment on a device."""
    m = _mem()
    if not m or not device:
        return None
    try:
        hist = m.device_history(device, limit=50, event_type="deployment_outcome")
        good = [h for h in hist if h.get("outcome") == "success"]
        if not good:
            return None
        return time.time() - max(float(h.get("ts") or 0) for h in good)
    except Exception:
        return None
