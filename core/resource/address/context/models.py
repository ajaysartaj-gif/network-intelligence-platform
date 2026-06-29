"""
NRIE · Context · Models
=======================
Read models produced by the Context Builder. Pure data — no persistence, no
allocation/planning/prediction. These are the reusable inputs that future
Planning / Prediction / Optimization / Explainability PRs will consume.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class EnterpriseContext:
    node_id: str = ""
    level: str = ""
    name: str = ""
    ancestors: List[str] = field(default_factory=list)   # ordered root→parent names
    owner: str = ""
    tags: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResourceContext:
    resource_id: str = ""
    resource_type: str = ""
    purpose: str = ""
    status: str = ""
    pool_ref: Optional[str] = None
    labels: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class BusinessContextModel:
    """The 'why' — enterprise meaning, not networking detail."""
    attached_to: Optional[str] = None
    business_capability: str = ""
    business_service: str = ""
    business_owner: str = ""
    business_function: str = ""
    industry: str = ""
    site_type: str = ""
    users: int = 0
    criticality: str = "normal"
    compliance: List[str] = field(default_factory=list)
    availability: Dict[str, str] = field(default_factory=dict)     # target/rto/rpo
    growth_expectation: Dict[str, Any] = field(default_factory=dict)  # horizon/expected_pct
    operational_model: str = "unspecified"
    architecture_pattern: str = "unspecified"
    risk_classification: str = "low"
    services: Dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class OrganizationalContext:
    applicable_standard_kinds: List[str] = field(default_factory=list)
    knowledge_titles: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResourceContextBundle:
    """The single merged context for a resource (domain-tagged for extensibility)."""
    domain: str = "address"
    resource: ResourceContext = field(default_factory=ResourceContext)
    enterprise: EnterpriseContext = field(default_factory=EnterpriseContext)
    business: BusinessContextModel = field(default_factory=BusinessContextModel)
    organizational: OrganizationalContext = field(default_factory=OrganizationalContext)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "resource": self.resource.__dict__,
            "enterprise": self.enterprise.__dict__,
            "business": self.business.__dict__,
            "organizational": self.organizational.__dict__,
        }
