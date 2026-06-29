"""
NRIE · Context · Builder
========================
Builds Enterprise, Resource, Business and Organizational contexts and merges
them into one ResourceContextBundle. It REUSES the existing read API
(core.resource.address.api.service) and domain entities — it introduces no new
platform service and contains NO allocation, planning, prediction, optimization,
or explainability logic. It only assembles knowledge that already exists.

This package is intended for reuse by future Planning / Prediction / Optimization
/ Explainability PRs.
"""
from __future__ import annotations

from typing import List, Optional

from ..domain.entities import (
    BusinessContext, EnterpriseEntity, NetworkResource, OrganizationalKnowledge,
)
from .models import (
    BusinessContextModel, EnterpriseContext, OrganizationalContext,
    ResourceContext, ResourceContextBundle,
)


class DefaultContextBuilder:
    """Assembles context from domain objects; merge() yields the single bundle."""

    # ── individual context builders ─────────────────────────────────────────
    def build_enterprise_context(self, node: EnterpriseEntity,
                                 ancestors: Optional[List[EnterpriseEntity]] = None
                                 ) -> EnterpriseContext:
        return EnterpriseContext(
            node_id=node.id.value, level=node.level.value, name=node.name,
            ancestors=[a.name for a in (ancestors or [])],
            owner=node.owner.owner, tags=list(node.tags))

    def build_resource_context(self, resource: NetworkResource,
                               pool: Optional[object] = None) -> ResourceContext:
        pool_ref = None
        if pool is not None and getattr(pool, "id", None) is not None:
            pool_ref = pool.id.value
        return ResourceContext(
            resource_id=resource.id.value, resource_type=resource.resource_type.value,
            purpose=resource.purpose, status=resource.status.value, pool_ref=pool_ref,
            labels=list(resource.labels))

    def build_business_context(self, bc: BusinessContext) -> BusinessContextModel:
        return BusinessContextModel(
            attached_to=bc.attached_to.value if bc.attached_to else None,
            business_capability=bc.business_capability,
            business_service=bc.business_service,
            business_owner=bc.business_owner.owner,
            business_function=bc.business_function, industry=bc.industry,
            site_type=bc.site_type, users=bc.users,
            criticality=bc.criticality.value, compliance=list(bc.compliance),
            availability={"target": bc.availability.target, "rto": bc.availability.rto,
                          "rpo": bc.availability.rpo},
            growth_expectation={"horizon": bc.growth_expectation.horizon,
                                "expected_pct": bc.growth_expectation.expected_pct},
            operational_model=bc.operational_model.value,
            architecture_pattern=bc.architecture_pattern.value,
            risk_classification=bc.risk_classification.value,
            services={"voice": bc.voice, "cctv": bc.cctv, "guest": bc.guest,
                      "iot": bc.iot, "ot": bc.ot})

    def build_organizational_context(self, records: List[OrganizationalKnowledge],
                                     kinds: Optional[List[str]] = None
                                     ) -> OrganizationalContext:
        recs = [r for r in records if (not kinds or r.kind in kinds)]
        return OrganizationalContext(
            applicable_standard_kinds=sorted({r.kind for r in recs}),
            knowledge_titles=[r.title for r in recs])

    # ── merge into the single Resource Context ───────────────────────────────
    def merge(self, *, domain: str = "address",
              resource: ResourceContext, enterprise: EnterpriseContext,
              business: BusinessContextModel,
              organizational: OrganizationalContext) -> ResourceContextBundle:
        return ResourceContextBundle(
            domain=domain, resource=resource, enterprise=enterprise,
            business=business, organizational=organizational)

    # ── convenience: assemble from the existing read API (reuse) ─────────────
    def for_resource(self, resource: NetworkResource,
                     enterprise_node: Optional[EnterpriseEntity] = None,
                     ancestors: Optional[List[EnterpriseEntity]] = None,
                     business_context: Optional[BusinessContext] = None,
                     knowledge: Optional[List[OrganizationalKnowledge]] = None,
                     pool: Optional[object] = None,
                     domain: str = "address") -> ResourceContextBundle:
        rc = self.build_resource_context(resource, pool)
        ec = (self.build_enterprise_context(enterprise_node, ancestors)
              if enterprise_node else EnterpriseContext())
        bc = (self.build_business_context(business_context)
              if business_context else BusinessContextModel())
        oc = self.build_organizational_context(knowledge or [])
        return self.merge(domain=domain, resource=rc, enterprise=ec,
                          business=bc, organizational=oc)


_BUILDER: Optional[DefaultContextBuilder] = None


def get_context_builder() -> DefaultContextBuilder:
    global _BUILDER
    if _BUILDER is None:
        _BUILDER = DefaultContextBuilder()
    return _BUILDER
