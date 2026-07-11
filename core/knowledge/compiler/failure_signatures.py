"""
core/knowledge/compiler/failure_signatures.py
================================================
Failure Signature Library — deterministic, textbook root-cause signatures
compiled from each protocol's VERIFIED state model
(core/knowledge/compiler/protocol_models.py, seeded with OSPF, STP, BGP,
and LACP). Confidence is honestly hedged per signature, grounded in
real-world reported frequency, not uniform: ExStart/MTU, BGP Active
(repeated TCP failures), and LACP Individual (LACPDU/mode mismatch) are
well-established, frequently-cited signatures (high confidence); a
"stuck" state with many possible causes (Down, Exchange, Loading, BGP
OpenSent) gets a lower confidence rather than false precision. 2-Way is
explicitly noted as often a NORMAL stable state, not a failure, on
broadcast networks between two DROTHERs — a real nuance worth stating
rather than flagging every 2-Way sighting as a problem.

Returns [] for any protocol without a seeded model in protocol_models.py
— NEVER fabricates a signature for EIGRP/ISIS/MPLS/VXLAN/EVPN/HSRP/VRRP/
RSTP, consistent with the original scoping decision (those protocols are
on the roadmap, not yet verified precisely enough to seed).

compile_acl_deny_signature() is independently grounded — it reads Phase
1's already-compiled `acl` NormalizedObjects directly (a deny rule IS the
failure signature, not an inference from a state machine).
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

_SIGNATURE_LIBRARY = {"ospf": _OSPF_SIGNATURES, "stp": _STP_SIGNATURES, "bgp": _BGP_SIGNATURES,
                      "lacp": _LACP_SIGNATURES}


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
