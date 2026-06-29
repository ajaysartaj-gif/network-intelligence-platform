"""
NRIE · Contracts · Commands
===========================
Write intents for FOUNDATIONAL knowledge only (registering hierarchy, recording
resource knowledge, attaching business context, capturing organizational
knowledge). These are NOT allocation/planning commands — they establish the
knowledge base. Commands are plain data; handlers live in the api/service layer.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class RegisterEnterpriseEntity:
    level: str
    name: str
    parent_id: Optional[str] = None
    owner: str = ""
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecordResource:
    resource_type: str
    name: str
    purpose: str = ""
    hierarchy_ref: Optional[str] = None
    status: str = "planned"
    labels: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AttachBusinessContext:
    attached_to: str
    site_type: str = ""
    business_function: str = ""
    industry: str = ""
    users: int = 0
    criticality: str = "normal"
    services: Dict[str, bool] = field(default_factory=dict)
    compliance: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class CaptureOrganizationalKnowledge:
    kind: str
    title: str
    body: str = ""
    tags: List[str] = field(default_factory=list)
