"""
Reasoning Layer (Milestone 3 — Reasoning & Decision Engine)
==========================================================

Reasoning-first gate. After the Evidence Layer (M2) confirms enough verified
evidence exists, this layer makes a DETERMINISTIC engineering decision by
activating the existing intelligence (Reasoning Registry, Decision Faculty,
Knowledge Graph, Operational Memory). The LLM never decides whether more
information is required — this layer does.

Public interface (the standard contract future milestones depend on):
    DecisionContract, DecisionStatus
    decide_change(request, device, evidence, ...)
    get_reasoning_decision_engine()
"""

from .contract import DecisionContract, DecisionStatus
from .engine import (
    ReasoningDecisionEngine,
    get_reasoning_decision_engine,
    decide_change,
)

__all__ = [
    "DecisionContract",
    "DecisionStatus",
    "ReasoningDecisionEngine",
    "get_reasoning_decision_engine",
    "decide_change",
]
