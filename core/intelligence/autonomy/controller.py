"""
core/intelligence/autonomy/controller.py
=========================================
The Autonomic Controller — the self-directed control loop.

This composes the self-* faculties into the autonomic-computing MAPE-K loop
(Monitor → Analyze → Plan → Execute, over shared Knowledge) and exposes the one
method the rest of the platform calls before doing anything consequential:
authorize(action) → ALLOW / GATE / DENY, with reasons.

Two safety invariants are absolute:

  1. The controller NEVER pushes a network change itself. It MONITORS, ANALYSES,
     PLANS, AUTHORISES and LEARNS; the only things it EXECUTES directly are
     bounded, internal self-repairs (e.g. re-consolidating memory). Every change
     to the network still flows through the existing approval-gated deploy path,
     which now consults authorize() first. Autonomy here means better self-
     directed decisions, not unsupervised hands on the routers.

  2. When uncertain, the safe verdict wins. Tripped breaker, policy denial,
     missing knowledge, exhausted budget, unsafe time window, or an un-earned
     autonomy level all push a state-changing action to GATE or DENY — never to
     ALLOW. Authority is earned per domain and capped by a configured ceiling.

governed_run() wraps an orchestrator's run_cycle() so a normal operational cycle
becomes a self-managed one without rewriting the cycle.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from core.intelligence.autonomy.base import (
    Action, Decision, Verdict, AutonomyLevel,
)
from core.intelligence.autonomy.faculties import build_faculties

logger = logging.getLogger("NetBrain.Intelligence.Autonomy.Controller")


def _sys():
    try:
        from core.intelligence.memory import get_memory_system
        return get_memory_system()
    except Exception:
        return None


class AutonomicController:
    def __init__(self):
        self.f = build_faculties()           # persistent faculty instances
        self._executor: Optional[Callable[[Action], bool]] = None
        self._last_cycle: Dict[str, Any] = {}

    # external change executor is OPTIONAL and only used for ALLOW decisions;
    # by default there is none, so the controller authorises but never pushes.
    def attach_executor(self, fn: Callable[[Action], bool]) -> None:
        self._executor = fn

    # ── faculty shortcuts ────────────────────────────────────────────────────
    @property
    def protection(self):
        return self.f["self_protection"]

    @property
    def optimizer(self):
        return self.f["self_optimizer"]

    @property
    def resources(self):
        return self.f["resource_governor"]

    @property
    def coordinator(self):
        return self.f["coordinator"]

    @property
    def goals(self):
        return self.f["goal_manager"]

    # ════════════════════════════════════════════════════════════════════════
    # THE SAFETY GATE — every consequential action passes through here.
    # ════════════════════════════════════════════════════════════════════════
    def authorize(self, action: Action) -> Decision:
        reasons: List[str] = []

        # internal/non-mutating actions are always allowed (safe by definition).
        if action.internal or not action.changes_state:
            return Decision(Verdict.ALLOW, ["internal/non-mutating action"],
                            requires_approval=False)

        domain = action.protocol or "general"
        gate_threshold = float(self.optimizer.params.get("risk_gate_threshold", 0.25))

        # 0) circuit breaker — when tripped, no autonomous network change.
        if self.protection.tripped:
            return Decision(Verdict.DENY,
                            [f"self-protection tripped: {self.protection._tripped_reason}"],
                            level=AutonomyLevel.OBSERVE, requires_approval=True)

        # 1) time context
        time_ctx = self.f["time_context"].run(
            {"device": action.device, "protocol": domain})

        # 2) policy envelope (may DENY or GATE)
        policy_verdicts = self.f["policy_engine"].evaluate(action, time_ctx)
        if any(v == Verdict.DENY for v, _ in policy_verdicts):
            deny_reasons = [r for v, r in policy_verdicts if v == Verdict.DENY]
            return Decision(Verdict.DENY, deny_reasons, risk=action.risk,
                            requires_approval=True,
                            metadata={"policy": [(v.value, r) for v, r in policy_verdicts]})
        policy_gates = [r for v, r in policy_verdicts if v == Verdict.GATE]

        # 3) predicted risk for this action (forecasting)
        risk = action.risk
        try:
            from core.intelligence.forecasting import get_prediction_engine
            board = get_prediction_engine().forecast(
                {"device": action.device, "intent": action.intent,
                 "protocol": domain, "site": action.site}, log=False)
            risk = max([risk] + [f.risk for f in board])
        except Exception:
            pass
        action.risk = round(risk, 4)

        # 4) coordination (locks + predicted change conflict)
        coord = self.coordinator.run({"action": action, "site": action.site})
        if not coord.get("clear", True):
            return Decision(Verdict.GATE, [f"coordination: {coord.get('reason')}"],
                            risk=risk, requires_approval=True,
                            metadata={"coordination": coord})

        # 5) resource budget
        budget = self.resources.can_spend(action.metadata.get("active_workflows", 0))
        if not budget.get("ok", True):
            return Decision(Verdict.GATE, [f"resource: {', '.join(budget['reasons'])}"],
                            risk=risk, requires_approval=True,
                            metadata={"resources": budget})

        # 6) earned autonomy for this domain
        lvl_info = self.f["autonomy_governor"].effective_level(domain)
        level = AutonomyLevel(lvl_info["effective_int"])
        reasons += lvl_info["reasons"]

        # 7) decide by level × risk, with policy gates honoured
        verdict = Verdict.GATE
        if level >= AutonomyLevel.FULL:
            verdict = Verdict.ALLOW
        elif level >= AutonomyLevel.BOUNDED_AUTONOMOUS:
            if risk <= gate_threshold and not policy_gates:
                verdict = Verdict.ALLOW
                reasons.append(f"risk {risk:.0%} ≤ gate {gate_threshold:.0%}; bounded autonomy")
            else:
                verdict = Verdict.GATE
                reasons.append(f"risk {risk:.0%} > gate {gate_threshold:.0%} or policy caution")
        else:
            # OBSERVE / RECOMMEND / APPROVE_GATED → changes need a human.
            verdict = Verdict.GATE
            reasons.append(f"autonomy level {level.name}: change requires approval")

        if policy_gates:
            reasons += [f"policy: {g}" for g in policy_gates]

        return Decision(verdict, reasons, level=level, risk=round(risk, 4),
                        requires_approval=(verdict != Verdict.ALLOW),
                        metadata={"time": time_ctx, "coordination": coord,
                                  "budget": budget, "autonomy": lvl_info})

    # ════════════════════════════════════════════════════════════════════════
    # THE MAPE-K CYCLE
    # ════════════════════════════════════════════════════════════════════════
    def cycle(self, world: Optional[Dict[str, Any]] = None,
              candidates: Optional[List[Action]] = None) -> Dict[str, Any]:
        world = world or {}
        self.resources.reset_cycle()

        # ── MONITOR ──────────────────────────────────────────────────────────
        vitals = self.f["self_monitor"].run(world)

        # ── ANALYZE ──────────────────────────────────────────────────────────
        self_model = self.f["self_model"].run(world)
        diagnosis = self.f["self_diagnosis"].run({"vitals": vitals})
        goals = self.f["goal_manager"].run({"vitals": vitals, "world": world})
        protection = self.f["self_protection"].run({"vitals": vitals})

        # ── PLAN ─────────────────────────────────────────────────────────────
        params = self.optimizer.run({"vitals": vitals}).get("params", {})
        focus = (goals.get("focus") or {})
        domain = world.get("protocol") or focus.get("target") or "general"
        time_ctx = self.f["time_context"].run(
            {"device": world.get("device", ""), "protocol": domain})
        sched = self.f["scheduler"].run(
            {"params": params, "time_ctx": time_ctx, "vitals": vitals})
        prioritized = self.f["prioritizer"].run(
            {"candidates": candidates or [], "goals": goals})
        top = prioritized.get("top")
        plan = {}
        if top is not None:
            plan = self.f["planner"].run(
                {"intent": top.intent, "protocol": top.protocol})

        # ── EXECUTE (governed) ───────────────────────────────────────────────
        executed: List[Dict[str, Any]] = []
        # 1) safe internal self-repair always permitted
        if not diagnosis.get("healthy", True):
            rec = self.f["self_recovery"].run({"problems": diagnosis.get("problems", [])})
            executed.append({"action": "internal_recovery", "result": rec})

        # 2) external candidate: authorise, then act ONLY if ALLOW and an
        #    executor is attached; otherwise surface as a recommendation.
        decision_dict = None
        if top is not None and not sched.get("defer_changes", False):
            decision = self.authorize(top)
            decision_dict = {"verdict": decision.verdict.value,
                             "reasons": decision.reasons, "risk": decision.risk,
                             "level": decision.level.name}
            self._record_decision(top, decision)
            if decision.allowed and self._executor is not None:
                if self.coordinator.acquire(top.device):
                    try:
                        self.resources.note_action()
                        ok = bool(self._executor(top))
                        self.protection.record_action_result(ok)
                        executed.append({"action": "external_change",
                                         "device": top.device, "ok": ok})
                    finally:
                        self.coordinator.release(top.device)
            elif decision.allowed:
                executed.append({"action": "authorized_no_executor",
                                 "note": "ALLOW but no executor attached; "
                                         "surfaced as recommendation"})
        elif top is not None:
            decision_dict = {"verdict": "deferred",
                             "reasons": [sched.get("reason", "deferred to safe window")]}

        # ── VERIFY ───────────────────────────────────────────────────────────
        verification = self.f["self_verifier"].run(
            {"contract": world.get("contract"), "device": world.get("device", ""),
             "intent": world.get("intent", "")})

        report = {
            "ts": time.time(),
            "monitor": vitals,
            "self_model": self_model,
            "diagnosis": diagnosis,
            "goals": goals,
            "protection": protection,
            "plan": {"focus_goal": focus, "candidate": self._a(top),
                     "decision": decision_dict, "steps": plan.get("plan", []),
                     "plan_source": plan.get("source", "")},
            "schedule": sched,
            "params": params,
            "executed": executed,
            "verification": verification,
            "recommendations": self._recommendations(top, decision_dict, goals),
        }
        self._last_cycle = report
        return report

    # ── orchestrator integration: wrap a normal run_cycle() ──────────────────
    def governed_run(self, run_cycle: Callable[[], Dict[str, Any]],
                     candidates: Optional[List[Action]] = None) -> Dict[str, Any]:
        t0 = time.time()
        errored = False
        cycle_result: Dict[str, Any] = {}
        try:
            cycle_result = run_cycle() or {}
        except Exception as exc:
            errored = True
            cycle_result = {"status": "error", "error": str(exc)}
        dur = time.time() - t0
        self.f["self_monitor"].observe_cycle(dur, errored or
                                              cycle_result.get("status") == "error")
        # build the 'world' the control loop reasons over from the cycle output
        world = {
            "open_incidents": _len(cycle_result.get("operational_summary", {}),
                                   "open_incidents", cycle_result.get("incidents_created", 0)),
            "critical_devices": cycle_result.get("critical_devices", 0),
            "anomalies": cycle_result.get("anomalies_detected", 0),
        }
        governance = self.cycle(world, candidates=candidates)
        return {"cycle": cycle_result, "governance": governance,
                "next_cycle_in_s": governance["schedule"]["next_cycle_in_s"]}

    # ── helpers ──────────────────────────────────────────────────────────────
    def _record_decision(self, action: Action, decision: Decision) -> None:
        s = _sys()
        if not s:
            return
        try:
            s.decision.record(
                f"{action.kind}:{action.protocol or 'generic'}:{action.intent[:40]}",
                decision.verdict.value,
                rationale="; ".join(decision.reasons), outcome="unknown")
        except Exception:
            pass

    @staticmethod
    def _a(action: Optional[Action]) -> Optional[Dict[str, Any]]:
        if action is None:
            return None
        return {"kind": action.kind, "intent": action.intent, "device": action.device,
                "protocol": action.protocol, "risk": action.risk}

    def _recommendations(self, top, decision_dict, goals) -> List[str]:
        recs: List[str] = []
        for g in goals.get("at_risk", []):
            recs.append(f"goal at risk: {g}")
        if top is not None and decision_dict:
            v = decision_dict.get("verdict")
            if v == "gate":
                recs.append(f"awaiting approval: {top.intent} on {top.device} "
                            f"(risk {top.risk:.0%})")
            elif v == "deny":
                recs.append(f"blocked: {top.intent} on {top.device} — "
                            + "; ".join(decision_dict.get("reasons", [])))
        return recs

    # ── status surface ───────────────────────────────────────────────────────
    def report(self) -> Dict[str, Any]:
        from core.intelligence.autonomy.base import autonomy_ceiling
        return {"faculties": [f.health() for f in self.f.values()],
                "autonomy_ceiling": autonomy_ceiling().name,
                "breaker_tripped": self.protection.tripped,
                "params": dict(self.optimizer.params),
                "goals": [GoalManager_g(g) for g in self.goals.goals.values()]}

    def health(self) -> Dict[str, Any]:
        active = sum(1 for f in self.f.values() if f.health()["status"] == "active")
        return {"faculties": len(self.f), "active": active,
                "breaker_tripped": self.protection.tripped}


def GoalManager_g(g) -> Dict[str, Any]:
    return {"key": g.key, "description": g.description, "priority": g.priority,
            "status": g.status, "progress": g.progress}


def _len(d: Dict[str, Any], key: str, default: int) -> int:
    try:
        v = d.get(key, default)
        return len(v) if isinstance(v, (list, dict)) else int(v)
    except Exception:
        return default


# ── singleton ────────────────────────────────────────────────────────────────
_controller: Optional[AutonomicController] = None


def get_controller() -> AutonomicController:
    global _controller
    if _controller is None:
        _controller = AutonomicController()
    return _controller


def authorize(action: Action) -> Decision:
    """Module-level convenience: the one call any execution path makes first."""
    return get_controller().authorize(action)


# ── startup wiring (mirrors wire_memory_system / wire_prediction) ────────────
def wire_autonomy() -> Dict[str, Any]:
    result = {"faculties": 0, "pillars": []}
    ctrl = get_controller()
    result["faculties"] = len(ctrl.f)

    try:
        from core.intelligence.capability_model import (
            get_capability_registry, Capability, CapabilityHealth, CapabilityStatus)
        reg = get_capability_registry()

        # Decision Making: now a real, governed gate with earned authority.
        def _decision_probe():
            try:
                lvl = ctrl.f["autonomy_governor"].effective_level("general")
                return CapabilityHealth(
                    CapabilityStatus.ACTIVE,
                    f"Governed decisions; effective autonomy '{lvl['effective']}' "
                    f"(ceiling {lvl['ceiling']}).", metrics=ctrl.health())
            except Exception as exc:
                return CapabilityHealth(CapabilityStatus.PARTIAL, str(exc))
        reg.bind_probe("decision", _decision_probe)
        result["pillars"].append("decision")

        # Autonomous Execution: governed by the safety gate + breaker.
        def _autonomous_probe():
            try:
                h = ctrl.health()
                detail = (f"{h['active']}/{h['faculties']} self-* faculties active; "
                          f"breaker {'TRIPPED' if h['breaker_tripped'] else 'normal'}; "
                          "all changes pass the authorize() gate.")
                status = (CapabilityStatus.ACTIVE if not h["breaker_tripped"]
                          else CapabilityStatus.PARTIAL)
                return CapabilityHealth(status, detail, metrics=h)
            except Exception as exc:
                return CapabilityHealth(CapabilityStatus.PARTIAL, str(exc))
        reg.bind_probe("autonomous", _autonomous_probe)
        result["pillars"].append("autonomous")

        # A new first-class pillar for self-management as a whole.
        def _selfmgmt_probe():
            h = ctrl.health()
            return CapabilityHealth(
                CapabilityStatus.ACTIVE if h["active"] else CapabilityStatus.PARTIAL,
                f"MAPE-K self-management across {h['faculties']} faculties.",
                metrics=h)
        reg.register(Capability(
            "self_management", "Self-Management",
            "MAPE-K autonomic control: self-monitoring, diagnosis, planning, "
            "recovery, optimisation, protection — governed by earned authority.",
            "core/intelligence/autonomy/controller.py",
            ["decision", "reasoning", "memory", "prediction"], _selfmgmt_probe))
        result["pillars"].append("self_management")
    except Exception as exc:
        logger.debug(f"autonomy pillar wiring deferred: {exc}")

    return result
