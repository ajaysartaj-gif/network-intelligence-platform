"""
Policy Contract (Milestone 5 — Enterprise Policy & Autonomous Control)
====================================================================

The single, reusable interface carrying the ORGANIZATIONAL decision on whether a
change may execute. Governance decides whether a change is technically
acceptable; Policy decides whether it is organizationally permitted (change
freeze, maintenance window, business criticality, operator/role authorization,
autonomous eligibility).

Produced by reusing the existing business-rules subsystem; it performs no
deployment, generation, reasoning, or evidence collection. Future autonomous
capabilities consume THIS contract.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class PolicyStatus(str, Enum):
    """The only policy decisions that may be returned (deterministic)."""
    PERMITTED = "permitted"
    PERMITTED_WITH_WARNING = "permitted_with_warning"
    MANUAL_APPROVAL_REQUIRED = "manual_approval_required"
    DENIED = "denied"


_PERMITTED = {PolicyStatus.PERMITTED, PolicyStatus.PERMITTED_WITH_WARNING}


@dataclass
class PolicyContract:
    """Standard organizational-policy result."""
    device: str
    status: PolicyStatus = PolicyStatus.PERMITTED
    business_rules_applied: List[str] = field(default_factory=list)
    policy_violations: List[str] = field(default_factory=list)
    maintenance_window: str = "open"             # open | freeze | closed
    role_validation: str = "unverified"          # validated | autonomous | unverified | denied
    autonomous_eligible: bool = False
    business_warnings: List[str] = field(default_factory=list)
    ts: float = field(default_factory=time.time)

    @property
    def permitted(self) -> bool:
        """Execution is organizationally permitted ONLY when this is True."""
        return self.status in _PERMITTED

    @property
    def execution_permission(self) -> str:
        return "permitted" if self.permitted else "denied"

    def summary(self) -> str:
        head = self.status.value.replace("_", " ").title()
        if self.permitted:
            extra = f" ({len(self.business_warnings)} warning(s))" if self.business_warnings else ""
            return f"{head}: execution organizationally permitted for {self.device}{extra}."
        why = "; ".join(self.policy_violations) or "see policy report"
        return f"{head}: execution not permitted for {self.device} — {why}."

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device": self.device,
            "status": self.status.value,
            "business_rules_applied": list(self.business_rules_applied),
            "policy_violations": list(self.policy_violations),
            "maintenance_window": self.maintenance_window,
            "role_validation": self.role_validation,
            "autonomous_eligible": self.autonomous_eligible,
            "execution_permission": self.execution_permission,
            "business_warnings": list(self.business_warnings),
            "summary": self.summary(),
            "ts": self.ts,
        }
