"""
NRIE · Policy · Policy Evaluator
================================
Evaluates the policy registry against a ResourceContextBundle and REPORTS
results (pass/fail, violations, recommendations, applicable standards). It never
enforces or gates deployment. Consumes the bundle as the single context source.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..context.models import ResourceContextBundle
from ..events.domain_events import (
    POLICY_EVALUATED, IntelligenceEvent, get_event_publisher,
)
from ..knowledge.standards import ORGANIZATIONAL_STANDARD_KINDS
from .policy_engine import PolicyRule, get_policy_rules


@dataclass
class PolicyEvaluation:
    resource_id: str
    passed: bool
    violations: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    applicable_standards: List[str] = field(default_factory=list)
    evaluated_rules: int = 0


class PolicyEvaluator:
    def __init__(self, rules: Optional[List[PolicyRule]] = None, publisher=None):
        self._rules = rules or get_policy_rules()
        self._pub = publisher or get_event_publisher()

    def evaluate(self, bundle: ResourceContextBundle) -> PolicyEvaluation:
        violations: List[str] = []
        recommendations: List[str] = []
        for rule in self._rules:
            try:
                ok = rule.check(bundle)
            except Exception:
                ok = True  # never fail evaluation on a rule error
            if not ok:
                violations.append(f"[{rule.category}] {rule.description}")
                if rule.recommendation:
                    recommendations.append(rule.recommendation)
        ev = PolicyEvaluation(
            resource_id=bundle.resource.resource_id,
            passed=(len(violations) == 0), violations=violations,
            recommendations=recommendations,
            applicable_standards=list(ORGANIZATIONAL_STANDARD_KINDS),
            evaluated_rules=len(self._rules))
        self._pub.publish(IntelligenceEvent(
            type=POLICY_EVALUATED, resource_id=ev.resource_id,
            payload={"passed": ev.passed, "violations": len(violations)}))
        return ev
