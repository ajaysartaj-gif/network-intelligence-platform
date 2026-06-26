"""
core/intelligence/autonomy/faculties.py
========================================
The cognitive faculties that separate an autonomous system from an automation
script. Each is grounded in the platform's real organs — the capability
registry (what it can do), the memory system (what it has learned), and the
forecasting engine (what it expects) — never in stubs.

  SelfModel          — self-awareness: what am I, what can I do, how good am I?
  SelfMonitor        — self-monitoring: my own vital signs.
  SelfDiagnosis      — self-diagnosis: what is wrong with ME and why?
  SelfRecovery       — self-recovery: bounded repair of my own faults.
  SelfProtection     — self-protection: circuit breakers and tripwires.
  SelfOptimizer      — self-optimization: tune my own parameters from results.
  SelfVerifier       — self-verification: did my action actually achieve its end?
  GoalManager        — goal management: pursue standing objectives, not events.
  ResourceGovernor   — resource awareness: act within budgets.
  TimeContext        — time awareness: know when now is a good/bad time.
  PolicyEngine       — policy awareness: the safety envelope.
  Prioritizer        — self-prioritization: do the most important thing first.
  Planner            — self-planning: turn a goal into an ordered plan.
  Scheduler          — self-scheduling: choose cadence; defer to safe windows.
  Coordinator        — self-coordination: don't let concurrent actions collide.
  AutonomyGovernor   — earned authority: the effective autonomy level per domain.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from core.intelligence.autonomy.base import (
    AutonomyFaculty, FacultySpec, AutonomyLevel, autonomy_ceiling,
    Goal, Action, Decision, Verdict,
)


# ── lazy organ accessors ─────────────────────────────────────────────────────
def _caps():
    from core.intelligence.capability_model import get_capability_registry
    return get_capability_registry()


def _sys():
    from core.intelligence.memory import get_memory_system
    return get_memory_system()


def _pred():
    from core.intelligence.forecasting import get_prediction_engine
    return get_prediction_engine()


def _reasoning():
    from core.intelligence.reasoning import get_reasoning_registry
    return get_reasoning_registry()


# ════════════════════════════════════════════════════════════════════════════
# SELF-AWARENESS
# ════════════════════════════════════════════════════════════════════════════
class SelfModel(AutonomyFaculty):
    def __init__(self):
        super().__init__(FacultySpec(
            "self_model", "Self Model",
            "Knows its own capabilities, competence and current limits."))

    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        report = _caps().report()
        active = [c["key"] for c in report if c["status"] == "active"]
        partial = [c["key"] for c in report if c["status"] == "partial"]
        planned = [c["key"] for c in report if c["status"] in ("planned", "error")]
        domain = ctx.get("protocol") or ctx.get("domain") or "general"
        try:
            comp = _sys().experience.competence(domain)
        except Exception:
            comp = {"level": "unknown", "success_rate": 0.0, "autonomy_ok": False}
        return {"active": active, "partial": partial, "not_ready": planned,
                "n_active": len(active), "n_total": len(report),
                "competence": comp,
                "self_summary": f"{len(active)}/{len(report)} capabilities active; "
                                f"{comp.get('level')} at {domain}"}


# ════════════════════════════════════════════════════════════════════════════
# SELF-MONITORING
# ════════════════════════════════════════════════════════════════════════════
class SelfMonitor(AutonomyFaculty):
    def __init__(self):
        super().__init__(FacultySpec(
            "self_monitor", "Self Monitor",
            "Watches the platform's own vital signs each cycle."))
        self._latencies: List[float] = []
        self._cycle_errors = 0
        self._cycles = 0

    def observe_cycle(self, duration_s: float, errored: bool) -> None:
        self._cycles += 1
        self._latencies.append(duration_s)
        self._latencies = self._latencies[-50:]
        if errored:
            self._cycle_errors += 1

    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        report = _caps().report()
        degraded = [c["key"] for c in report if c["status"] in ("error", "degraded")]
        partial = [c["key"] for c in report if c["status"] == "partial"]
        try:
            hr = _sys().prediction.hit_rate()
        except Exception:
            hr = {"resolved": 0, "hit_rate": 0.0}
        mean_lat = sum(self._latencies) / len(self._latencies) if self._latencies else 0.0
        err_rate = self._cycle_errors / max(1, self._cycles)
        world = {
            "open_incidents": ctx.get("open_incidents", 0),
            "critical_devices": ctx.get("critical_devices", 0),
            "anomalies": ctx.get("anomalies", 0),
        }
        vitals_ok = (not degraded) and err_rate < 0.3
        return {"vitals_ok": vitals_ok, "degraded_capabilities": degraded,
                "partial_capabilities": partial, "cycle_error_rate": round(err_rate, 3),
                "mean_cycle_latency_s": round(mean_lat, 3),
                "prediction_hit_rate": hr.get("hit_rate", 0.0),
                "resolved_predictions": hr.get("resolved", 0), "world": world}


# ════════════════════════════════════════════════════════════════════════════
# SELF-DIAGNOSIS
# ════════════════════════════════════════════════════════════════════════════
class SelfDiagnosis(AutonomyFaculty):
    def __init__(self):
        super().__init__(FacultySpec(
            "self_diagnosis", "Self Diagnosis",
            "Diagnoses the platform's own degradation and its likely cause."))

    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        vitals = ctx.get("vitals") or {}
        problems: List[Dict[str, Any]] = []
        for key in vitals.get("degraded_capabilities", []):
            cap = _caps().get(key)
            unmet = _caps().unmet_dependencies(key) if cap else []
            cause = (f"unmet dependencies: {', '.join(unmet)}" if unmet
                     else "probe reports degraded/error")
            problems.append({"subsystem": key, "cause": cause,
                             "remedy": ("restore dependencies" if unmet
                                        else "reinitialise subsystem")})
        if vitals.get("cycle_error_rate", 0) >= 0.3:
            problems.append({"subsystem": "control_loop",
                             "cause": "elevated cycle error rate",
                             "remedy": "drop to safe mode and recover"})
        hr = vitals.get("prediction_hit_rate", 1.0)
        if vitals.get("resolved_predictions", 0) >= 8 and hr < 0.5:
            problems.append({"subsystem": "forecasting",
                             "cause": f"calibration drift (hit-rate {hr:.0%})",
                             "remedy": "widen uncertainty; re-consolidate memory"})
        return {"healthy": not problems, "problems": problems,
                "diagnosis": ("nominal" if not problems
                              else f"{len(problems)} self-fault(s) detected")}


# ════════════════════════════════════════════════════════════════════════════
# SELF-RECOVERY  (bounded, safe, internal only)
# ════════════════════════════════════════════════════════════════════════════
class SelfRecovery(AutonomyFaculty):
    def __init__(self):
        super().__init__(FacultySpec(
            "self_recovery", "Self Recovery",
            "Repairs the platform's own faults within safe, bounded actions."))

    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        problems = ctx.get("problems") or []
        taken: List[str] = []
        for p in problems:
            sub = p.get("subsystem")
            try:
                if sub == "forecasting":
                    # re-consolidate experience so calibration can recover.
                    _sys().consolidate(since_s=14 * 24 * 3600, limit=500)
                    taken.append("re-consolidated memory for forecasting")
                elif sub in ("memory", "learning") or str(sub).startswith("memory."):
                    _sys().consolidate(since_s=7 * 24 * 3600, limit=300)
                    taken.append(f"re-consolidated {sub}")
                # control_loop / external subsystems are NOT self-repaired here;
                # they trip self-protection instead (safety: don't poke the net).
            except Exception as exc:
                taken.append(f"recovery of {sub} failed: {exc}")
        return {"recovered": bool(taken), "actions": taken}


# ════════════════════════════════════════════════════════════════════════════
# SELF-PROTECTION  (circuit breaker / tripwires)
# ════════════════════════════════════════════════════════════════════════════
class SelfProtection(AutonomyFaculty):
    def __init__(self, max_consecutive_failures: int = 3,
                 error_rate_trip: float = 0.5):
        super().__init__(FacultySpec(
            "self_protection", "Self Protection",
            "Trips a circuit breaker that halts autonomous change on danger."))
        self.max_consecutive_failures = max_consecutive_failures
        self.error_rate_trip = error_rate_trip
        self._consecutive_failures = 0
        self._tripped = False
        self._tripped_reason = ""
        self._tripped_ts = 0.0
        self.cooldown_s = 1800.0

    def record_action_result(self, success: bool) -> None:
        if success:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.max_consecutive_failures:
                self.trip(f"{self._consecutive_failures} consecutive action failures")

    def trip(self, reason: str) -> None:
        self._tripped = True
        self._tripped_reason = reason
        self._tripped_ts = time.time()

    def reset(self) -> None:
        self._tripped = False
        self._tripped_reason = ""
        self._consecutive_failures = 0

    @property
    def tripped(self) -> bool:
        # auto-reset after cooldown so the platform can cautiously resume.
        if self._tripped and (time.time() - self._tripped_ts) > self.cooldown_s:
            self.reset()
        return self._tripped

    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        vitals = ctx.get("vitals") or {}
        if vitals.get("cycle_error_rate", 0) >= self.error_rate_trip:
            self.trip(f"cycle error rate {vitals.get('cycle_error_rate'):.0%}")
        return {"tripped": self.tripped, "reason": self._tripped_reason,
                "consecutive_failures": self._consecutive_failures,
                "mode": "safe/observe-only" if self.tripped else "normal"}


# ════════════════════════════════════════════════════════════════════════════
# SELF-OPTIMIZATION
# ════════════════════════════════════════════════════════════════════════════
class SelfOptimizer(AutonomyFaculty):
    def __init__(self):
        super().__init__(FacultySpec(
            "self_optimizer", "Self Optimizer",
            "Tunes its own parameters (cadence, thresholds) from results."))
        # live, self-tuned parameters with safe defaults and bounds.
        self.params = {"cycle_interval_s": 60.0, "risk_gate_threshold": 0.25,
                       "max_actions_per_cycle": 3}
        self._bounds = {"cycle_interval_s": (15.0, 900.0),
                        "risk_gate_threshold": (0.1, 0.6),
                        "max_actions_per_cycle": (1, 8)}

    def _clamp(self, k, v):
        lo, hi = self._bounds[k]
        return max(lo, min(hi, v))

    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        vitals = ctx.get("vitals") or {}
        changes = {}
        # if the loop is erroring or the world is calm, slow down; if busy, speed up.
        world = vitals.get("world") or {}
        busy = (world.get("anomalies", 0) + world.get("open_incidents", 0)) > 0
        if vitals.get("cycle_error_rate", 0) >= 0.3:
            new = self._clamp("cycle_interval_s", self.params["cycle_interval_s"] * 1.5)
            if new != self.params["cycle_interval_s"]:
                changes["cycle_interval_s"] = new
        elif busy:
            new = self._clamp("cycle_interval_s", self.params["cycle_interval_s"] * 0.8)
            if new != self.params["cycle_interval_s"]:
                changes["cycle_interval_s"] = new
        else:
            new = self._clamp("cycle_interval_s", self.params["cycle_interval_s"] * 1.1)
            if new != self.params["cycle_interval_s"]:
                changes["cycle_interval_s"] = new
        # tighten the risk gate if our forecasts have been poorly calibrated.
        hr = vitals.get("prediction_hit_rate", 1.0)
        if vitals.get("resolved_predictions", 0) >= 8 and hr < 0.5:
            new = self._clamp("risk_gate_threshold",
                              self.params["risk_gate_threshold"] * 0.8)
            if new != self.params["risk_gate_threshold"]:
                changes["risk_gate_threshold"] = round(new, 3)
        self.params.update(changes)
        return {"params": dict(self.params), "adjusted": changes}


# ════════════════════════════════════════════════════════════════════════════
# SELF-VERIFICATION
# ════════════════════════════════════════════════════════════════════════════
class SelfVerifier(AutonomyFaculty):
    def __init__(self):
        super().__init__(FacultySpec(
            "self_verifier", "Self Verifier",
            "Confirms that its own actions actually achieved their intent."))

    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        # consumes a contract-like result if present (the outcome contract engine
        # already proves end-state). Otherwise reports 'unverified'.
        contract = ctx.get("contract")
        if contract is not None:
            satisfied = bool(getattr(contract, "satisfied", False))
            return {"verified": satisfied,
                    "detail": getattr(contract, "summary", ""),
                    "method": "outcome contract"}
        device = ctx.get("device", "")
        intent = ctx.get("intent", "")
        if device and intent:
            try:
                hist = _sys().episodic.similar_cases(f"{intent} {device}", top_k=1)
                if hist:
                    return {"verified": hist[0].get("resolved", False),
                            "detail": hist[0].get("story", ""), "method": "episodic"}
            except Exception:
                pass
        return {"verified": None, "detail": "no verifiable artifact", "method": "none"}


# ════════════════════════════════════════════════════════════════════════════
# GOAL MANAGEMENT
# ════════════════════════════════════════════════════════════════════════════
class GoalManager(AutonomyFaculty):
    def __init__(self):
        super().__init__(FacultySpec(
            "goal_manager", "Goal Manager",
            "Maintains standing objectives and tracks their progress."))
        self.goals: Dict[str, Goal] = {}
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        for g in [
            Goal("health", "Keep critical devices healthy", 0.9, success_metric="0 critical devices"),
            Goal("incidents", "Drive open incidents to resolution", 0.8, success_metric="0 open incidents"),
            Goal("compliance", "Keep configuration within policy", 0.6, success_metric="no drift"),
            Goal("calibration", "Keep the platform's own forecasts calibrated", 0.5, success_metric="hit-rate >= 0.7"),
            Goal("safety", "Never cause an avoidable outage", 1.0, success_metric="0 self-caused outages"),
        ]:
            self.goals[g.key] = g

    def add_goal(self, goal: Goal) -> None:
        self.goals[goal.key] = goal

    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        world = ctx.get("world") or (ctx.get("vitals") or {}).get("world") or {}
        crit = world.get("critical_devices", 0)
        inc = world.get("open_incidents", 0)
        hr = (ctx.get("vitals") or {}).get("prediction_hit_rate", 1.0)
        # update progress from real state
        self._set("health", 1.0 if crit == 0 else max(0.0, 1 - crit / 5),
                  "met" if crit == 0 else "at_risk")
        self._set("incidents", 1.0 if inc == 0 else max(0.0, 1 - inc / 10),
                  "met" if inc == 0 else "progressing")
        self._set("calibration", min(1.0, hr / 0.7), "met" if hr >= 0.7 else "at_risk")
        ranked = sorted(self.goals.values(),
                        key=lambda g: (g.status == "at_risk", g.priority, 1 - g.progress),
                        reverse=True)
        return {"goals": [self._g(g) for g in ranked],
                "focus": self._g(ranked[0]) if ranked else None,
                "at_risk": [g.key for g in ranked if g.status == "at_risk"]}

    def _set(self, key: str, progress: float, status: str) -> None:
        g = self.goals.get(key)
        if g:
            g.progress = round(progress, 3)
            g.status = status
            g.last_update = time.time()

    @staticmethod
    def _g(g: Goal) -> Dict[str, Any]:
        return {"key": g.key, "description": g.description, "priority": g.priority,
                "status": g.status, "progress": g.progress}


# ════════════════════════════════════════════════════════════════════════════
# RESOURCE AWARENESS
# ════════════════════════════════════════════════════════════════════════════
class ResourceGovernor(AutonomyFaculty):
    def __init__(self):
        super().__init__(FacultySpec(
            "resource_governor", "Resource Governor",
            "Keeps autonomous activity within action/concurrency/AI budgets."))
        self.max_actions_per_cycle = 3
        self.max_concurrent = 2
        self.ai_calls_per_cycle = 20
        self.reset_cycle()

    def reset_cycle(self) -> None:
        self._actions_used = 0
        self._ai_used = 0

    def note_action(self) -> None:
        self._actions_used += 1

    def note_ai(self, n: int = 1) -> None:
        self._ai_used += n

    def can_spend(self, active_workflows: int = 0) -> Dict[str, Any]:
        ok = (self._actions_used < self.max_actions_per_cycle and
              active_workflows < self.max_concurrent and
              self._ai_used < self.ai_calls_per_cycle)
        reasons = []
        if self._actions_used >= self.max_actions_per_cycle:
            reasons.append("action budget exhausted this cycle")
        if active_workflows >= self.max_concurrent:
            reasons.append("max concurrent workflows reached")
        if self._ai_used >= self.ai_calls_per_cycle:
            reasons.append("AI call budget exhausted")
        return {"ok": ok, "reasons": reasons,
                "actions_used": self._actions_used,
                "ai_used": self._ai_used}

    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        return self.can_spend(ctx.get("active_workflows", 0))


# ════════════════════════════════════════════════════════════════════════════
# TIME AWARENESS
# ════════════════════════════════════════════════════════════════════════════
class TimeContext(AutonomyFaculty):
    def __init__(self):
        super().__init__(FacultySpec(
            "time_context", "Time Context",
            "Knows whether now is a good time to act (windows, risk, hours)."))

    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        device = ctx.get("device", "")
        protocol = ctx.get("protocol", "general")
        from core.intelligence.forecasting import signals as S
        fatigue, why = S.fatigue_factor()
        trisk = S.temporal_risk(f"domain:{protocol}")
        frozen = {"frozen": False, "reason": ""}
        if device:
            try:
                frozen = _sys().business.in_freeze(device)
            except Exception:
                frozen = {"frozen": False, "reason": ""}
        lt = time.localtime()
        business_hours = 0 <= lt.tm_wday <= 4 and 9 <= lt.tm_hour < 18
        good_window = (not frozen.get("frozen") and not trisk.get("elevated")
                       and fatigue <= 1.3)
        return {"good_window": good_window, "frozen": frozen.get("frozen"),
                "freeze_reason": frozen.get("reason", ""),
                "elevated_risk_time": trisk.get("elevated", False),
                "fatigue_factor": round(fatigue, 2), "fatigue_reason": why,
                "business_hours": business_hours,
                "detail": ("safe window" if good_window else
                           f"caution: {frozen.get('reason') or why}")}


# ════════════════════════════════════════════════════════════════════════════
# POLICY AWARENESS  (the safety envelope)
# ════════════════════════════════════════════════════════════════════════════
class PolicyEngine(AutonomyFaculty):
    def __init__(self):
        super().__init__(FacultySpec(
            "policy_engine", "Policy Engine",
            "Evaluates an action against the safety envelope (deny/gate/allow)."))
        self.deny_in_freeze = True
        self.contraindication_deny_weight = 0.6
        self.critical_asset_gate = 0.8     # criticality above which changes gate

    def evaluate(self, action: Action, time_ctx: Dict[str, Any]) -> List[tuple]:
        """Return a list of (verdict, reason). The strongest verdict wins."""
        out: List[tuple] = []
        if not action.changes_state or action.internal:
            return [(Verdict.ALLOW, "non-mutating/internal action")]

        # 1) change freeze → DENY
        if self.deny_in_freeze and time_ctx.get("frozen"):
            out.append((Verdict.DENY, f"change freeze: {time_ctx.get('freeze_reason')}"))

        # 2) hard contraindications from failure memory → DENY
        try:
            scars = _sys().failure.contraindications(
                f"{action.intent} {action.protocol} {action.device}", top_k=3)
            worst = max((s.get("weight", 0) for s in scars), default=0.0)
            if worst >= self.contraindication_deny_weight:
                out.append((Verdict.DENY,
                            f"contraindicated by failure memory (w={worst:.2f})"))
            elif scars:
                out.append((Verdict.GATE, f"{len(scars)} prior failures recall caution"))
        except Exception:
            pass

        # 3) critical asset → GATE (human eyes on high-value changes)
        try:
            crit = float(_sys().business.impact_of(action.device).get("criticality") or 0.3)
            if crit >= self.critical_asset_gate:
                out.append((Verdict.GATE, f"critical asset (criticality {crit:.0%})"))
        except Exception:
            pass

        # 4) elevated-risk time → GATE
        if time_ctx.get("elevated_risk_time"):
            out.append((Verdict.GATE, "historically failure-prone time window"))

        return out or [(Verdict.ALLOW, "within policy")]

    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        action = ctx.get("action")
        if not isinstance(action, Action):
            return {"verdicts": [(Verdict.ALLOW.value, "no action to evaluate")]}
        res = self.evaluate(action, ctx.get("time_ctx") or {})
        return {"verdicts": [(v.value, r) for v, r in res]}


# ════════════════════════════════════════════════════════════════════════════
# SELF-PRIORITIZATION
# ════════════════════════════════════════════════════════════════════════════
class Prioritizer(AutonomyFaculty):
    def __init__(self):
        super().__init__(FacultySpec(
            "prioritizer", "Prioritizer",
            "Ranks candidate actions by expected risk×impact and goal alignment."))

    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        candidates = ctx.get("candidates") or []   # list of Action
        goal_focus = (ctx.get("goals") or {}).get("focus") or {}
        ranked = []
        for a in candidates:
            risk = 0.0
            try:
                board = _pred().forecast(
                    {"device": a.device, "intent": a.intent, "protocol": a.protocol,
                     "site": a.site}, log=False)
                risk = max((f.risk for f in board), default=0.0)
            except Exception:
                risk = 0.0
            a.risk = round(risk, 4)
            align = 1.0 if goal_focus and goal_focus.get("key") in (a.metadata or {}).get("goals", []) else 0.5
            score = 0.7 * risk + 0.3 * align
            ranked.append((score, a))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return {"ranked": [a for _, a in ranked],
                "top": ranked[0][1] if ranked else None,
                "scores": [round(s, 3) for s, _ in ranked]}


# ════════════════════════════════════════════════════════════════════════════
# SELF-PLANNING
# ════════════════════════════════════════════════════════════════════════════
class Planner(AutonomyFaculty):
    def __init__(self):
        super().__init__(FacultySpec(
            "planner", "Planner",
            "Turns a goal/problem into an ordered, grounded plan of steps."))

    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        intent = ctx.get("intent", "")
        protocol = ctx.get("protocol", "")
        if not intent:
            return {"plan": [], "source": "none"}
        # prefer a proven procedure from memory; otherwise a safe generic plan.
        try:
            proc = _sys().procedural.best_for(intent, protocol, min_rate=0.5)
        except Exception:
            proc = None
        if proc and proc.get("commands"):
            steps = (["read current device state"] +
                     [f"apply: {c}" for c in proc["commands"]] +
                     ["verify post-conditions (outcome contract)",
                      "persist if verified, else roll back"])
            return {"plan": steps, "source": f"procedural memory "
                    f"({proc['success_rate']:.0%} over {proc['attempts']})",
                    "proven": True}
        steps = ["read current device state",
                 "generate change grounded in live facts + knowledge (RAG)",
                 "risk-check & simulate blast radius",
                 "apply change",
                 "verify post-conditions (outcome contract)",
                 "persist if verified, else roll back"]
        return {"plan": steps, "source": "generic safe template", "proven": False}


# ════════════════════════════════════════════════════════════════════════════
# SELF-SCHEDULING
# ════════════════════════════════════════════════════════════════════════════
class Scheduler(AutonomyFaculty):
    def __init__(self):
        super().__init__(FacultySpec(
            "scheduler", "Scheduler",
            "Chooses cadence and defers work to safe windows under load."))

    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        params = ctx.get("params") or {}
        interval = float(params.get("cycle_interval_s", 60.0))
        time_ctx = ctx.get("time_ctx") or {}
        vitals = ctx.get("vitals") or {}
        # defer state-changing work outside safe windows; keep observing always.
        defer_changes = not time_ctx.get("good_window", True)
        # back off when erroring or when breaker is near tripping.
        if vitals.get("cycle_error_rate", 0) >= 0.3:
            interval *= 1.5
        next_run_in = interval
        return {"next_cycle_in_s": round(next_run_in, 1),
                "defer_changes": defer_changes,
                "reason": ("safe window" if not defer_changes
                           else f"deferring changes: {time_ctx.get('detail','unsafe window')}")}


# ════════════════════════════════════════════════════════════════════════════
# SELF-COORDINATION
# ════════════════════════════════════════════════════════════════════════════
class Coordinator(AutonomyFaculty):
    def __init__(self):
        super().__init__(FacultySpec(
            "coordinator", "Coordinator",
            "Serialises concurrent actions so they don't collide on a device."))
        self._locks: Dict[str, float] = {}     # device -> lock-expiry ts
        self.lock_ttl_s = 600.0

    def acquire(self, device: str) -> bool:
        now = time.time()
        exp = self._locks.get(device, 0)
        if exp > now:
            return False
        self._locks[device] = now + self.lock_ttl_s
        return True

    def release(self, device: str) -> None:
        self._locks.pop(device, None)

    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        action = ctx.get("action")
        device = getattr(action, "device", "") if action else ctx.get("device", "")
        if not device:
            return {"clear": True, "reason": "no device scope"}
        now = time.time()
        locked = self._locks.get(device, 0) > now
        # check forecast change-conflict as a second, predictive guard.
        conflict = None
        try:
            board = _pred().forecast({"device": device, "site": ctx.get("site", "")},
                                     only=["change_conflict"], log=False)
            conflict = board[0] if board else None
        except Exception:
            conflict = None
        clear = (not locked) and (conflict is None or conflict.probability is None
                                  or conflict.probability < 0.5)
        return {"clear": clear, "locked": locked,
                "predicted_conflict": None if conflict is None else conflict.probability,
                "reason": ("clear" if clear else
                           "device locked by another action" if locked else
                           "predicted change conflict")}


# ════════════════════════════════════════════════════════════════════════════
# EARNED AUTHORITY
# ════════════════════════════════════════════════════════════════════════════
class AutonomyGovernor(AutonomyFaculty):
    def __init__(self):
        super().__init__(FacultySpec(
            "autonomy_governor", "Autonomy Governor",
            "Computes the effective, EARNED autonomy level per domain (≤ ceiling)."))

    def effective_level(self, domain: str) -> Dict[str, Any]:
        ceiling = autonomy_ceiling()
        earned = AutonomyLevel.OBSERVE
        reasons = []
        try:
            comp = _sys().experience.competence(domain)
            trust = _sys().trust._by_key(f"forecast:deployment_success")
            recurring = _sys().failure.worst(limit=5)
        except Exception:
            comp, trust, recurring = {"attempts": 0, "success_rate": 0.0, "autonomy_ok": False}, None, []

        if comp.get("attempts", 0) >= 1:
            earned = AutonomyLevel.RECOMMEND
            reasons.append("has acted at least once → may recommend")
        if comp.get("attempts", 0) >= 5 and comp.get("success_rate", 0) >= 0.6:
            earned = AutonomyLevel.APPROVE_GATED
            reasons.append("competent → may act with approval")
        if comp.get("autonomy_ok"):
            # earned bounded autonomy: many reps, high & non-declining success.
            cal_ok = True
            if trust and int(trust.get("n") or 0) >= 8:
                cal_ok = float(trust.get("confidence") or 0) >= 0.6
            if cal_ok:
                earned = AutonomyLevel.BOUNDED_AUTONOMOUS
                reasons.append("proven competence + calibration → bounded autonomy")
            else:
                reasons.append("competent but miscalibrated → held at approval-gated")
        effective = AutonomyLevel(min(int(earned), int(ceiling)))
        return {"domain": domain, "earned": earned.name, "ceiling": ceiling.name,
                "effective": effective.name, "effective_int": int(effective),
                "reasons": reasons}

    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        return self.effective_level(ctx.get("protocol") or ctx.get("domain") or "general")


def build_faculties() -> Dict[str, AutonomyFaculty]:
    facs = [SelfModel(), SelfMonitor(), SelfDiagnosis(), SelfRecovery(),
            SelfProtection(), SelfOptimizer(), SelfVerifier(), GoalManager(),
            ResourceGovernor(), TimeContext(), PolicyEngine(), Prioritizer(),
            Planner(), Scheduler(), Coordinator(), AutonomyGovernor()]
    return {f.spec.key: f for f in facs}
