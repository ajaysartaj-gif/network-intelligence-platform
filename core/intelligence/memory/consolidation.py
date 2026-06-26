"""
core/intelligence/memory/consolidation.py
==========================================
Consolidation — the mechanism by which experience becomes expertise.

Humans don't grow expert while acting; they grow expert afterwards, when the
brain replays the day and files raw episodes into durable structure (the role of
sleep). This module is that replay. It reads the EPISODIC log (operational
memory) and updates every DERIVED memory:

  episode of a successful OSPF fix      → procedural (known-good ↑), experience
                                          (ospf competence ↑), pattern
                                          (cause→fix), trust (was confident &
                                          right), verification (which checks
                                          fired), temporal (when it happened).
  episode of a recurring failure        → failure (scar ↑), pattern
                                          (symptom→cause), experience (↓).

Two entry points:

  • record_episode(...)  — the SINGLE fan-out the app calls right after a
    verified contract. One call updates every relevant memory at once, so the
    write-path stays a one-liner and no subsystem is forgotten.

  • consolidate(...)     — a batch replay over recent episodic events, so a
    brain that accumulated raw events (e.g. before this layer existed, or from
    another instance via the shared store) is back-filled into derived memory.

Everything is best-effort and isolated: a failure in one memory never blocks the
others or the caller.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("NetBrain.Intelligence.Memory.Consolidation")

_PROTOS = ("ospf", "bgp", "eigrp", "rip", "isis", "mpls", "vlan",
           "interface", "acl", "nat", "hsrp", "vrrp", "stp", "dhcp", "ntp")


def _proto_from(text: str) -> str:
    t = (text or "").lower()
    return next((p for p in _PROTOS if p in t), "")


def _domain_from(intent: str, protocol: str) -> str:
    return protocol or _proto_from(intent) or "general"


class ConsolidationEngine:
    """Reads episodes, writes expertise. Holds no state but the memory handles."""

    def __init__(self, system: Any):
        self.sys = system     # MemorySystem facade (lazy handles to each store)

    # ── the one-call fan-out after a verified change ─────────────────────────
    def record_episode(
        self, *, intent: str, device: str, protocol: str = "", site: str = "",
        success: bool, commands: Optional[List[str]] = None,
        conditions: Optional[List[Dict[str, Any]]] = None,
        signature: str = "", operator: str = "", stated_confidence: float = 0.0,
        ts: float = 0.0,
    ) -> Dict[str, Any]:
        ts = ts or time.time()
        commands = commands or []
        conditions = conditions or []
        protocol = protocol or _proto_from(intent)
        domain = _domain_from(intent, protocol)
        touched: List[str] = []

        def _try(name, fn):
            try:
                fn()
                touched.append(name)
            except Exception as exc:
                logger.debug(f"consolidate {name}: {exc}")

        # procedural: reinforce the known-good (or down-rate on failure)
        _try("procedural", lambda: self.sys.procedural.learn_outcome(
            intent, protocol, commands, success, device=device))

        # experience: competence in this domain moves
        _try("experience", lambda: self.sys.experience.log(domain, success))

        # temporal: this domain's event rhythm + per-device failure rhythm
        _try("temporal", lambda: self.sys.temporal.observe_event(
            f"domain:{domain}", ts=ts, is_failure=not success))
        if not success and device:
            _try("temporal_dev", lambda: self.sys.temporal.observe_event(
                f"device:{device.lower()}", ts=ts, is_failure=True))

        # verification: which checks discriminated?
        for c in conditions:
            verdict = str(c.get("verdict") or "").lower()
            informative = verdict in ("pass", "fail")
            cmd = c.get("check_command") or c.get("command") or ""
            if cmd:
                _try("verification", lambda cmd=cmd, inf=informative:
                     self.sys.verification.record_check(cmd, protocol, informative=inf))

        # trust: was the platform's stated confidence borne out?
        if stated_confidence > 0:
            _try("trust", lambda: self.sys.trust.record(domain, stated_confidence, success))

        # pattern + failure: learn cause→fix on success, scars on failure
        failed = [c for c in conditions if str(c.get("verdict") or "").lower() == "fail"]
        if success and commands:
            fixtext = "; ".join(commands[:4])
            _try("pattern", lambda: self.sys.pattern.observe(
                "cause_fix", intent, fixtext, protocol=protocol, confidence=0.6))
        if not success:
            harm = "; ".join((c.get("reason") or c.get("description") or "")
                             for c in failed) or "change did not satisfy its post-conditions"
            _try("failure", lambda: self.sys.failure.record_scar(
                intent, f"{protocol or 'generic'} on {device or 'device'}",
                harm, signature=signature, severity=0.65))
            for c in failed:
                desc = c.get("description") or ""
                if desc:
                    _try("pattern_sym", lambda desc=desc: self.sys.pattern.observe(
                        "symptom_cause", desc, intent, protocol=protocol, confidence=0.5))

        # operator preference: their approve/reject teaches their habits
        if operator:
            _try("operator", lambda: self.sys.operator.record_decision(
                operator, "approval", f"{protocol or 'generic'}:{_class_intent(intent)}",
                approved=success))

        return {"ts": ts, "domain": domain, "success": success, "updated": touched}

    # ── batch replay over the episodic log ───────────────────────────────────
    def consolidate(self, since_s: float = 30 * 24 * 3600,
                    limit: int = 1000) -> Dict[str, Any]:
        try:
            from core.intelligence.operational_memory import get_operational_memory
            mem = get_operational_memory()
        except Exception as exc:
            return {"ok": False, "error": f"episodic log unavailable: {exc}"}

        since = time.time() - since_s
        events = mem.temporal(since=since, limit=limit, newest_first=False)
        seen_sig = set()
        n = 0
        for e in events:
            et = e.get("event_type")
            intent = e.get("intent") or e.get("summary") or ""
            device = e.get("device") or ""
            protocol = e.get("protocol") or _proto_from(intent)
            success = e.get("outcome") == "success"
            ts = float(e.get("ts") or 0)

            if et in ("deployment_outcome", "remediation", "verification_result"):
                # avoid double-counting: one consolidation per (signature, ts-bucket)
                tag = (e.get("signature", ""), int(ts // 60))
                if tag in seen_sig:
                    continue
                seen_sig.add(tag)
                cmds = _extract_commands(e.get("detail") or "")
                self.record_episode(
                    intent=intent, device=device, protocol=protocol,
                    site=e.get("site", ""), success=success, commands=cmds,
                    signature=e.get("signature", ""), ts=ts)
                n += 1
            elif et == "recurring_failure":
                try:
                    self.sys.failure.record_scar(
                        intent, f"{protocol or 'generic'} on {device or 'device'}",
                        e.get("summary", "recurring failure"),
                        signature=e.get("signature", ""), severity=0.8)
                except Exception:
                    pass
            elif et == "root_cause":
                try:
                    self.sys.pattern.observe("symptom_cause", intent,
                                             e.get("summary", ""), protocol=protocol)
                except Exception:
                    pass

        return {"ok": True, "episodes_consolidated": n,
                "events_scanned": len(events)}


def _class_intent(intent: str) -> str:
    """A coarse class for an intent so operator habits generalise."""
    t = (intent or "").lower()
    for verb in ("add", "remove", "fix", "configure", "enable", "disable",
                 "save", "rollback", "deploy", "change", "create", "delete"):
        if verb in t:
            return verb
    return "change"


def _extract_commands(detail: str) -> List[str]:
    """Pull a command body back out of an episodic detail blob, if present."""
    if not detail or "Commands:" not in detail:
        return []
    block = detail.split("Commands:", 1)[1]
    block = block.split("Post-conditions:", 1)[0]
    cmds = [ln.strip() for ln in block.splitlines() if ln.strip()]
    return cmds[:50]
