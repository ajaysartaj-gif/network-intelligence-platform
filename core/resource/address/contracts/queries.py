"""
NRIE · Contracts · Queries
==========================
Read intents. Each maps to a read-only API method returning DTOs.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class GetEnterpriseHierarchy:
    root_id: Optional[str] = None        # None → full hierarchy


@dataclass(frozen=True)
class GetResourceHierarchy:
    hierarchy_ref: Optional[str] = None
    resource_type: Optional[str] = None


@dataclass(frozen=True)
class GetBusinessContext:
    attached_to: str


@dataclass(frozen=True)
class GetKnowledge:
    kind: Optional[str] = None


@dataclass(frozen=True)
class GetOrganizationalStandards:
    kind: Optional[str] = None
