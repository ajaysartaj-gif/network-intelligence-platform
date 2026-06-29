"""
NRIE · Cognition · Resource Cognition (Layer 9)
===============================================
Transforms raw resource information into enterprise understanding.

IMPORTANT: this module does NOT reconstruct Enterprise/Business/Organizational/
Resource context. It CONSUMES the ResourceContextBundle produced by the Context
Builder (the single source of contextual truth) and enriches it with cognition:
classification, ownership resolution, relationship discovery, purpose and
criticality. No planning or allocation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..context.models import ResourceContextBundle
from ..events.domain_events import (
    COGNITION_COMPLETED, IntelligenceEvent, get_event_publisher,
)
from . import classification, relationship_engine


@dataclass
class ResourceCognitionResult:
    resource_id: str
    classification: Dict[str, str] = field(default_factory=dict)
    purpose: str = ""
    criticality: str = "normal"
    owner: str = ""
    business_service: str = ""
    relationships: List[Dict[str, str]] = field(default_factory=list)
    dependency_kinds: List[Dict[str, str]] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)   # echo of the bundle (not rebuilt)


class ResourceCognition:
    """Builds enterprise understanding from the bundle (single source of truth)."""

    def __init__(self, publisher=None):
        self._pub = publisher or get_event_publisher()

    def comprehend(self, bundle: ResourceContextBundle) -> ResourceCognitionResult:
        cls = classification.classify(bundle)
        result = ResourceCognitionResult(
            resource_id=bundle.resource.resource_id,
            classification=cls,
            purpose=cls.get("purpose", ""),
            criticality=classification.assess_criticality(bundle),
            owner=self._resolve_owner(bundle),
            business_service=bundle.business.business_service,
            relationships=relationship_engine.discover(bundle),
            dependency_kinds=relationship_engine.dependency_kinds(bundle),
            context=bundle.to_dict())
        self._pub.publish(IntelligenceEvent(
            type=COGNITION_COMPLETED, resource_id=result.resource_id,
            payload={"criticality": result.criticality,
                     "category": cls.get("category", "")}))
        return result

    @staticmethod
    def _resolve_owner(bundle: ResourceContextBundle) -> str:
        # ownership resolution: business owner → enterprise node owner (from bundle)
        return bundle.business.business_owner or bundle.enterprise.owner or ""
