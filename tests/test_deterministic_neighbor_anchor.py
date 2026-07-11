"""
Tests for TroubleshootingEngine._ensure_protocol_state_observed() — the fix
for a real, user-reported bug: a live session pasted a transcript where
plan_operations() (100% LLM-driven, sees only bare operation NAMES with no
descriptions) never once requested get_neighbors/show-ip-ospf-neighbor
across 3 rounds — only get_routing_information, get_interface_details, and
get_configuration. Without ever observing the actual neighbor FSM state,
engine._bind_compiled_signature_evidence()'s one deterministic, high-weight
confirm/contradict pass never fires for ANY compiled signature, so
confidence just drifted on weak LLM guesses (68% top, no fix generated) —
and which secondary command the LLM happened to reach for (and in what
order) varied call to call, which is exactly "different output for the
same issue" from the user's own words.

The fix forces whichever operation actually reveals per-neighbor state
(GET_NEIGHBORS for OSPF/BGP, falling back to GET_INTERFACE_DETAILS for
protocols like LACP/STP/HSRP/VRRP whose AdapterSpec.commands has no
get_neighbors mapping at all) to be collected exactly once, before the LLM
ever forms or extends a hypothesis.
"""
import json
import sys
import types
from pathlib import Path

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.vendor import VendorGateway
from core.troubleshooting import TroubleshootingEngine, TSConfig


class Dev:
    def __init__(self, ip, hostname="R1"):
        self.ip, self.hostname, self.device_type = ip, hostname, "cisco_ios"


# ── OSPF: reproduces the exact reported transcript ──────────────────────
_OSPF_NEIGHBOR_OUTPUT = (
    "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
    "192.168.20.2      1   EXSTART/DR      00:00:39    192.168.20.2    GigabitEthernet1/0\n"
)
_OSPF_INTERFACE_OUTPUT = (
    "GigabitEthernet1/0 is up, line protocol is up\n"
    "  Internet Address 192.168.20.1/24, Area 0\n"
    "  MTU 1500 bytes\n"
)
_OSPF_CONFIG_OUTPUT = "router ospf 1\n network 192.168.20.0 0.0.0.255 area 0\n"
_OSPF_ROUTING_OUTPUT = "O    192.168.30.0/24 [110/2] via 192.168.20.2\n"


def _ospf_command_router(dev, cmds):
    out = {}
    for c in cmds:
        low = c.lower()
        if "neighbor" in low:
            out[c] = _OSPF_NEIGHBOR_OUTPUT
        elif "interface" in low and "running-config" not in low:
            out[c] = _OSPF_INTERFACE_OUTPUT
        elif "route" in low:
            out[c] = _OSPF_ROUTING_OUTPUT
        elif "running-config" in low or "section" in low:
            out[c] = _OSPF_CONFIG_OUTPUT
        else:
            out[c] = ""
    return out


def _make_ai_that_never_picks_neighbors():
    """Rotates through get_routing_information / get_interface_details /
    get_configuration only -- literally never get_neighbors -- matching
    the pasted transcript's own Executed Commands list exactly."""
    calls = {"n": 0}

    def ai(prompt: str) -> str:
        if "Restate this network troubleshooting" in prompt:
            return "Identify and resolve the root cause of OSPF errors in the network."
        if "candidate ROOT CAUSES" in prompt:
            return json.dumps([])
        if "normalized diagnostic OPERATION" in prompt:
            calls["n"] += 1
            rotation = [
                {"device": "all", "operation": "get_routing_information",
                 "params": {"protocol": "ospf"}, "purpose": "routes", "tests_hypotheses": [], "value": 0.6},
                {"device": "all", "operation": "get_interface_details",
                 "params": {"protocol": "ospf"}, "purpose": "mtu/area", "tests_hypotheses": [], "value": 0.7},
                {"device": "all", "operation": "get_configuration",
                 "params": {"protocol": "ospf"}, "purpose": "config", "tests_hypotheses": [], "value": 0.5},
            ]
            return json.dumps([rotation[(calls["n"] - 1) % len(rotation)]])
        if "Interpret this device output" in prompt:
            return json.dumps({"facts": [], "impacts": []})
        return ""
    return ai


def test_ospf_converges_even_when_llm_never_requests_get_neighbors():
    devices = [Dev("192.168.96.136")]
    gw = VendorGateway(send=_ospf_command_router, hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai_that_never_picks_neighbors(),
                               devices=devices, gateway=gw, config=TSConfig(max_steps=4))
    report = eng.run("Identify and resolve the root cause of OSPF errors in the network.")
    s = report.session
    assert any("op:get_neighbors" in e.command for e in s.executed), \
        "get_neighbors must be forced even though the LLM planner never proposed it"
    top = s.top()
    assert top is not None and top.confidence >= 0.8, \
        f"expected high-confidence convergence, got {top.confidence if top else None}"
    assert "MTU" in top.statement
    assert s.fix is not None and any("mtu-ignore" in c for c in s.fix.config_commands)


def test_state_anchor_is_idempotent_when_llm_already_supplied_it():
    """If the LLM's very first probe already happens to reveal the state
    (or it's already in session memory), the deterministic anchor must not
    fetch get_neighbors a second time."""
    calls = {"n": 0}

    def ai(prompt: str) -> str:
        if "Restate this network troubleshooting" in prompt:
            return "Resolve the OSPF neighbor stuck in ExStart."
        if "candidate ROOT CAUSES" in prompt:
            return json.dumps([])
        if "normalized diagnostic OPERATION" in prompt:
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps([{"device": "all", "operation": "get_neighbors",
                                    "params": {"protocol": "ospf"}, "purpose": "state",
                                    "tests_hypotheses": [], "value": 0.9}])
            return json.dumps([])
        if "Interpret this device output" in prompt:
            return json.dumps({"facts": [], "impacts": []})
        return ""

    devices = [Dev("192.168.96.136")]
    gw = VendorGateway(send=_ospf_command_router, hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=ai, devices=devices, gateway=gw, config=TSConfig(max_steps=3))
    report = eng.run("why is the OSPF neighbor stuck in ExStart")
    s = report.session
    neighbor_fetches = [e for e in s.executed if "op:get_neighbors" in e.command]
    assert len(neighbor_fetches) == 1, \
        f"get_neighbors must be fetched exactly once, not re-fetched by the anchor: {neighbor_fetches}"


# ── LACP: no get_neighbors mapping at all -> must fall back cleanly ─────
_LACP_ETHERCHANNEL_OUTPUT = (
    "Group  Port-channel  Protocol    Ports\n"
    "1      Po1(SU)         LACP      Gi0/1(I)    Gi0/2(P)\n"
)


def _lacp_command_router(dev, cmds):
    return {c: (_LACP_ETHERCHANNEL_OUTPUT if "etherchannel" in c.lower() else "") for c in cmds}


def _make_ai_that_proposes_nothing():
    def ai(prompt: str) -> str:
        if "Restate this network troubleshooting" in prompt:
            return "Resolve the LACP port stuck in Individual state."
        if "candidate ROOT CAUSES" in prompt:
            return json.dumps([])
        if "normalized diagnostic OPERATION" in prompt:
            return json.dumps([])
        if "Interpret this device output" in prompt:
            return json.dumps({"facts": [], "impacts": []})
        return ""
    return ai


def test_lacp_falls_back_to_interface_details_when_get_neighbors_yields_nothing():
    """LACP's CISCO_ADAPTER_SPECS entry has no "get_neighbors" command
    mapping at all (its neighbor concept IS the interface) -- the anchor
    must try GET_NEIGHBORS, notice it produced no state, and fall back to
    GET_INTERFACE_DETAILS rather than silently giving up."""
    devices = [Dev("10.0.0.1")]
    gw = VendorGateway(send=_lacp_command_router, hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai_that_proposes_nothing(),
                               devices=devices, gateway=gw, config=TSConfig(max_steps=3))
    report = eng.run("why is the LACP port stuck in Individual state")
    s = report.session
    assert any("op:get_neighbors" in e.command for e in s.executed), "must try get_neighbors first"
    assert any("op:get_interface_details" in e.command for e in s.executed), \
        "must fall back to get_interface_details when get_neighbors yields nothing"
    assert any(o.attribute == "state" and o.subject.startswith("neighbor.") for o in s.observations), \
        "the fallback must actually bind a real neighbor state"


# ── reactive-only protocols (ACL/NAT/VLAN) have no state_model: no-op ───
def test_reactive_only_protocol_is_a_clean_noop():
    """ACL has no state_model (spec.state_model is None) -- the anchor
    must recognize this isn't an FSM protocol and do nothing, not error."""
    def ai(prompt: str) -> str:
        if "Restate this network troubleshooting" in prompt:
            return "Why is ACL denying traffic on GigabitEthernet0/1."
        if "candidate ROOT CAUSES" in prompt:
            return json.dumps([])
        if "normalized diagnostic OPERATION" in prompt:
            return json.dumps([])
        if "Interpret this device output" in prompt:
            return json.dumps({"facts": [], "impacts": []})
        return ""

    devices = [Dev("10.0.0.1")]
    gw = VendorGateway(send=lambda d, cmds: {c: "" for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=ai, devices=devices, gateway=gw, config=TSConfig(max_steps=2))
    report = eng.run("why is ACL denying traffic on GigabitEthernet0/1")
    assert not any("neighbor/protocol-state anchor" in e.purpose for e in report.session.executed)
