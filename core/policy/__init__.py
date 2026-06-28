"""
Enterprise Policy & Autonomous Control Layer (Milestone 5)
=========================================================

Policy-driven operations. After Governance (M4) decides whether a change is
technically acceptable, this layer decides whether it is organizationally
permitted — change freeze, maintenance window, business criticality, operator
authorization, and autonomous eligibility — by reusing the existing
business-rules subsystem. The LLM never decides organizational permission.

Public interface (the standard policy contract future autonomous operation
consumes):
    PolicyContract, PolicyStatus
    evaluate_policy(device=..., ...)
    get_policy_engine()
"""

from .contract import PolicyContract, PolicyStatus
from .engine import EnterprisePolicyEngine, get_policy_engine, evaluate_policy

__all__ = [
    "PolicyContract",
    "PolicyStatus",
    "EnterprisePolicyEngine",
    "get_policy_engine",
    "evaluate_policy",
]
