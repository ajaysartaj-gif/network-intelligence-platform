"""
Enterprise Change Governance Layer (Milestone 4)
===============================================

Governed change execution. After Evidence (M2) and Reasoning (M3) protect
configuration generation, this layer makes the final engineering decision on
whether a change may DEPLOY — acting as an enterprise Change Advisory Board plus
a Principal Network Architect. It activates the existing Compliance,
Authorization, Risk, Rollback, and (optional) Simulation capabilities; the LLM
never decides whether deployment is safe.

Public interface (the standard governance contract future milestones depend on):
    GovernanceContract, GovernanceStatus
    govern_change(device=..., commands=..., ...)
    get_governance_engine()
"""

from .contract import GovernanceContract, GovernanceStatus
from .engine import GovernanceEngine, get_governance_engine, govern_change

__all__ = [
    "GovernanceContract",
    "GovernanceStatus",
    "GovernanceEngine",
    "get_governance_engine",
    "govern_change",
]
