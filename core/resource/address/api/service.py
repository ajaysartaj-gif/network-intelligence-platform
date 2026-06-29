"""
NRIE · API · Foundation Service
===============================
The single facade the Orchestrator and UI talk to — strictly through contracts
(commands in, DTOs/events out). It applies domain policies on writes (reusing the
domain layer) and persists via repositories. It exposes READ-ONLY queries.

NO allocation, planning, prediction, optimization, or AI — foundation only.
"""
from __future__ import annotations

from typing import List, Optional

from ..contracts.commands import (
    AttachBusinessContext, CaptureOrganizationalKnowledge, RecordResource,
    RegisterEnterpriseEntity,
)
from ..contracts.dto import (
    BusinessContextDTO, EnterpriseNodeDTO, KnowledgeDTO, ResourceDTO,
)
from ..domain.entities import (
    BusinessContext, EnterpriseEntity, NetworkResource, OrganizationalKnowledge,
)
from ..domain.policies import (
    BusinessContextAttachmentPolicy, HierarchyLevelOrderPolicy, ParentMustExistPolicy,
)
from ..domain.value_objects import (
    Criticality, EnterpriseLevel, Identifier, Metadata, Ownership, ResourceStatus,
    ResourceType, Tags,
)
from ..infrastructure.repositories import (
    SqlBusinessContextRepository, SqlEnterpriseRepository, SqlKnowledgeRepository,
    SqlResourceRepository,
)


class NRIEFoundationService:
    """Single entry point for Network Resource Intelligence (foundation)."""

    def __init__(self, enterprise=None, resource=None, context=None, knowledge=None):
        self._ent = enterprise or SqlEnterpriseRepository()
        self._res = resource or SqlResourceRepository()
        self._ctx = context or SqlBusinessContextRepository()
        self._know = knowledge or SqlKnowledgeRepository()

    # ── foundational writes (knowledge base, NOT allocation) ─────────────────
    def register_enterprise_entity(self, cmd: RegisterEnterpriseEntity) -> str:
        parent = self._ent.get(cmd.parent_id) if cmd.parent_id else None
        entity = EnterpriseEntity(
            id=Identifier.new("ent"), level=EnterpriseLevel(cmd.level), name=cmd.name,
            parent_id=Identifier(cmd.parent_id) if cmd.parent_id else None,
            metadata=Metadata(cmd.metadata), tags=Tags.of(*cmd.tags),
            owner=Ownership(owner=cmd.owner))
        ParentMustExistPolicy().check(entity, parent)
        HierarchyLevelOrderPolicy().check(entity, parent)
        self._ent.save(entity)
        if parent is not None:
            parent.add_child(entity.id)
            self._ent.save(parent)
        return entity.id.value

    def record_resource(self, cmd: RecordResource) -> str:
        r = NetworkResource(
            id=Identifier.new("res"), resource_type=ResourceType(cmd.resource_type),
            name=cmd.name, purpose=cmd.purpose,
            hierarchy_ref=Identifier(cmd.hierarchy_ref) if cmd.hierarchy_ref else None,
            status=ResourceStatus(cmd.status), labels=Tags.of(*cmd.labels),
            metadata=Metadata(cmd.metadata))
        self._res.save(r)
        return r.id.value

    def attach_business_context(self, cmd: AttachBusinessContext) -> str:
        svc = cmd.services or {}
        ctx = BusinessContext(
            id=Identifier.new("ctx"), attached_to=Identifier(cmd.attached_to),
            site_type=cmd.site_type, business_function=cmd.business_function,
            industry=cmd.industry, users=cmd.users,
            voice=svc.get("voice", False), cctv=svc.get("cctv", False),
            guest=svc.get("guest", False), iot=svc.get("iot", False), ot=svc.get("ot", False),
            compliance=cmd.compliance, criticality=Criticality(cmd.criticality))
        BusinessContextAttachmentPolicy().check(ctx, None)
        self._ctx.save(ctx)
        return ctx.id.value

    def capture_knowledge(self, cmd: CaptureOrganizationalKnowledge) -> str:
        rec = OrganizationalKnowledge(
            id=Identifier.new("know"), kind=cmd.kind, title=cmd.title,
            body=cmd.body, tags=Tags.of(*cmd.tags))
        self._know.save(rec)
        return rec.id.value

    # ── read-only API (returns DTOs only) ────────────────────────────────────
    def enterprise_hierarchy(self, root_id: Optional[str] = None) -> List[EnterpriseNodeDTO]:
        nodes = self._ent.all()
        if root_id:
            nodes = [n for n in nodes if n.id.value == root_id
                     or (n.parent_id and n.parent_id.value == root_id)]
        return [EnterpriseNodeDTO(
            id=n.id.value, level=n.level.value, name=n.name,
            parent_id=n.parent_id.value if n.parent_id else None,
            children_ids=[c.value for c in n.children_ids],
            lifecycle=n.lifecycle.value, owner=n.owner.owner, tags=list(n.tags),
            metadata=n.metadata.as_dict()) for n in nodes]

    def resource_hierarchy(self, hierarchy_ref: Optional[str] = None,
                           resource_type: Optional[str] = None) -> List[ResourceDTO]:
        res = self._res.by_hierarchy(hierarchy_ref) if hierarchy_ref else self._res.all()
        if resource_type:
            res = [r for r in res if r.resource_type.value == resource_type]
        return [ResourceDTO(
            id=r.id.value, resource_type=r.resource_type.value, name=r.name,
            purpose=r.purpose, hierarchy_ref=r.hierarchy_ref.value if r.hierarchy_ref else None,
            lifecycle=r.lifecycle.value, status=r.status.value,
            utilization_pct=r.utilization.percent, labels=list(r.labels),
            business_context_id=r.business_context_id.value if r.business_context_id else None,
            metadata=r.metadata.as_dict()) for r in res]

    def business_context(self, attached_to: str) -> Optional[BusinessContextDTO]:
        c = self._ctx.for_target(attached_to)
        if not c:
            return None
        return BusinessContextDTO(
            id=c.id.value, attached_to=c.attached_to.value if c.attached_to else None,
            site_type=c.site_type, business_function=c.business_function, industry=c.industry,
            users=c.users, criticality=c.criticality.value,
            services={"voice": c.voice, "cctv": c.cctv, "guest": c.guest, "iot": c.iot, "ot": c.ot},
            compliance=c.compliance, sla={"name": c.sla.name})

    def knowledge(self, kind: Optional[str] = None) -> List[KnowledgeDTO]:
        return [KnowledgeDTO(id=r.id.value, kind=r.kind, title=r.title, body=r.body,
                             tags=list(r.tags), lifecycle=r.lifecycle.value)
                for r in self._know.by_kind(kind)]


_SERVICE: Optional[NRIEFoundationService] = None


def get_nrie_service() -> NRIEFoundationService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = NRIEFoundationService()
    return _SERVICE
