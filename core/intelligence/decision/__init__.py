"""
core/intelligence/decision
===========================
Decision Intelligence — judgment, not recommendation.

A junior engineer outputs "do X". A senior architect renders a judgment: holds
the alternatives at once, weighs considerations that genuinely trade off,
respects hard lines cost-benefit cannot override, sees second-order and long-term
consequences, knows the opportunity cost and the cost of being wrong, prefers
reversible moves under uncertainty, stays consistent with precedent, and explains
why — including why not the runner-up — with calibrated confidence.

  from core.intelligence.decision import (
      get_deliberation_engine, judge, wire_decision, Option, DecisionContext)

  wire_decision()                                   # at startup
  j = judge("Fix OSPF on the hub now, or wait for the window?",
            options=[{"label": "Fix now", "intent": "fix ospf adjacency",
                      "device": "10.0.0.1", "protocol": "ospf", "reversible": True},
                     {"label": "Wait for window", "intent": "schedule fix",
                      "device": "10.0.0.1", "protocol": "ospf", "changes_state": False}])
  print(j.explain())
"""
from core.intelligence.decision.engine import (
    DeliberationEngine, get_deliberation_engine, judge, wire_decision,
)
from core.intelligence.decision.base import (
    Option, DecisionContext, Judgment, Appraisal,
)

__all__ = [
    "DeliberationEngine", "get_deliberation_engine", "judge", "wire_decision",
    "Option", "DecisionContext", "Judgment", "Appraisal",
]
