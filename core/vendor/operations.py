"""
Universal Vendor Adapter Framework — normalized operations & remediation intent
===============================================================================
The engine expresses WHAT it wants (normalized) — never HOW (vendor syntax).

Operation names below are well-known but NOT exhaustive ("including but not
limited to"). The engine may reference any operation name; adapters advertise
which they support and a generic adapter can attempt the rest.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


class Op:
    """Illustrative catalogue of normalized read operations (NOT exhaustive)."""
    GET_NEIGHBORS = "get_neighbors"
    GET_INTERFACE_DETAILS = "get_interface_details"
    GET_ROUTING_INFORMATION = "get_routing_information"
    GET_CONFIGURATION = "get_configuration"
    EXECUTE_VERIFICATION = "execute_verification"
    COLLECT_EVIDENCE = "collect_evidence"
    GET_INVENTORY = "get_inventory"
    GET_TELEMETRY = "get_telemetry"


# Well-known operation names as a set for discovery/validation (extensible).
KNOWN_OPERATIONS = {
    v for k, v in vars(Op).items() if not k.startswith("_") and isinstance(v, str)
}


@dataclass
class Operation:
    """A vendor-neutral request for evidence."""
    name: str
    params: Dict[str, Any] = field(default_factory=dict)   # e.g. {"protocol": "ospf"}
    purpose: str = ""


@dataclass
class RemediationIntent:
    """A vendor-neutral description of the change to make. The engine produces
    only this; adapters translate it into vendor configuration + rollback."""
    name: str                              # free-form, e.g. "ignore_protocol_mtu"
    params: Dict[str, Any] = field(default_factory=dict)   # e.g. {"protocol": "ospf", "interface": "..."}
    target_device: str = ""
    rationale: str = ""


@dataclass
class RemediationPlan:
    """What an adapter returns for an intent — all vendor syntax lives here."""
    fix_commands: List[str] = field(default_factory=list)
    rollback_commands: List[str] = field(default_factory=list)
    verification_commands: List[str] = field(default_factory=list)
    explanation: str = ""
    supported: bool = True
