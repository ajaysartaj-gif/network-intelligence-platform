"""
core/intelligence/autonomy
==========================
Self-direction as a first-class capability.

Automation runs a fixed script; autonomy decides for itself — what to do, in what
order, whether now is the right time, whether it is allowed, whether it worked,
and what to change next time — while staying inside a hard safety envelope.

The faculties (self-monitoring, self-diagnosis, self-recovery, self-protection,
self-optimisation, self-verification, goal management, resource/time/policy
awareness, prioritisation, planning, scheduling, coordination, and earned
authority) are composed by an AutonomicController into the MAPE-K loop
(Monitor → Analyze → Plan → Execute over shared Knowledge).

  from core.intelligence.autonomy import (
      get_controller, authorize, wire_autonomy, Action, Decision, Verdict)

  wire_autonomy()                                  # at startup
  d = authorize(Action(kind="config_change", intent="add ospf",
                       device="192.168.96.133", protocol="ospf"))
  if d.allowed: ...                                # else d.requires_approval / DENY

  # wrap a normal operational cycle into a self-managed one:
  report = get_controller().governed_run(orchestrator.run_cycle)
"""
from core.intelligence.autonomy.base import (
    Action, Decision, Verdict, AutonomyLevel, Goal, autonomy_ceiling,
)
from core.intelligence.autonomy.controller import (
    AutonomicController, get_controller, authorize, wire_autonomy,
)

__all__ = [
    "Action", "Decision", "Verdict", "AutonomyLevel", "Goal", "autonomy_ceiling",
    "AutonomicController", "get_controller", "authorize", "wire_autonomy",
]
