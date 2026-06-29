"""
NRIE · Address Domain · Domain Events
=====================================

Immutable facts about things that have happened in the domain. They are records
only — no handling, dispatch, or side effects here. The Orchestrator consumes
their contract mirror (contracts/events.py).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class DomainEvent:
    occurred_at: float = field(default_factory=time.time)

    @property
    def name(self) -> str:
        return type(self).__name__


@dataclass(frozen=True)
class EnterpriseEntityRegistered(DomainEvent):
    entity_id: str = ""
    level: str = ""
    name: str = ""
    parent_id: Optional[str] = None


@dataclass(frozen=True)
class ResourceRecorded(DomainEvent):
    resource_id: str = ""
    resource_type: str = ""
    name: str = ""
    hierarchy_ref: Optional[str] = None


@dataclass(frozen=True)
class BusinessContextAttached(DomainEvent):
    context_id: str = ""
    attached_to: Optional[str] = None


@dataclass(frozen=True)
class KnowledgeCaptured(DomainEvent):
    knowledge_id: str = ""
    kind: str = ""
    title: str = ""
