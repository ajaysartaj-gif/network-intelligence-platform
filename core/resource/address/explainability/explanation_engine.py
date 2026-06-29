"""
NRIE · Explainability · Explanation Engine (Layer 14)
=====================================================
Every recommendation explains itself: why, which evidence, which policies, which
business requirements, which alternatives, confidence, expected benefits, risks
and future impact. Pure assembly from the bundle + plan + validation + options.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Explanation:
    why: str = ""
    evidence: List[str] = field(default_factory=list)
    policies: List[str] = field(default_factory=list)
    business_requirements: List[str] = field(default_factory=list)
    alternatives: List[str] = field(default_factory=list)
    confidence: float = 0.0
    expected_benefits: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    future_impact: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__


class ExplanationEngine:
    def explain(self, *, bundle, plan, validation, recommendations) -> Explanation:
        top = recommendations[0] if recommendations else None
        b = bundle.business
        return Explanation(
            why=(f"Plan satisfies '{plan.intent}' for {bundle.enterprise.name} using "
                 f"{len(plan.subnets)} subnet(s) sized for declared demand plus "
                 f"{plan.growth_headroom_pct:.0f}% growth headroom."),
            evidence=[f"resource={bundle.resource.resource_id}",
                      f"criticality={b.criticality}",
                      f"ancestors={bundle.enterprise.ancestors}",
                      f"address_space={plan.address_space}"],
            policies=[f"validation: {'passed' if validation.valid else 'issues'}"]
                     + validation.issues[:3],
            business_requirements=[f"capability={b.business_capability}",
                                   f"service={b.business_service}",
                                   f"compliance={b.compliance}"],
            alternatives=[r.label for r in recommendations],
            confidence=(top.confidence if top else 0.0),
            expected_benefits=["minimised fragmentation", "growth headroom reserved",
                               "conflict-free, validated addressing"],
            risks=(["plan incomplete — see notes"] if not plan.success else
                   (["unresolved validation issues"] if not validation.valid else [])),
            future_impact=("Leaves room to expand without re-addressing; supports "
                           "summarisation as the site grows."))
