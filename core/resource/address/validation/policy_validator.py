"""
NRIE · Validation · Policy Validator
====================================
Validates policy compliance by REUSING the PR-002 Policy Evaluator (no duplicate
policy logic). Report-only.
"""
from __future__ import annotations

from typing import List

from ..context.models import ResourceContextBundle
from ..policy.policy_evaluator import PolicyEvaluator


class PolicyValidator:
    def __init__(self, evaluator=None):
        self._eval = evaluator or PolicyEvaluator()

    def validate(self, bundle: ResourceContextBundle) -> List[str]:
        ev = self._eval.evaluate(bundle)
        return list(ev.violations)
