"""
Universal Vendor Adapter Framework — normalized models
======================================================
The Troubleshooting Engine reasons ONLY on these objects. They are vendor-neutral
and open for extension: any future object type is expressed as a NormalizedObject
with a new `type` string — no redesign, no engine change.

Nothing here references any vendor, OS, platform, protocol or command.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ObjectType(str, Enum):
    """Well-known normalized object types. Illustrative, NOT exhaustive —
    adapters may emit any custom type string via NormalizedObject(type=...)."""
    DEVICE = "device"; INTERFACE = "interface"; VRF = "vrf"; ROUTE = "route"
    NEIGHBOR = "neighbor"; PROTOCOL = "protocol"; POLICY = "policy"; ACL = "acl"
    TUNNEL = "tunnel"; TOPOLOGY = "topology"; SERVICE = "service"
    APPLICATION = "application"; FLOW = "flow"; TELEMETRY = "telemetry"
    ALARM = "alarm"; EVENT = "event"; INVENTORY = "inventory"
    CONFIGURATION = "configuration"
    # Added for the Network Knowledge Compiler's Semantic Compiler
    # (core/knowledge/compiler/) — additive only, no existing adapter or
    # engine branches on full enum membership since NormalizedObject.type
    # is a plain str.
    VLAN = "vlan"; QOS = "qos"; NAT = "nat"; SECURITY_RULE = "security_rule"
    CLOUD_RESOURCE = "cloud_resource"


@dataclass
class NormalizedObject:
    """Universal normalized network object.

    `type` may be any ObjectType value OR an arbitrary string for future objects.
    All specifics live in `attributes`, so new fields never require a schema change.
    """
    type: str
    id: str = ""
    device: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.attributes.get(key, default)

    def summary(self) -> str:
        kv = ", ".join(f"{k}={v}" for k, v in list(self.attributes.items())[:6])
        return f"{self.type}[{self.id or '-'}]@{self.device or '-'} {{{kv}}}"


def obj(type_: Any, device: str = "", id: str = "", **attributes) -> NormalizedObject:
    t = type_.value if isinstance(type_, ObjectType) else str(type_)
    return NormalizedObject(type=t, id=id, device=device, attributes=attributes)


class ErrorClass(str, Enum):
    """Normalized error classes. Illustrative, NOT exhaustive."""
    PERMISSION = "permission"; CLI = "cli"; API = "api"
    UNSUPPORTED = "unsupported_feature"; AUTH = "authentication"
    TIMEOUT = "timeout"; RATE_LIMIT = "rate_limit"; TRANSPORT = "transport"
    PARSER = "parser"; UNKNOWN = "unknown"


@dataclass
class NormalizedError:
    error_class: ErrorClass = ErrorClass.UNKNOWN
    message: str = ""
    retriable: bool = False
    raw: str = ""
    source: str = ""            # which adapter/transport produced it


@dataclass
class ValidationResult:
    ok: bool = True
    blocked: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class VendorProfile:
    """Result of adapter.detect(): what the adapter believes the device is.

    Every field is discoverable; none is constrained to a fixed enumeration, so
    new vendors/platforms/OSes need no change here.
    """
    adapter: str = ""           # id of the adapter that produced this profile
    vendor: str = ""
    platform: str = ""
    os: str = ""
    version: str = ""
    model: str = ""
    confidence: float = 0.0     # 0..1 how confident detect() is
    capabilities: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
