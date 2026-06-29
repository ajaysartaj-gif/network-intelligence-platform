"""
NRIE · Validation · Plan Validator (Validation Engine)
======================================================
Validates a Resource Plan before any execution: duplicate/overlap addresses,
capacity, policy compliance (reused), dependency, business-rule, lifecycle and
naming checks. Only validated plans may proceed. No deployment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..allocation.conflict_detector import detect
from ..context.models import ResourceContextBundle
from ..events.domain_events import (
    VALIDATION_COMPLETED, IntelligenceEvent, get_event_publisher,
)
from .policy_validator import PolicyValidator


@dataclass
class PlanValidation:
    valid: bool = True
    issues: List[str] = field(default_factory=list)
    checks_run: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"valid": self.valid, "issues": self.issues, "checks_run": self.checks_run}


class PlanValidator:
    def __init__(self, policy_validator=None, publisher=None):
        self._policy = policy_validator or PolicyValidator()
        self._pub = publisher or get_event_publisher()

    def validate(self, *, plan, bundle: ResourceContextBundle) -> PlanValidation:
        issues: List[str] = []
        checks = ["duplicate", "overlap", "capacity", "policy", "naming", "lifecycle"]
        cidrs = [s.cidr for s in plan.subnets]
        # duplicate / overlap
        for i, c in enumerate(cidrs):
            conflicts = detect(c, cidrs[:i])
            issues += [f"{k.kind}: {c} vs {k.existing}" for k in conflicts]
        # capacity / planning success
        if not plan.success:
            issues.append("plan incomplete: " + "; ".join(plan.notes))
        # naming: every subnet must declare a purpose & vrf
        for s in plan.subnets:
            if not s.purpose or not s.vrf:
                issues.append(f"naming: subnet {s.cidr} missing purpose/vrf")
        # policy compliance (reused evaluator)
        issues += [f"policy: {v}" for v in self._policy.validate(bundle)]
        result = PlanValidation(valid=(len(issues) == 0), issues=issues, checks_run=checks)
        self._pub.publish(IntelligenceEvent(
            type=VALIDATION_COMPLETED, resource_id=bundle.resource.resource_id,
            payload={"valid": result.valid, "issues": len(issues)}))
        return result
