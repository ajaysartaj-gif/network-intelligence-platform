"""
NRIE · Address Domain · Entities
================================

Entities have identity and lifecycle. They hold knowledge state and enforce
small local invariants, but contain NO persistence and NO allocation/planning
logic. Persistence lives in infrastructure; behaviour that spans entities lives
in aggregates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .value_objects import (
    ArchitecturePattern, AvailabilityRequirement, Criticality, EnterpriseLevel,
    GrowthExpectation, Identifier, Lifecycle, Metadata, OperationalModel, Ownership,
    ResourceStatus, ResourceType, RiskClassification, SLA, Tags, Utilization,
)


@dataclass
class EnterpriseEntity:
    """A node in the enterprise hierarchy (Organization … Floor)."""
    id: Identifier
    level: EnterpriseLevel
    name: str
    parent_id: Optional[Identifier] = None
    children_ids: List[Identifier] = field(default_factory=list)
    metadata: Metadata = field(default_factory=Metadata)
    tags: Tags = field(default_factory=Tags)
    lifecycle: Lifecycle = Lifecycle.ACTIVE
    owner: Ownership = field(default_factory=Ownership)

    def add_child(self, child_id: Identifier) -> None:
        if child_id not in self.children_ids:
            self.children_ids.append(child_id)


@dataclass
class NetworkResource:
    """A unit of network resource knowledge (subnet, VLAN, VRF, …).

    Stores *what it is and where it sits* — never how it was allocated.
    """
    id: Identifier
    resource_type: ResourceType
    name: str
    purpose: str = ""
    hierarchy_ref: Optional[Identifier] = None      # the enterprise node it belongs to
    ownership: Ownership = field(default_factory=Ownership)
    lifecycle: Lifecycle = Lifecycle.PLANNED
    status: ResourceStatus = ResourceStatus.PLANNED
    utilization: Utilization = field(default_factory=Utilization)
    metadata: Metadata = field(default_factory=Metadata)
    labels: Tags = field(default_factory=Tags)
    business_context_id: Optional[Identifier] = None


@dataclass
class BusinessContext:
    """Business meaning attachable to any resource or hierarchy node.

    Describes *why* a resource exists (capability, service, owner, criticality,
    compliance, availability, growth, operating/architecture posture, risk) — not
    networking details. Original fields are retained for backward compatibility.
    """
    id: Identifier
    attached_to: Optional[Identifier] = None
    site_type: str = ""
    business_function: str = ""
    industry: str = ""
    users: int = 0
    applications: List[str] = field(default_factory=list)
    voice: bool = False
    cctv: bool = False
    guest: bool = False
    iot: bool = False
    ot: bool = False
    compliance: List[str] = field(default_factory=list)
    criticality: Criticality = Criticality.NORMAL
    sla: SLA = field(default_factory=SLA)
    metadata: Metadata = field(default_factory=Metadata)
    # ── PR-001.1: richer enterprise meaning (why the resource exists) ──
    business_capability: str = ""
    business_service: str = ""
    business_owner: Ownership = field(default_factory=Ownership)
    availability: AvailabilityRequirement = field(default_factory=AvailabilityRequirement)
    growth_expectation: GrowthExpectation = field(default_factory=GrowthExpectation)
    operational_model: OperationalModel = OperationalModel.UNSPECIFIED
    architecture_pattern: ArchitecturePattern = ArchitecturePattern.UNSPECIFIED
    risk_classification: RiskClassification = RiskClassification.LOW


@dataclass
class Reservation:
    """A recorded reservation owned by a Pool (knowledge only — NO allocation).

    It records that capacity is intended to be set aside; it performs no carving,
    sizing, or assignment (those belong to a later Allocation PR).
    """
    id: Identifier
    pool_id: Optional[Identifier] = None
    reserved_for: str = ""
    size_hint_hosts: int = 0
    status: ResourceStatus = ResourceStatus.RESERVED
    metadata: Metadata = field(default_factory=Metadata)


@dataclass
class OrganizationalKnowledge:
    """A stored unit of organizational knowledge (standard, decision, lesson …).

    Knowledge is STORED, not reasoned over here (no AI in this PR).
    """
    id: Identifier
    kind: str            # engineering_standard|naming_standard|address_standard|
                         # architecture_decision|lesson_learned|runbook|
                         # vendor_standard|business_exception|compliance_policy
    title: str
    body: str = ""
    tags: Tags = field(default_factory=Tags)
    lifecycle: Lifecycle = Lifecycle.ACTIVE
    metadata: Metadata = field(default_factory=Metadata)
