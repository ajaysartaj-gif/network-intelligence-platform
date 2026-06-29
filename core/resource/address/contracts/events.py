"""
NRIE · Contracts · Events
=========================
Contract mirror of domain events for the Orchestrator/Event Framework. The
Orchestrator subscribes to THESE, never to domain internals.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EnterpriseEntityRegisteredV1:
    entity_id: str
    level: str
    name: str
    parent_id: Optional[str]
    occurred_at: float


@dataclass(frozen=True)
class ResourceRecordedV1:
    resource_id: str
    resource_type: str
    name: str
    hierarchy_ref: Optional[str]
    occurred_at: float


@dataclass(frozen=True)
class BusinessContextAttachedV1:
    context_id: str
    attached_to: Optional[str]
    occurred_at: float


@dataclass(frozen=True)
class KnowledgeCapturedV1:
    knowledge_id: str
    kind: str
    title: str
    occurred_at: float
