"""Flat capability registries -- mirrors protocol_registry.py's shape.

Adding a technology is two new dict entries (one per registry) and nothing
else: no orchestration code, no executor code, and no policy code branches
on a technology name anywhere in this package.

Only OSPF/HSRP/VRRP are populated today -- the first three registered
technologies, not special cases. Every other technology named in the
platform's requirements (BGP, STP, LACP, MPLS, VXLAN/EVPN, PIM/IGMP, QoS,
NAT, ACL, DHCP, DNS, IP SLA, SD-WAN, firewall, wireless, ...) is deliberately
left out of this pass: each needs real, vendor-doc-verified CLI syntax
before it can safely go in a registry that runs commands against real
devices, the same discipline already applied to this platform's read-only
protocol knowledge base.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .capability import DiagnosticActionSpec, DiagnosticCapability, Precondition, PreconditionKind

_DEFAULT_PRECONDITIONS: List[Precondition] = [
    Precondition(kind=PreconditionKind.CPU_BELOW, threshold=50.0),
    Precondition(kind=PreconditionKind.LOGGING_BUFFERED),
]

DIAGNOSTIC_CAPABILITIES: Dict[str, DiagnosticCapability] = {
    "ospf": DiagnosticCapability(
        technology="ospf", action="adjacency_debug",
        description="OSPF adjacency state transitions and hello exchange",
        safety_level="low", preconditions=list(_DEFAULT_PRECONDITIONS),
        max_duration_s=10,
        expected_evidence="neighbor state transitions (Down/Init/2-Way/ExStart/.../Full), "
                           "hello/dead timer mismatches, area or authentication rejects",
    ),
    "hsrp": DiagnosticCapability(
        technology="hsrp", action="state_debug",
        description="HSRP group state transitions and role elections",
        safety_level="low", preconditions=list(_DEFAULT_PRECONDITIONS),
        max_duration_s=10,
        expected_evidence="group state transitions (Speak/Standby/Active), priority/"
                           "preempt-driven role changes, duplicate-active conditions",
    ),
    "vrrp": DiagnosticCapability(
        technology="vrrp", action="state_debug",
        description="VRRP group state transitions and role elections",
        safety_level="low", preconditions=list(_DEFAULT_PRECONDITIONS),
        max_duration_s=10,
        expected_evidence="group state transitions (Backup/Master), priority-driven "
                           "role changes, advertisement timer mismatches",
    ),
}

CISCO_DIAGNOSTIC_ACTIONS: Dict[str, DiagnosticActionSpec] = {
    "ospf": DiagnosticActionSpec(enable_commands=["debug ip ospf adj"]),
    "hsrp": DiagnosticActionSpec(enable_commands=["debug standby events"]),
    "vrrp": DiagnosticActionSpec(enable_commands=["debug vrrp events"]),
}

# Keyed by the real vendor string core.vendor.adapters.cisco_ios_like.CiscoLikeAdapter
# reports via VendorProfile.vendor ("ios-like"), so this resolves correctly
# whether the caller went through VendorGateway.resolve() or fell back to the
# same implicit assumption the engine's raw-SSH path already makes.
#
# Additional vendor families register their own flat dict the same way,
# e.g. JUNOS_DIAGNOSTIC_ACTIONS -- populated once real Junos syntax is
# researched (mirrors protocol_registry.py's JUNOS_ADAPTER_SPECS).
_VENDOR_ACTION_REGISTRIES: Dict[str, Dict[str, DiagnosticActionSpec]] = {
    "ios-like": CISCO_DIAGNOSTIC_ACTIONS,
}


def get_capability(technology: str) -> Optional[DiagnosticCapability]:
    return DIAGNOSTIC_CAPABILITIES.get((technology or "").strip().lower())


def get_action_spec(vendor: str, technology: str) -> Optional[DiagnosticActionSpec]:
    registry = _VENDOR_ACTION_REGISTRIES.get((vendor or "").strip().lower())
    if registry is None:
        return None
    return registry.get((technology or "").strip().lower())


def list_technologies() -> List[str]:
    return sorted(DIAGNOSTIC_CAPABILITIES.keys())
