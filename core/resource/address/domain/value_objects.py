"""
NRIE · Address Domain · Value Objects
=====================================

Immutable, equality-by-value building blocks. No persistence, no behaviour
beyond invariant checks. These encode *what things are*, not *what we do* —
there is deliberately NO allocation, planning, or AI logic here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, Mapping, Optional


# ── identity ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Identifier:
    """A stable, opaque identity for any knowledge entity."""
    value: str

    @staticmethod
    def new(prefix: str = "") -> "Identifier":
        return Identifier((f"{prefix}-" if prefix else "") + uuid.uuid4().hex[:16])

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# ── enterprise hierarchy levels (ordered, top → bottom) ──────────────────────
class EnterpriseLevel(str, Enum):
    ORGANIZATION = "organization"
    BUSINESS_UNIT = "business_unit"
    REGION = "region"
    COUNTRY = "country"
    STATE = "state"
    CITY = "city"
    CAMPUS = "campus"
    SITE = "site"
    BUILDING = "building"
    FLOOR = "floor"

    @property
    def rank(self) -> int:
        return _ENTERPRISE_ORDER.index(self)


_ENTERPRISE_ORDER = [
    EnterpriseLevel.ORGANIZATION, EnterpriseLevel.BUSINESS_UNIT, EnterpriseLevel.REGION,
    EnterpriseLevel.COUNTRY, EnterpriseLevel.STATE, EnterpriseLevel.CITY,
    EnterpriseLevel.CAMPUS, EnterpriseLevel.SITE, EnterpriseLevel.BUILDING,
    EnterpriseLevel.FLOOR,
]


# ── resource taxonomy ────────────────────────────────────────────────────────
class ResourceType(str, Enum):
    ADDRESS_SPACE = "address_space"
    ADDRESS_POOL = "address_pool"
    SUBNET = "subnet"
    VLAN = "vlan"
    VRF = "vrf"
    DHCP_POOL = "dhcp_pool"
    DNS_ZONE = "dns_zone"
    GATEWAY = "gateway"
    LOOPBACK = "loopback"
    TRANSIT_NETWORK = "transit_network"
    TUNNEL = "tunnel"
    OVERLAY = "overlay"


class ResourceStatus(str, Enum):
    """Observed status only — NOT an allocation decision."""
    PLANNED = "planned"
    RESERVED = "reserved"
    IN_USE = "in_use"
    FREE = "free"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


# ── lifecycle (shared by enterprise + resource + knowledge) ──────────────────
class Lifecycle(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"
    ARCHIVED = "archived"


# ── business descriptors ─────────────────────────────────────────────────────
class Criticality(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class SLA:
    name: str = ""
    availability: str = ""      # e.g. "99.99%"
    response: str = ""          # e.g. "15m"


@dataclass(frozen=True)
class Ownership:
    owner: str = ""
    team: str = ""
    contact: str = ""


# ── generic descriptors ──────────────────────────────────────────────────────
@dataclass(frozen=True)
class Tags:
    values: FrozenSet[str] = field(default_factory=frozenset)

    @staticmethod
    def of(*items: str) -> "Tags":
        return Tags(frozenset(i.strip().lower() for i in items if i and i.strip()))

    def with_tag(self, tag: str) -> "Tags":
        return Tags(self.values | {tag.strip().lower()})

    def __iter__(self):
        return iter(sorted(self.values))


@dataclass(frozen=True)
class Metadata:
    """An immutable view over arbitrary descriptive attributes."""
    data: Mapping[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def merged(self, **extra: Any) -> "Metadata":
        d: Dict[str, Any] = dict(self.data)
        d.update(extra)
        return Metadata(d)

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.data)


@dataclass(frozen=True)
class Utilization:
    """A recorded utilization observation (no prediction — that's a later PR)."""
    percent: float = 0.0
    sampled_at: float = 0.0

    def __post_init__(self):
        object.__setattr__(self, "percent", max(0.0, min(100.0, float(self.percent))))
