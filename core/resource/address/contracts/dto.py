"""
NRIE · Contracts · DTOs
=======================
Flat, serializable read models returned by the read-only API. Independent of the
domain/persistence implementation so consumers (UI, orchestrator) never touch
entities directly.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class EnterpriseNodeDTO:
    id: str
    level: str
    name: str
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)
    lifecycle: str = "active"
    owner: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResourceDTO:
    id: str
    resource_type: str
    name: str
    purpose: str = ""
    hierarchy_ref: Optional[str] = None
    lifecycle: str = "planned"
    status: str = "planned"
    utilization_pct: float = 0.0
    labels: List[str] = field(default_factory=list)
    business_context_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BusinessContextDTO:
    id: str
    attached_to: Optional[str]
    site_type: str = ""
    business_function: str = ""
    industry: str = ""
    users: int = 0
    criticality: str = "normal"
    services: Dict[str, bool] = field(default_factory=dict)  # voice/cctv/guest/iot/ot
    compliance: List[str] = field(default_factory=list)
    sla: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeDTO:
    id: str
    kind: str
    title: str
    body: str = ""
    tags: List[str] = field(default_factory=list)
    lifecycle: str = "active"
