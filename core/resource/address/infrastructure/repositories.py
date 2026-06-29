"""
NRIE · Infrastructure · Repositories
====================================
Concrete repositories implementing the contract interfaces. They ONLY persist
and retrieve, mapping domain objects ↔ stored payloads. No domain rules here
(those live in the domain layer); no allocation/planning.
"""
from __future__ import annotations

from typing import List, Optional

from ..domain.entities import (
    BusinessContext, EnterpriseEntity, NetworkResource, OrganizationalKnowledge,
)
from ..domain.value_objects import (
    Criticality, EnterpriseLevel, Identifier, Lifecycle, Metadata, Ownership,
    ResourceStatus, ResourceType, SLA, Tags, Utilization,
)
from .persistence import (
    BusinessContextStore, EnterpriseStore, KnowledgeStore, ResourceStore,
)


# ── mapping helpers (row payload ↔ domain) ───────────────────────────────────
def _ent_to_payload(e: EnterpriseEntity) -> dict:
    return {"id": e.id.value, "level": e.level.value, "name": e.name,
            "parent_id": e.parent_id.value if e.parent_id else None,
            "children_ids": [c.value for c in e.children_ids],
            "lifecycle": e.lifecycle.value, "owner": e.owner.owner,
            "tags": list(e.tags), "metadata": e.metadata.as_dict()}


def _payload_to_ent(p: dict) -> EnterpriseEntity:
    return EnterpriseEntity(
        id=Identifier(p["id"]), level=EnterpriseLevel(p["level"]), name=p["name"],
        parent_id=Identifier(p["parent_id"]) if p.get("parent_id") else None,
        children_ids=[Identifier(c) for c in p.get("children_ids", [])],
        metadata=Metadata(p.get("metadata", {})), tags=Tags.of(*p.get("tags", [])),
        lifecycle=Lifecycle(p.get("lifecycle", "active")),
        owner=Ownership(owner=p.get("owner", "")))


class SqlEnterpriseRepository:
    def __init__(self, store: Optional[EnterpriseStore] = None):
        self._s = store or EnterpriseStore()

    def save(self, node: EnterpriseEntity) -> None:
        self._s.put(node.id.value, f"{node.level.value}:{node.name}",
                    _ent_to_payload(node), level=node.level.value,
                    parent=node.parent_id.value if node.parent_id else "")

    def get(self, entity_id: str) -> Optional[EnterpriseEntity]:
        p = self._s.get_payload(entity_id)
        return _payload_to_ent(p) if p else None

    def children(self, parent_id: Optional[str]) -> List[EnterpriseEntity]:
        rows = self._s.where(parent=parent_id or "")
        return [_payload_to_ent(p) for p in self._s.payloads(rows) if p]

    def all(self) -> List[EnterpriseEntity]:
        return [_payload_to_ent(p) for p in self._s.payloads(self._s.rows()) if p]


class SqlResourceRepository:
    def __init__(self, store: Optional[ResourceStore] = None):
        self._s = store or ResourceStore()

    def save(self, r: NetworkResource) -> None:
        payload = {"id": r.id.value, "resource_type": r.resource_type.value,
                   "name": r.name, "purpose": r.purpose,
                   "hierarchy_ref": r.hierarchy_ref.value if r.hierarchy_ref else None,
                   "lifecycle": r.lifecycle.value, "status": r.status.value,
                   "utilization_pct": r.utilization.percent, "labels": list(r.labels),
                   "business_context_id": r.business_context_id.value if r.business_context_id else None,
                   "metadata": r.metadata.as_dict()}
        self._s.put(r.id.value, f"{r.resource_type.value}:{r.name}", payload,
                    rtype=r.resource_type.value,
                    hierarchy_ref=r.hierarchy_ref.value if r.hierarchy_ref else "")

    def get(self, resource_id: str) -> Optional[NetworkResource]:
        p = self._s.get_payload(resource_id)
        return self._map(p) if p else None

    def by_hierarchy(self, hierarchy_ref: str) -> List[NetworkResource]:
        rows = self._s.where(hierarchy_ref=hierarchy_ref)
        return [self._map(p) for p in self._s.payloads(rows) if p]

    def all(self) -> List[NetworkResource]:
        return [self._map(p) for p in self._s.payloads(self._s.rows()) if p]

    @staticmethod
    def _map(p: dict) -> NetworkResource:
        return NetworkResource(
            id=Identifier(p["id"]), resource_type=ResourceType(p["resource_type"]),
            name=p["name"], purpose=p.get("purpose", ""),
            hierarchy_ref=Identifier(p["hierarchy_ref"]) if p.get("hierarchy_ref") else None,
            lifecycle=Lifecycle(p.get("lifecycle", "planned")),
            status=ResourceStatus(p.get("status", "planned")),
            utilization=Utilization(p.get("utilization_pct", 0.0)),
            labels=Tags.of(*p.get("labels", [])), metadata=Metadata(p.get("metadata", {})),
            business_context_id=Identifier(p["business_context_id"]) if p.get("business_context_id") else None)


class SqlBusinessContextRepository:
    def __init__(self, store: Optional[BusinessContextStore] = None):
        self._s = store or BusinessContextStore()

    def save(self, ctx: BusinessContext) -> None:
        payload = {"id": ctx.id.value,
                   "attached_to": ctx.attached_to.value if ctx.attached_to else None,
                   "site_type": ctx.site_type, "business_function": ctx.business_function,
                   "industry": ctx.industry, "users": ctx.users,
                   "criticality": ctx.criticality.value,
                   "services": {"voice": ctx.voice, "cctv": ctx.cctv, "guest": ctx.guest,
                                "iot": ctx.iot, "ot": ctx.ot},
                   "compliance": ctx.compliance,
                   "sla": {"name": ctx.sla.name, "availability": ctx.sla.availability}}
        self._s.put(ctx.id.value, f"ctx:{ctx.site_type or ctx.business_function}", payload,
                    attached_to=ctx.attached_to.value if ctx.attached_to else "")

    def for_target(self, attached_to: str) -> Optional[BusinessContext]:
        rows = self._s.where(attached_to=attached_to)
        ps = [p for p in self._s.payloads(rows) if p]
        return self._map(ps[0]) if ps else None

    @staticmethod
    def _map(p: dict) -> BusinessContext:
        svc = p.get("services", {})
        return BusinessContext(
            id=Identifier(p["id"]),
            attached_to=Identifier(p["attached_to"]) if p.get("attached_to") else None,
            site_type=p.get("site_type", ""), business_function=p.get("business_function", ""),
            industry=p.get("industry", ""), users=int(p.get("users", 0)),
            voice=svc.get("voice", False), cctv=svc.get("cctv", False),
            guest=svc.get("guest", False), iot=svc.get("iot", False), ot=svc.get("ot", False),
            compliance=p.get("compliance", []),
            criticality=Criticality(p.get("criticality", "normal")),
            sla=SLA(name=p.get("sla", {}).get("name", "")))


class SqlKnowledgeRepository:
    def __init__(self, store: Optional[KnowledgeStore] = None):
        self._s = store or KnowledgeStore()

    def save(self, rec: OrganizationalKnowledge) -> None:
        payload = {"id": rec.id.value, "kind": rec.kind, "title": rec.title,
                   "body": rec.body, "tags": list(rec.tags), "lifecycle": rec.lifecycle.value}
        self._s.put(rec.id.value, f"{rec.kind}:{rec.title}", payload, kind=rec.kind)

    def by_kind(self, kind: Optional[str]) -> List[OrganizationalKnowledge]:
        rows = self._s.where(kind=kind) if kind else self._s.rows()
        return [self._map(p) for p in self._s.payloads(rows) if p]

    @staticmethod
    def _map(p: dict) -> OrganizationalKnowledge:
        return OrganizationalKnowledge(
            id=Identifier(p["id"]), kind=p["kind"], title=p["title"],
            body=p.get("body", ""), tags=Tags.of(*p.get("tags", [])),
            lifecycle=Lifecycle(p.get("lifecycle", "active")))
