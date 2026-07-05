"""
Semantic normalization = the world model.

Cross-vendor mismatch detection is impossible without it. IOS reports OSPF area
"0"; Junos reports "0.0.0.0" for the SAME area. IOS network type "BROADCAST" ==
Junos "LAN". Compare raw strings and you invent false mismatches on every mixed
link. So the strategy never compares vendor strings -- it compares NORMALIZED
values in one canonical space.

Normalization is keyed by the SEMANTIC read_intent (vendor-neutral), not by vendor.
"Area 0 canonicalizes to integer 0" is a fact about OSPF areas, not about Cisco.
"""
from __future__ import annotations


def _area(v):
    if v is None:
        return None
    if "." in v:                       # dotted-decimal area id -> integer
        p = v.split(".")
        return str(sum(int(x) << (8 * (3 - i)) for i, x in enumerate(p)))
    return str(int(v))


def _int(v):
    return None if v is None else str(int(v))


def _lower(v):
    return None if v is None else v.strip().lower()


def _ntype(v):
    if v is None:
        return None
    t = v.strip().lower()
    if t in ("broadcast", "lan"):
        return "broadcast"
    if t in ("point_to_point", "point-to-point", "p2p", "ptp"):
        return "point_to_point"
    if t in ("nbma", "non-broadcast"):
        return "nbma"
    return t


def _auth(v):
    if v is None:
        return None
    t = v.strip().lower()
    if t in ("none", "no", "null", "disabled"):
        return "none"
    if t in ("md5", "message-digest", "message"):
        return "md5"
    if t in ("simple", "clear", "text", "password"):
        return "clear"
    return t


# read_intent -> canonicalizer. Unknown intents fall back to identity (string).
NORMALIZERS = {
    "ospf_area_id": _area,
    "ospf_hello_interval": _int,
    "ospf_dead_interval": _int,
    "interface_mtu": _int,
    "ospf_network_type": _ntype,
    "ospf_auth": _auth,
    "ospf_network_mask": _lower,
    "ospf_router_id": _lower,
    "hsrp_group_number": _int,
    "hsrp_priority": _int,
    "hsrp_version": _int,
}


def normalize(read_intent: str, value):
    fn = NORMALIZERS.get(read_intent, lambda x: x)
    return fn(value)
