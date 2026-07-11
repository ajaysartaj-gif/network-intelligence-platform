"""
core/knowledge/compiler/failure_signatures.py
================================================
Failure Signature Library — deterministic, textbook root-cause signatures
compiled from each protocol's VERIFIED state model
(core/knowledge/compiler/protocol_models.py, seeded with OSPF, STP, BGP,
LACP, HSRP, and VRRP). Confidence is honestly hedged per signature,
grounded in real-world reported frequency, not uniform: ExStart/MTU, BGP
Active (repeated TCP failures), and LACP Individual (LACPDU/mode
mismatch) are well-established, frequently-cited signatures (high
confidence); a "stuck" state with many possible causes (Down, Exchange,
Loading, BGP OpenSent) gets a lower confidence rather than false
precision. 2-Way is explicitly noted as often a NORMAL stable state, not
a failure, on broadcast networks between two DROTHERs — a real nuance
worth stating rather than flagging every 2-Way sighting as a problem.
HSRP's Standby and VRRP's Backup get the same honest treatment: each is
normally a healthy state, but the single most commonly reported real
complaint in each ("won't fail over even though the peer is down") is a
missing/disabled preempt configuration — well-documented enough in each
protocol to earn the same confidence tier as BGP's Active/LACP's
Individual, even though HSRP defaults preempt OFF while VRRP defaults it
ON (so the wording of each cause deliberately differs even though the
number doesn't).

Returns [] for any protocol without a seeded model in protocol_models.py
— NEVER fabricates a signature for EIGRP/ISIS/MPLS/VXLAN/EVPN/RSTP,
consistent with the original scoping decision (those protocols are on
the roadmap, not yet verified precisely enough to seed).

compile_acl_deny_signature(), compile_nat_role_signature(), and
compile_vlan_native_mismatch_signature() are all independently grounded —
they read Phase 1's already-compiled `acl`/`nat`/`vlan_native_mismatch`
NormalizedObjects directly (a deny rule, a missing NAT inside/outside
role, or a CDP-detected native VLAN mismatch, IS the failure signature,
not an inference from a state machine). None of ACL/NAT/VLAN has a
ProtocolStateModel at all (there's no "stuck state" FSM for a firewall
rule, an address-translation role, or a trunk-link comparison) — these
three functions are a deliberately different, reactive shape from every
FSM-based signature above: they only exist once real device output has
actually been read, not seeded as a prior beforehand.
"""
from __future__ import annotations

from typing import List

from core.knowledge.compiler.artifacts import FailureSignature
from core.knowledge.compiler.protocol_models import build_protocol_model
from core.vendor.models import NormalizedObject

_OSPF_SIGNATURES = {
    "Down": FailureSignature(
        protocol="ospf", stuck_state="Down",
        likely_cause="No hello packets exchanged — Layer 1/2 connectivity issue, "
                    "OSPF not enabled on the interface, or an ACL blocking IP protocol 89",
        evidence_fields=["admin_state"], confidence=0.55),
    "Attempt": FailureSignature(
        protocol="ospf", stuck_state="Attempt",
        likely_cause="Statically configured NBMA neighbor not responding to unicast hellos",
        evidence_fields=[], confidence=0.5),
    "Init": FailureSignature(
        protocol="ospf", stuck_state="Init",
        likely_cause="Hello/dead interval or area ID mismatch between neighbors",
        evidence_fields=["timer_type", "areas"], confidence=0.75),
    "2-Way": FailureSignature(
        protocol="ospf", stuck_state="2-Way",
        likely_cause="Often a NORMAL stable state between two DROTHERs on a broadcast "
                    "network (no adjacency required) — only a concern if full adjacency "
                    "with the DR/BDR was expected and isn't forming",
        evidence_fields=[], confidence=0.4),
    "ExStart": FailureSignature(
        protocol="ospf", stuck_state="ExStart",
        likely_cause="MTU mismatch between OSPF neighbors prevents DBD packet exchange",
        evidence_fields=["mtu"], confidence=0.85),
    "Exchange": FailureSignature(
        protocol="ospf", stuck_state="Exchange",
        likely_cause="DBD sequence number mismatch or packet loss during database exchange",
        evidence_fields=[], confidence=0.5),
    "Loading": FailureSignature(
        protocol="ospf", stuck_state="Loading",
        likely_cause="LSA retransmission — link congestion or packet loss (LSR/LSU unacknowledged)",
        evidence_fields=[], confidence=0.5),
}

_STP_SIGNATURES = {
    "Blocking": FailureSignature(
        protocol="stp", stuck_state="Blocking",
        likely_cause="Superior BPDU received from another switch (legitimate redundant-"
                    "path block, or a root-guard/BPDU-guard candidate if unexpected)",
        evidence_fields=[], confidence=0.6),
    # "ErrDisabled" isn't one of 802.1D's own 5 FSM states (it's a Cisco
    # port-administrative action BPDU Guard takes, layered ON TOP of STP) —
    # but it's DIRECTLY observed (a specific, unambiguous status string in
    # "show interfaces status"), not inferred, so it earns a high
    # confidence the same way ACL's deny-hit signature does. Deliberately
    # has NO mapped remediation intent (see _REMEDIATION_INTENTS below):
    # blindly clearing an err-disabled BPDU-Guard port ("shutdown"/"no
    # shutdown") could reintroduce a real bridging loop if a switch or hub
    # really was plugged into what should be an access port — this is a
    # judgment call that belongs to a human, not an automatic fix, same
    # safety principle as this platform's deliberate exclusion of
    # auto-enabled debug/packet-capture.
    "ErrDisabled": FailureSignature(
        protocol="stp", stuck_state="ErrDisabled",
        likely_cause="Port was administratively disabled by BPDU Guard after receiving "
                    "a BPDU on a PortFast-enabled edge port — almost always means "
                    "either PortFast is misconfigured on a port that's actually "
                    "connected to another switch/hub, or an unintended switch/hub "
                    "was plugged into this access port",
        evidence_fields=["portfast", "bpduguard"], confidence=0.8),
}

# Confidence grounded in real-world frequency (Cisco/Juniper docs, community
# threads), not uniform: Active (repeated TCP failures — wrong neighbor IP/
# no route/ACL) is by far the most commonly reported stuck state, so it gets
# the highest confidence; OpenSent (AS/version mismatch) is comparatively
# rare/short-lived, so it gets the lowest.
_BGP_SIGNATURES = {
    "Idle": FailureSignature(
        protocol="bgp", stuck_state="Idle",
        likely_cause="Neighbor administratively shut down, or no route exists to the "
                    "peer address — BGP never even attempts to connect",
        evidence_fields=["admin_state", "route_to_peer"], confidence=0.5),
    "Connect": FailureSignature(
        protocol="bgp", stuck_state="Connect",
        likely_cause="TCP port 179 appears reachable but the peer isn't completing the "
                    "handshake — an ACL or firewall along the path is the most common cause",
        evidence_fields=["acl"], confidence=0.6),
    "Active": FailureSignature(
        protocol="bgp", stuck_state="Active",
        likely_cause="Repeated TCP connection failures to the peer address — wrong "
                    "neighbor IP, no route to the peer, or an ACL/firewall blocking "
                    "TCP port 179",
        evidence_fields=["neighbor_ip", "route_to_peer", "acl"], confidence=0.7),
    "OpenSent": FailureSignature(
        protocol="bgp", stuck_state="OpenSent",
        likely_cause="Local OPEN message sent but the peer's OPEN was rejected — "
                    "commonly a remote-AS mismatch or a BGP version mismatch",
        evidence_fields=["remote_as"], confidence=0.55),
    "OpenConfirm": FailureSignature(
        protocol="bgp", stuck_state="OpenConfirm",
        likely_cause="OPEN messages exchanged but KEEPALIVE never confirmed — commonly "
                    "an MD5 authentication mismatch or an MTU mismatch preventing "
                    "larger BGP messages",
        evidence_fields=["auth", "mtu"], confidence=0.6),
}

# Individual is by far the most commonly reported LACP problem (community/
# vendor consensus: neighbor not sending LACPDUs, active/PAgP/passive mode
# mismatch, or both ends passive so neither side initiates) — highest
# confidence. Suspended (a real parameter mismatch the switch actively
# protects the channel from) is well-understood but less frequently the
# FIRST symptom reported. Down is generic (many possible causes) and gets
# the lowest confidence, same pattern as OSPF's Down/BGP's Idle.
_LACP_SIGNATURES = {
    "Individual": FailureSignature(
        protocol="lacp", stuck_state="Individual",
        likely_cause="Neighbor not sending LACPDUs, an LACP mode mismatch (one side "
                    "static/PAgP while the other is LACP), or both ends configured "
                    "passive so neither side initiates negotiation",
        evidence_fields=["lacp_mode", "channel_protocol"], confidence=0.75),
    "Suspended": FailureSignature(
        protocol="lacp", stuck_state="Suspended",
        likely_cause="Parameter mismatch on this member link (allowed VLANs, native "
                    "VLAN, trunk mode, or STP-related) — the switch suspends the port "
                    "to protect the channel rather than bundling a mismatched link",
        evidence_fields=["allowed_vlans", "native_vlan", "trunk_mode"], confidence=0.65),
    "Down": FailureSignature(
        protocol="lacp", stuck_state="Down",
        likely_cause="Member link is physically down or administratively disabled — "
                    "Layer 1/2 issue upstream of LACP negotiation entirely",
        evidence_fields=["admin_state"], confidence=0.4),
}

# Init is generic (interface down/HSRP disabled/no IP — many possible
# causes, same tier as OSPF's Down/BGP's Idle). Listen (never hearing a
# hello from any Active/Standby peer) is the most commonly cited real
# HSRP complaint — usually a VLAN/trunk misconfiguration or an ACL
# blocking the HSRP multicast hello (UDP 1985 to 224.0.0.2). Speak (stuck
# mid-election) is rarer/more ambiguous. Standby is normally healthy —
# flagged only because "won't take over when Active fails" is real and
# well-documented, and HSRP's preempt is OFF by default, so this is often
# exactly what's missing.
_HSRP_SIGNATURES = {
    "Init": FailureSignature(
        protocol="hsrp", stuck_state="Init",
        likely_cause="HSRP not enabled on the interface, interface administratively "
                    "down, or the interface has no usable IP address — the FSM "
                    "never starts",
        evidence_fields=["admin_state"], confidence=0.45),
    "Listen": FailureSignature(
        protocol="hsrp", stuck_state="Listen",
        likely_cause="No HSRP hellos heard from any Active/Standby peer — commonly "
                    "a VLAN or trunk native-VLAN misconfiguration, or an ACL "
                    "blocking the HSRP multicast hello (UDP 1985 to 224.0.0.2) "
                    "between the routers",
        evidence_fields=["vlan", "acl"], confidence=0.65),
    "Speak": FailureSignature(
        protocol="hsrp", stuck_state="Speak",
        likely_cause="Announcing itself as a candidate but the election with a "
                    "peer isn't completing — most often a priority tie or an "
                    "authentication-string mismatch between the HSRP group members",
        evidence_fields=["priority", "auth"], confidence=0.55),
    "Standby": FailureSignature(
        protocol="hsrp", stuck_state="Standby",
        likely_cause="Correctly Standby, but will NOT take over if the Active "
                    "router fails, because 'standby preempt' is not configured — "
                    "HSRP's preempt is OFF by default, so this is the single most "
                    "commonly reported HSRP failover complaint",
        evidence_fields=["preempt_configured"], confidence=0.7),
}

# Initialize mirrors OSPF's Down/BGP's Idle/HSRP's Init (generic, many
# causes). Backup gets the SAME "won't fail over" treatment as HSRP's
# Standby, but with a materially different story: VRRP enables preempt
# BY DEFAULT, so a higher-priority router stuck in Backup while a
# lower-priority peer keeps advertising almost always means preempt was
# explicitly turned OFF ("no vrrp <group> preempt") — not merely "never
# turned on" the way HSRP's equivalent gap works.
_VRRP_SIGNATURES = {
    "Initialize": FailureSignature(
        protocol="vrrp", stuck_state="Initialize",
        likely_cause="VRRP not enabled on the interface, interface administratively "
                    "down, or the interface has no usable IP address — the FSM "
                    "never starts",
        evidence_fields=["admin_state"], confidence=0.45),
    "Backup": FailureSignature(
        protocol="vrrp", stuck_state="Backup",
        likely_cause="This router has a higher configured priority but remains "
                    "Backup behind a lower-priority Master — since VRRP enables "
                    "preemption by default, this almost always means preemption "
                    "was explicitly disabled ('no vrrp <group> preempt') on this "
                    "router",
        evidence_fields=["preempt_enabled", "priority"], confidence=0.7),
}

_SIGNATURE_LIBRARY = {"ospf": _OSPF_SIGNATURES, "stp": _STP_SIGNATURES, "bgp": _BGP_SIGNATURES,
                      "lacp": _LACP_SIGNATURES, "hsrp": _HSRP_SIGNATURES, "vrrp": _VRRP_SIGNATURES}


def compile_failure_signatures(protocol: str) -> List[FailureSignature]:
    """Returns the seeded failure signatures for `protocol`'s states. []
    for any protocol without a verified state model — never a guess."""
    protocol = (protocol or "").strip().lower()
    if build_protocol_model(protocol) is None:
        return []
    return list(_SIGNATURE_LIBRARY.get(protocol, {}).values())


def compile_acl_deny_signature(acl_objects: List[NormalizedObject]) -> List[FailureSignature]:
    """One signature per distinct denying ACL rule, read directly from
    Phase 1's compiled `acl` NormalizedObjects — a deny rule IS the
    signature, not an inference, so confidence is high."""
    signatures: List[FailureSignature] = []
    for obj in acl_objects:
        if obj.type != "acl" or obj.get("action") != "deny":
            continue
        acl_name = obj.get("acl_name", "")
        rule = obj.get("rule", "")
        signatures.append(FailureSignature(
            protocol="acl", stuck_state="deny_hit",
            likely_cause=f"Traffic denied by ACL '{acl_name}' rule: {rule}",
            evidence_fields=["action", "rule"], confidence=0.9))
    return signatures


def compile_nat_role_signature(nat_objects: List[NormalizedObject]) -> List[FailureSignature]:
    """Reads Phase 1's already-compiled `nat` NormalizedObjects (from
    "show ip nat statistics") directly — a missing 'ip nat inside' or
    'ip nat outside' interface role IS the signature, not an inference:
    NAT cannot translate anything without at least one interface of each
    role configured, regardless of any other configuration, so this is
    among the most commonly reported real "NAT isn't working at all"
    causes. High confidence (directly observed, unambiguous).

    Deliberately has NO mapped remediation intent (see reasoning_artifact_
    compiler.py): auto-assigning 'ip nat inside'/'ip nat outside' to a
    GUESSED interface risks getting the role backwards (translating the
    wrong direction, or exposing the wrong network) — worse than leaving
    NAT unconfigured. Same safety principle as ACL's deny-hit signature
    and STP's ErrDisabled signature both having no auto-fix either."""
    signatures: List[FailureSignature] = []
    for obj in nat_objects:
        if obj.type != "nat":
            continue
        if int(obj.get("inside_count", 0) or 0) == 0:
            signatures.append(FailureSignature(
                protocol="nat", stuck_state="no_inside_interface",
                likely_cause="No interface is configured as 'ip nat inside' — NAT has "
                            "no interface to translate traffic FROM, so nothing gets "
                            "translated regardless of any other configuration",
                evidence_fields=["inside_count"], confidence=0.85))
        if int(obj.get("outside_count", 0) or 0) == 0:
            signatures.append(FailureSignature(
                protocol="nat", stuck_state="no_outside_interface",
                likely_cause="No interface is configured as 'ip nat outside' — NAT has "
                            "no interface to translate traffic TO, so nothing gets "
                            "translated regardless of any other configuration",
                evidence_fields=["outside_count"], confidence=0.85))
    return signatures


def compile_vlan_native_mismatch_signature(vlan_objects: List[NormalizedObject]) -> List[FailureSignature]:
    """Reads Phase 1's already-compiled `vlan_native_mismatch` Normalized-
    Objects (parsed directly from a real %CDP-4-NATIVE_VLAN_MISMATCH
    syslog line in "show logging") directly. Unlike ACL's deny-hit or
    NAT's missing-role signature, this isn't even OUR inference at all —
    CDP itself already did the cross-device comparison and told us the
    two sides disagree, so confidence is higher than any other reactive
    signature in this module.

    VLAN native-mismatch was originally scoped (per the roadmap) to reuse
    this package's existing cross-device Mismatch Investigation machinery
    (core.troubleshooting.strategies.mismatch_bridge / gateway_adapter.py's
    GatewayDeviceAdapter), the same mechanism ospf_adjacency/hsrp_pairing
    use. That machinery's enumerate_relationship() fundamentally requires
    a PROTOCOL neighbor table (it resolves the far end via a router-id
    map built from protocol-specific interface attributes) — a physical
    trunk link has no such protocol-neighbor concept, only a CDP/LLDP
    topology edge, so forcing VLAN through it would need a real rewrite
    of that pairing logic, not a one-file addition, and risks regressing
    OSPF/HSRP's existing pairing behavior. Detecting CDP's OWN mismatch
    log line directly (this function) is honest, correct, and exactly
    what an operator would actually check in practice — not a workaround.

    Deliberately has NO mapped remediation intent: aligning the native
    VLAN is a safe, well-understood FIX in isolation, but WHICH side is
    misconfigured (and therefore which one to change) is a judgment call
    this platform can't safely guess — same principle as every other
    reactive, no-FSM signature in this module."""
    signatures: List[FailureSignature] = []
    for obj in vlan_objects:
        if obj.type != "vlan_native_mismatch":
            continue
        local_if, local_vlan = obj.get("local_interface", "?"), obj.get("local_vlan", "?")
        remote_dev, remote_if = obj.get("remote_device", "?"), obj.get("remote_interface", "?")
        remote_vlan = obj.get("remote_vlan", "?")
        signatures.append(FailureSignature(
            protocol="vlan", stuck_state="native_vlan_mismatch",
            likely_cause=f"CDP detected a native VLAN mismatch on {local_if} (VLAN "
                        f"{local_vlan}) with {remote_dev} {remote_if} (VLAN {remote_vlan}) "
                        f"— the trunk's native VLAN must match on both ends or untagged "
                        f"traffic leaks between VLANs and STP may see it as a loop",
            evidence_fields=["local_vlan", "remote_vlan"], confidence=0.95))
    return signatures


def compile_operational_failure_signatures(recurring: List[dict]) -> List[FailureSignature]:
    """
    Converts core.intelligence.operational_memory.OperationalMemory.
    recurring_failures()'s output — real operational history, not textbook
    protocol knowledge — into the SAME FailureSignature shape the OSPF/STP/
    ACL signatures above use, so patterns LEARNED FROM OPERATIONS join the
    same artifact model rather than living in a separate, second shape.

    Expects the exact dict shape recurring_failures() returns:
    {"signature": str, "count": int, "last_ts": float, "intent": str,
    "protocol": str}. Confidence scales with recurrence count — more
    independent failures of the same signature is stronger evidence this
    is a real pattern, not noise — capped at 0.9 (the same ceiling the
    textbook ExStart/MTU signature uses; operational evidence earns the
    same trust as verified protocol knowledge, never more).
    """
    signatures: List[FailureSignature] = []
    for row in recurring:
        signature = row.get("signature", "")
        count = int(row.get("count", 0) or 0)
        intent = row.get("intent", "") or "(no intent recorded)"
        protocol = (row.get("protocol", "") or "operational").lower()
        confidence = min(0.9, 0.5 + 0.1 * max(0, count - 2))
        signatures.append(FailureSignature(
            protocol=protocol, stuck_state=f"recurring:{signature[:12]}",
            likely_cause=f"Recurring failure pattern (seen {count}x): intent "
                        f"'{intent}' on protocol '{protocol}'",
            evidence_fields=["signature", "count"], confidence=confidence))
    return signatures
