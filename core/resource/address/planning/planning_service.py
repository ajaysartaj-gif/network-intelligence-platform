"""
NRIE · Planning · Planning Service (orchestration)
=================================================
Coordinates planning → recommendation → validation → explainability into one
read/act workflow. Reuses the existing intelligence layers; it does NOT deploy or
generate configuration (separation of planning from deployment is preserved).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..allocation.allocator import AddressDemand
from ..context.models import ResourceContextBundle
from ..explainability.explanation_engine import Explanation, ExplanationEngine
from ..recommendation.recommendation_engine import Recommendation, RecommendationEngine
from ..validation.validator import PlanValidation, PlanValidator
from .planner import ResourcePlan, ResourcePlanner


@dataclass
class PlanningOutcome:
    plan: ResourcePlan
    validation: PlanValidation
    recommendations: List[Recommendation] = field(default_factory=list)
    explanation: Optional[Explanation] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"plan": self.plan.to_dict(), "validation": self.validation.to_dict(),
                "recommendations": [r.to_dict() for r in self.recommendations],
                "explanation": self.explanation.to_dict() if self.explanation else None}


class PlanningService:
    def __init__(self, planner=None, validator=None, recommender=None, explainer=None):
        self._planner = planner or ResourcePlanner()
        self._validator = validator or PlanValidator()
        self._recommender = recommender or RecommendationEngine()
        self._explainer = explainer or ExplanationEngine()

    def plan(self, *, bundle: ResourceContextBundle, intent: str,
             demands: List[AddressDemand], address_space: str = "10.40.0.0/16") -> PlanningOutcome:
        plan = self._planner.plan(bundle=bundle, intent=intent, demands=demands,
                                  address_space=address_space)
        validation = self._validator.validate(plan=plan, bundle=bundle)
        recommendations = self._recommender.rank(bundle=bundle, plan=plan, demands=demands,
                                                 address_space=address_space)
        explanation = self._explainer.explain(bundle=bundle, plan=plan,
                                              validation=validation,
                                              recommendations=recommendations)
        return PlanningOutcome(plan=plan, validation=validation,
                               recommendations=recommendations, explanation=explanation)
