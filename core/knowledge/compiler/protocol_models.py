"""
core/knowledge/compiler/protocol_models.py
=============================================
Protocol State Model Compiler — a small, generic state-machine
representation, seeded with six verified models: OSPF neighbor adjacency
(RFC 2328), STP port states (802.1D), BGP peer session states (RFC 4271),
LACP port-bundling state (802.3ad/802.1AX), HSRP group state (RFC 2281,
Cisco proprietary but textbook-documented), and VRRP router state
(RFC 5798). All six are textbook, unambiguous, and their states already
appear in this package's tokens.py::_STATE_WORDS and
semantic_analyzer.py::_NEIGHBOR_ROW (or are added there alongside this
model, for HSRP/VRRP).

LACP's model is deliberately scoped to the OBSERVABLE port-bundling state
from "show etherchannel summary" (Down/Individual/Suspended/Bundled) —
NOT the full internal 802.3ad Actor/Partner state machine (LACP_Activity,
Aggregation, Synchronization, Collecting, Distributing, Defaulted,
Expired flags), which isn't what an operator observes directly via CLI
and would risk asserting internal detail I can't verify precisely enough.
Same principle as OSPF/BGP: model what's textbook AND observable, not
protocol internals.

HSRP and VRRP are DELIBERATELY kept as two SEPARATE models rather than
one generic "FHRP" model, because their real, vendor-documented state
names and defaults genuinely differ: HSRP's RFC 2281 states are
Init/Learn/Listen/Speak/Standby/Active with preemption OFF by default;
VRRP's RFC 5798 states are Initialize/Backup/Master with preemption ON
by default. Asserting a single shared model would blur a real, commonly
misunderstood difference (a lot of real-world VRRP "won't fail back"
reports trace to someone assuming HSRP's off-by-default behavior).

Deliberately NOT seeded (yet): EIGRP/ISIS/MPLS/VXLAN/EVPN. These have
real vendor/version-specific nuance I cannot verify precisely enough to
assert as "compiled knowledge" without risking a WRONG transition table —
worse than no table at all. The registry mechanism is fully generic
(PROTOCOL_STATE_MODELS is just a dict); adding a new protocol is one new
ProtocolStateModel entry, same "registry, not a rewrite" shape as every
other extension point in this package.
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

_BGP_NEIGHBOR = ProtocolStateModel(
    protocol="bgp",
    states=["Idle", "Connect", "Active", "OpenSent", "OpenConfirm", "Established"],
    transitions=[
        ProtocolTransition("Idle", "Connect", "TCP connection initiated"),
        ProtocolTransition("Connect", "Active", "TCP connection failed, retrying"),
        ProtocolTransition("Connect", "OpenSent", "TCP connection succeeded, OPEN sent"),
        ProtocolTransition("Active", "Connect", "TCP retry timer, reattempting connection"),
        ProtocolTransition("Active", "OpenSent", "TCP connection finally succeeded, OPEN sent"),
        ProtocolTransition("OpenSent", "OpenConfirm", "valid OPEN received, KEEPALIVE sent"),
        ProtocolTransition("OpenSent", "Active", "OPEN error or connection collapse"),
        ProtocolTransition("OpenConfirm", "Established", "KEEPALIVE received"),
        # regression edges — a hold-timer expiry or NOTIFICATION drops the
        # session all the way back to Idle, not to some intermediate state
        ProtocolTransition("OpenConfirm", "Idle", "hold timer expired / NOTIFICATION received"),
        ProtocolTransition("Established", "Idle", "hold timer expired / session reset"),
    ],
)

_LACP_PORT = ProtocolStateModel(
    protocol="lacp",
    states=["Down", "Individual", "Suspended", "Bundled"],
    transitions=[
        ProtocolTransition("Down", "Individual", "link up, LACP negotiation starts but partner not yet agreeing"),
        ProtocolTransition("Down", "Bundled", "link up, LACP negotiation succeeds immediately"),
        ProtocolTransition("Individual", "Bundled", "partner starts responding correctly / mode corrected"),
        ProtocolTransition("Suspended", "Bundled", "parameter mismatch on this member resolved"),
        # regression edges
        ProtocolTransition("Bundled", "Suspended", "parameter mismatch develops (VLAN/trunk/STP inconsistency)"),
        ProtocolTransition("Bundled", "Down", "member link goes down"),
        ProtocolTransition("Individual", "Down", "member link goes down"),
    ],
)

_HSRP_GROUP = ProtocolStateModel(
    protocol="hsrp",
    states=["Init", "Learn", "Listen", "Speak", "Standby", "Active"],
    transitions=[
        ProtocolTransition("Init", "Learn", "interface up, virtual IP not yet known"),
        ProtocolTransition("Init", "Listen", "interface up, virtual IP already configured"),
        ProtocolTransition("Learn", "Listen", "virtual IP learned from an Active router's hello"),
        ProtocolTransition("Listen", "Speak", "active/standby timer expires, no hello heard from a peer"),
        ProtocolTransition("Speak", "Standby", "lost the priority election to a peer"),
        ProtocolTransition("Speak", "Active", "won the priority election (highest priority/IP)"),
        ProtocolTransition("Standby", "Active", "Active router's hold timer expires (stops hearing hellos)"),
        # regression edges — an interface flap restarts the whole FSM
        ProtocolTransition("Active", "Init", "interface down / HSRP disabled"),
        ProtocolTransition("Standby", "Init", "interface down / HSRP disabled"),
    ],
)

_VRRP_ROUTER = ProtocolStateModel(
    protocol="vrrp",
    states=["Initialize", "Backup", "Master"],
    transitions=[
        ProtocolTransition("Initialize", "Master", "is the IP address owner, or priority 255, or no Master seen"),
        ProtocolTransition("Initialize", "Backup", "not the address owner and a Master is already present"),
        ProtocolTransition("Backup", "Master", "Master_Down_Timer expires (Master stops advertising)"),
        # regression edges
        ProtocolTransition("Master", "Backup", "higher-priority advertisement received AND preempt is enabled"),
        ProtocolTransition("Master", "Initialize", "interface down / VRRP disabled"),
        ProtocolTransition("Backup", "Initialize", "interface down / VRRP disabled"),
    ],
)

PROTOCOL_STATE_MODELS: Dict[str, ProtocolStateModel] = {
    "ospf": _OSPF_NEIGHBOR,
    "stp": _STP_PORT,
    "bgp": _BGP_NEIGHBOR,
    "lacp": _LACP_PORT,
    "hsrp": _HSRP_GROUP,
    "vrrp": _VRRP_ROUTER,
}


def build_protocol_model(protocol: str) -> Optional[ProtocolStateModel]:
    """Returns the seeded model for `protocol`, or None — deliberately
    never fabricates a transition table for a protocol not in the
    registry."""
    return PROTOCOL_STATE_MODELS.get((protocol or "").strip().lower())
