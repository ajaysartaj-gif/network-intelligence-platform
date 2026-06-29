"""
NRIE · Address Domain · Aggregates
==================================

Aggregate roots own consistency boundaries and enforce cross-entity invariants
(via policies). They are pure in-memory models — repositories persist them, they
do not persist themselves. No allocation/planning/AI here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .entities import (
    BusinessContext, EnterpriseEntity, NetworkResource, OrganizationalKnowledge,
)
from .events import (
    BusinessContextAttached, DomainEvent, EnterpriseEntityRegistered,
    KnowledgeCaptured, ResourceRecorded,
)
from .policies import (
    BusinessContextAttachmentPolicy, HierarchyLevelOrderPolicy, ParentMustExistPolicy,
)
from .value_objects import Identifier


@dataclass
class EnterpriseHierarchy:
    """Aggregate root for the enterprise hierarchy (Organization … Floor)."""
    entities: Dict[str, EnterpriseEntity] = field(default_factory=dict)
    _events: List[DomainEvent] = field(default_factory=list)

    def register(self, entity: EnterpriseEntity) -> EnterpriseEntity:
        parent = self.entities.get(entity.parent_id.value) if entity.parent_id else None
        ParentMustExistPolicy().check(entity, parent)
        HierarchyLevelOrderPolicy().check(entity, parent)
        self.entities[entity.id.value] = entity
        if parent is not None:
            parent.add_child(entity.id)
        self._events.append(EnterpriseEntityRegistered(
            entity_id=entity.id.value, level=entity.level.value, name=entity.name,
            parent_id=entity.parent_id.value if entity.parent_id else None))
        return entity

    def children_of(self, parent_id: Identifier) -> List[EnterpriseEntity]:
        return [e for e in self.entities.values()
                if e.parent_id and e.parent_id.value == parent_id.value]

    def pull_events(self) -> List[DomainEvent]:
        out, self._events = self._events, []
        return out


@dataclass
class ResourceInventory:
    """Aggregate root for resource knowledge + business-context attachment."""
    resources: Dict[str, NetworkResource] = field(default_factory=dict)
    contexts: Dict[str, BusinessContext] = field(default_factory=dict)
    _events: List[DomainEvent] = field(default_factory=list)

    def record(self, resource: NetworkResource) -> NetworkResource:
        self.resources[resource.id.value] = resource
        self._events.append(ResourceRecorded(
            resource_id=resource.id.value, resource_type=resource.resource_type.value,
            name=resource.name, hierarchy_ref=(resource.hierarchy_ref.value
                                               if resource.hierarchy_ref else None)))
        return resource

    def attach_context(self, ctx: BusinessContext,
                       resource: Optional[NetworkResource] = None) -> BusinessContext:
        BusinessContextAttachmentPolicy().check(ctx, resource)
        self.contexts[ctx.id.value] = ctx
        if resource is not None:
            resource.business_context_id = ctx.id
        self._events.append(BusinessContextAttached(
            context_id=ctx.id.value,
            attached_to=ctx.attached_to.value if ctx.attached_to else None))
        return ctx

    def pull_events(self) -> List[DomainEvent]:
        out, self._events = self._events, []
        return out


@dataclass
class OrganizationalMemory:
    """Aggregate root for stored organizational knowledge."""
    records: Dict[str, OrganizationalKnowledge] = field(default_factory=dict)
    _events: List[DomainEvent] = field(default_factory=list)

    def capture(self, record: OrganizationalKnowledge) -> OrganizationalKnowledge:
        self.records[record.id.value] = record
        self._events.append(KnowledgeCaptured(
            knowledge_id=record.id.value, kind=record.kind, title=record.title))
        return record

    def by_kind(self, kind: str) -> List[OrganizationalKnowledge]:
        return [r for r in self.records.values() if r.kind == kind]

    def pull_events(self) -> List[DomainEvent]:
        out, self._events = self._events, []
        return out


# ──────────────────────────────────────────────────────────────────────────────
# PR-001.1 — Pool becomes the Address Aggregate Root
# ──────────────────────────────────────────────────────────────────────────────
from .entities import Reservation                       # noqa: E402
from .events import (                                    # noqa: E402
    PoolRegistered, ReservationRecorded, SubnetAttachedToPool,
)
from .value_objects import (                             # noqa: E402
    Capacity, Fragmentation, GrowthInfo, Identifier as _Id, ResourceDomain,
    ResourceType, Utilization,
)


@dataclass
class Pool:
    """The Address aggregate root.

    A Pool owns its Subnets, Reservations, Capacity, Utilization, Fragmentation
    and Growth information. It is the single consistency boundary for address
    resources — future allocation logic must work THROUGH this aggregate (no
    allocation/sizing/carving is implemented here; this PR only establishes
    ownership and structure).
    """
    id: _Id
    purpose: str = ""
    hierarchy_ref: Optional[_Id] = None
    domain: ResourceDomain = ResourceDomain.ADDRESS      # not address-only by assumption
    parent_pool_id: Optional[_Id] = None
    # owned members
    subnets: Dict[str, NetworkResource] = field(default_factory=dict)
    reservations: Dict[str, Reservation] = field(default_factory=dict)
    # recorded structural knowledge (NOT computed plans)
    capacity: Capacity = field(default_factory=Capacity)
    utilization: Utilization = field(default_factory=Utilization)
    fragmentation: Fragmentation = field(default_factory=Fragmentation)
    growth: GrowthInfo = field(default_factory=GrowthInfo)
    _events: List[DomainEvent] = field(default_factory=list)

    def __post_init__(self):
        self._events.append(PoolRegistered(
            pool_id=self.id.value, purpose=self.purpose,
            hierarchy_ref=self.hierarchy_ref.value if self.hierarchy_ref else None))

    # ── ownership operations (knowledge only; no allocation) ─────────────────
    def add_subnet(self, subnet: NetworkResource) -> NetworkResource:
        if subnet.resource_type != ResourceType.SUBNET:
            raise ValueError("Pool only owns SUBNET resources")
        self.subnets[subnet.id.value] = subnet
        self._events.append(SubnetAttachedToPool(
            pool_id=self.id.value, subnet_id=subnet.id.value))
        return subnet

    def add_reservation(self, reservation: Reservation) -> Reservation:
        reservation.pool_id = self.id
        self.reservations[reservation.id.value] = reservation
        self._events.append(ReservationRecorded(
            pool_id=self.id.value, reservation_id=reservation.id.value,
            reserved_for=reservation.reserved_for))
        return reservation

    def record_capacity(self, capacity: Capacity) -> None:
        self.capacity = capacity

    def record_utilization(self, utilization: Utilization) -> None:
        self.utilization = utilization

    def record_fragmentation(self, fragmentation: Fragmentation) -> None:
        self.fragmentation = fragmentation

    def record_growth(self, growth: GrowthInfo) -> None:
        self.growth = growth

    # ── read views ───────────────────────────────────────────────────────────
    def list_subnets(self) -> List[NetworkResource]:
        return list(self.subnets.values())

    def list_reservations(self) -> List[Reservation]:
        return list(self.reservations.values())

    def pull_events(self) -> List[DomainEvent]:
        out, self._events = self._events, []
        return out
