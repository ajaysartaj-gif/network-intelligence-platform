"""
Regression for a real production report: an OSPF area-ID mismatch was
deliberately introduced between two routers, but the resulting report never
showed the two interfaces' configured Area values side by side, and a
compiled "OSPF area ID mismatch" signature (evidence_fields=["area"]) was
ruled out using an unrelated neighbor's healthy state instead of ever being
compared against real area evidence.

Root cause (two compounding bugs in the gateway-mode evidence path):

1. NormalizedObject.summary() (core/vendor/models.py) -- the ONLY channel
   gateway-mode evidence has back to the reasoning engine -- truncated to
   the FIRST 6 attributes by dict-insertion order. IosLikeAdapter's OSPF
   interface parser builds attrs in the order status/mtu/area/network_type/
   ospf_state/hello/dead/router_id/auth/network_mask -- so "auth" (needed
   for the "OSPF authentication mismatch" hypothesis) and several other
   fields never survived the truncation at all, entirely depending on
   insertion order rather than what any hypothesis actually needed.

2. Even for fields that DID survive that truncation (like "area", which
   happened to be within the first 6), TroubleshootingEngine's
   _gateway_object_facts() -- which re-parses summary()'s text back into
   Observations -- only ever extracted "mtu" and "ip_mtu" for interface-type
   objects. "area", "network_type", "ospf_state", "hello", "dead", "auth",
   "router_id" were silently dropped even when present in the parsed kv
   dict, so they could never become comparable evidence regardless of the
   truncation bug above.

Fix: summary() no longer truncates (all attributes are included), and
_gateway_object_facts()'s interface branch now extracts every field the
adapter already collects for exactly this reason.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.troubleshooting.engine import TroubleshootingEngine as Engine
from core.vendor import VendorGateway, Op, Operation, VendorProfile
from core.vendor.adapters.cisco_ios_like import IosLikeAdapter
from core.vendor.models import NormalizedObject


# ── unit: NormalizedObject.summary() no longer truncates ───────────────────

def test_summary_includes_every_attribute_not_just_the_first_six():
    o = NormalizedObject(type="interface", id="Fa0/0", device="10.0.0.1", attributes={
        "ospf": True, "status": "up", "mtu": "1500", "area": "0",
        "network_type": "BROADCAST", "ospf_state": "DR", "hello": "10",
        "dead": "40", "router_id": "10.0.0.1", "auth": "md5", "network_mask": "24",
    })
    text = o.summary()
    m = Engine._GATEWAY_OBJ_LINE.match(text)
    assert m is not None
    kv = dict(p.split("=", 1) for p in m.group("kv").split(", ") if "=" in p)
    # Previously the last 5 of these (beyond the first 6 inserted) would
    # have been silently truncated away -- auth in particular is what the
    # "OSPF authentication mismatch" hypothesis needs to ever be confirmed.
    assert kv["dead"] == "40"
    assert kv["router_id"] == "10.0.0.1"
    assert kv["auth"] == "md5"
    assert kv["network_mask"] == "24"


# ── unit: _gateway_object_facts() surfaces area/network_type/auth/etc. ─────

def test_gateway_object_facts_extracts_area_and_auth_for_interfaces():
    eng = Engine(ai_call=lambda p: "", devices=[])
    line = ("interface[FastEthernet0/0]@10.0.0.1 {ospf=True, status=up, mtu=1500, "
           "area=0, network_type=BROADCAST, ospf_state=DR, hello=10, dead=40, "
           "router_id=10.0.0.1, auth=md5, network_mask=24}")
    facts = eng._gateway_object_facts(line)
    by_attr = {f["attribute"]: f["value"] for f in facts}
    assert by_attr["area"] == "0"
    assert by_attr["network_type"] == "BROADCAST"
    assert by_attr["ospf_state"] == "DR"
    assert by_attr["auth"] == "md5"
    assert by_attr["router_id"] == "10.0.0.1"
    assert by_attr["network_mask"] == "24"
    # mtu/ip_mtu behavior (already correct before this fix) must be unchanged.
    assert by_attr["mtu"] == "1500"


def test_gateway_object_facts_still_ignores_fields_that_are_absent():
    eng = Engine(ai_call=lambda p: "", devices=[])
    line = "interface[Fa0/0]@10.0.0.1 {status=up, mtu=1500}"
    facts = eng._gateway_object_facts(line)
    attrs = {f["attribute"] for f in facts}
    assert attrs == {"mtu"}


# ── real end-to-end: an OSPF area mismatch is now visible as evidence ──────

def test_area_mismatch_between_two_real_devices_is_now_visible_as_evidence():
    """R1 and R2 report DIFFERENT OSPF areas on the interfaces facing each
    other -- exactly the scenario the user manually configured. Both area
    values must now land in session.observations (and therefore in
    _evidence_summary()'s text, which is what the LLM/report actually sees)
    instead of being silently dropped."""
    adapter = IosLikeAdapter()
    profile_r1 = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                               capabilities=[], attributes={"ip": "192.168.96.136"})
    profile_r2 = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                               capabilities=[], attributes={"ip": "192.168.20.2"})

    r1_text = ("FastEthernet0/0 is up, line protocol is up\n"
              "  Internet Address 192.168.96.136/24, Area 0\n"
              "  Process ID 1, Router ID 192.168.96.136, Network Type BROADCAST, Cost: 1\n"
              "  Transmit Delay is 1 sec, State DR, Priority 1\n"
              "  Timer intervals configured, Hello 10, Dead 40, Wait 40, Retransmit 5\n")
    r2_text = ("FastEthernet0/0 is up, line protocol is up\n"
              "  Internet Address 192.168.20.2/24, Area 1\n"
              "  Process ID 1, Router ID 192.168.20.2, Network Type BROADCAST, Cost: 1\n"
              "  Transmit Delay is 1 sec, State DR, Priority 1\n"
              "  Timer intervals configured, Hello 10, Dead 40, Wait 40, Retransmit 5\n")

    r1_objs = adapter.parse_output(Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "ospf"}),
                                   {"show ip ospf interface": r1_text}, profile_r1)
    r2_objs = adapter.parse_output(Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "ospf"}),
                                   {"show ip ospf interface": r2_text}, profile_r2)

    eng = Engine(ai_call=lambda p: "", devices=[])
    r1_line = "\n".join(o.summary() for o in r1_objs)
    r2_line = "\n".join(o.summary() for o in r2_objs)

    r1_facts = eng._gateway_object_facts(r1_line)
    r2_facts = eng._gateway_object_facts(r2_line)
    r1_area = next(f["value"] for f in r1_facts if f["attribute"] == "area")
    r2_area = next(f["value"] for f in r2_facts if f["attribute"] == "area")

    assert r1_area == "0"
    assert r2_area == "1"
    assert r1_area != r2_area  # the actual mismatch -- now a real, comparable fact
