"""
core/knowledge/compiler/protocol_models.py
=============================================
Protocol State Model Compiler — a small, generic state-machine
representation, seeded with exactly TWO verified models: OSPF neighbor
adjacency (RFC 2328) and STP port states (802.1D). Both are textbook,
unambiguous, and OSPF's states already appear in this package's
tokens.py::_STATE_WORDS and semantic_analyzer.py::_NEIGHBOR_ROW.

Deliberately NOT seeded: BGP/EIGRP/ISIS/MPLS/VXLAN/EVPN/VRRP/HSRP/LACP.
Several of these have real vendor/version-specific nuance (HSRP vs VRRP
timers and state names differ; LACP spans multiple RFC revisions) that I
cannot verify precisely enough to assert as "compiled knowledge" without
risking a WRONG transition table — worse than no table at all. The
registry mechanism is fully generic (PROTOCOL_STATE_MODELS is just a
dict); adding a new protocol is one new ProtocolStateModel entry, same
"registry, not a rewrite" shape as every other extension point in this
package.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ProtocolTransition:
    from_state: str
    to_state: str
    trigger: str


@dataclass
class ProtocolStateModel:
    protocol: str
    states: List[str] = field(default_factory=list)
    transitions: List[ProtocolTransition] = field(default_factory=list)

    def next_states(self, current: str) -> List[str]:
        current_norm = (current or "").strip().lower()
        return [t.to_state for t in self.transitions if t.from_state.lower() == current_norm]

    def is_valid_transition(self, from_state: str, to_state: str) -> bool:
        f, t = (from_state or "").lower(), (to_state or "").lower()
        return any(tr.from_state.lower() == f and tr.to_state.lower() == t for tr in self.transitions)


_OSPF_NEIGHBOR = ProtocolStateModel(
    protocol="ospf",
    states=["Down", "Attempt", "Init", "2-Way", "ExStart", "Exchange", "Loading", "Full"],
    transitions=[
        ProtocolTransition("Down", "Attempt", "unicast hello sent (NBMA)"),
        ProtocolTransition("Down", "Init", "hello received"),
        ProtocolTransition("Attempt", "Init", "hello received"),
        ProtocolTransition("Init", "2-Way", "hello received with own router ID (bidirectional)"),
        ProtocolTransition("2-Way", "ExStart", "elected DR/BDR or point-to-point, adjacency begins"),
        ProtocolTransition("ExStart", "Exchange", "master/slave and initial sequence number negotiated"),
        ProtocolTransition("Exchange", "Loading", "DBD exchange complete, LSRs outstanding"),
        ProtocolTransition("Loading", "Full", "all LSRs satisfied"),
        ProtocolTransition("Exchange", "Full", "no LSRs needed"),
        # regression edges — a lost hello or bad DBD drops the adjacency back down
        ProtocolTransition("Full", "Down", "dead-interval expired / interface down"),
        ProtocolTransition("2-Way", "Down", "dead-interval expired"),
    ],
)

_STP_PORT = ProtocolStateModel(
    protocol="stp",
    states=["Disabled", "Blocking", "Listening", "Learning", "Forwarding"],
    transitions=[
        ProtocolTransition("Disabled", "Blocking", "port enabled"),
        ProtocolTransition("Blocking", "Listening", "forward delay timer / selected as root or designated"),
        ProtocolTransition("Listening", "Learning", "forward delay timer expires"),
        ProtocolTransition("Learning", "Forwarding", "forward delay timer expires"),
        ProtocolTransition("Forwarding", "Blocking", "superior BPDU received (topology change)"),
        ProtocolTransition("Listening", "Blocking", "superior BPDU received"),
        ProtocolTransition("Learning", "Blocking", "superior BPDU received"),
    ],
)

PROTOCOL_STATE_MODELS: Dict[str, ProtocolStateModel] = {
    "ospf": _OSPF_NEIGHBOR,
    "stp": _STP_PORT,
}


def build_protocol_model(protocol: str) -> Optional[ProtocolStateModel]:
    """Returns the seeded model for `protocol`, or None — deliberately
    never fabricates a transition table for a protocol not in the
    registry."""
    return PROTOCOL_STATE_MODELS.get((protocol or "").strip().lower())
