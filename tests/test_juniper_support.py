"""
Tests for real Juniper (Junos) vendor support — the second vendor this
platform genuinely supports, proving protocol_registry.py's ProtocolSpec/
AdapterSpec split (vendor-neutral knowledge vs vendor-specific syntax) is
real, not cosmetic. JunosLikeAdapter now has the same production depth as
IosLikeAdapter for OSPF/BGP/LACP/VRRP/STP: real parsing regexes and
remediation commands grounded in verified Junos documentation (see
protocol_registry.py's JUNOS_ADAPTER_SPECS docstring for sources).

Deliberately does NOT cover HSRP (Cisco-proprietary, no Juniper
equivalent) or ACL/NAT/VLAN-native-mismatch (real architectural
differences documented in protocol_registry.py, not built for Junos).
"""
import json
import re
import sys
import types
from pathlib import Path

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.knowledge.compiler.protocol_registry import JUNOS_ADAPTER_SPECS, PROTOCOL_SPECS
from core.vendor import VendorGateway, Op, Operation, VendorProfile
from core.vendor.adapters.juniper_junos_like import JunosLikeAdapter
from core.vendor.operations import RemediationIntent
from core.troubleshooting import TroubleshootingEngine, TSConfig, ResolutionStatus


class Dev:
    def __init__(self, ip, hostname="R1"):
        self.ip, self.hostname, self.device_type = ip, hostname, "juniper junos"


def _profile(ip="10.0.0.5"):
    return VendorProfile(vendor="junos-like", os="junos-like", version="", confidence=0.9,
                         capabilities=[], attributes={"ip": ip})


# ── scoping: Junos deliberately does NOT claim protocols it can't support ──
def test_junos_has_no_hsrp_or_reactive_protocol_support():
    """HSRP is Cisco-proprietary; ACL/NAT/VLAN-native-mismatch have real,
    verified architectural differences on Junos (see protocol_registry.py's
    JUNOS_ADAPTER_SPECS docstring) -- none are fabricated for this vendor."""
    assert "hsrp" not in JUNOS_ADAPTER_SPECS
    assert "acl" not in JUNOS_ADAPTER_SPECS
    assert "nat" not in JUNOS_ADAPTER_SPECS
    assert "vlan" not in JUNOS_ADAPTER_SPECS
    assert set(JUNOS_ADAPTER_SPECS.keys()) == {"ospf", "bgp", "lacp", "vrrp", "stp"}


def test_junos_shares_the_same_vendor_neutral_protocol_knowledge_as_cisco():
    """The whole point of the ProtocolSpec/AdapterSpec split: Junos and
    Cisco read the SAME state model/signatures/policy for a shared
    protocol -- only parsing/commands differ."""
    for proto in ("ospf", "bgp", "lacp", "vrrp", "stp"):
        assert proto in PROTOCOL_SPECS
        assert PROTOCOL_SPECS[proto].state_model is not None


# ── adapter parsing (real, verified Junos output formats) ────────────────
def test_adapter_parses_ospf_neighbor_full_and_exstart():
    adapter = JunosLikeAdapter()
    text = ("Address          Interface              State     ID               Pri  Dead\n"
           "10.5.1.2         ge-1/2/0.1             Full      10.5.1.2         128  33\n"
           "10.5.10.2        ge-1/2/0.10            ExStart   10.5.1.38        128  38\n")
    objs = adapter.parse_output(Operation(Op.GET_NEIGHBORS, {"protocol": "ospf"}),
                                {"show ospf neighbor": text}, _profile())
    nbrs = {o.id: o.attributes["state"] for o in objs if o.type == "neighbor"}
    assert nbrs == {"10.5.1.2": "FULL", "10.5.10.2": "EXSTART"}


def test_adapter_header_row_never_misparsed_as_ospf_neighbor():
    adapter = JunosLikeAdapter()
    text = ("Address          Interface              State     ID               Pri  Dead\n"
           "10.5.1.2         ge-1/2/0.1             Full      10.5.1.2         128  33\n")
    objs = adapter.parse_output(Operation(Op.GET_NEIGHBORS, {"protocol": "ospf"}),
                                {"show ospf neighbor": text}, _profile())
    ids = {o.id for o in objs if o.type == "neighbor"}
    assert ids == {"10.5.1.2"}


def test_adapter_parses_bgp_summary_establ_and_active():
    """Junos always prints a literal state word (including 'Establ' when
    established) -- no digit-vs-name disambiguation needed, a genuine,
    verified difference from Cisco's own PfxRcd-column ambiguity."""
    adapter = JunosLikeAdapter()
    text = ("Peer                     AS      InPkt     OutPkt    OutQ   Flaps Last Up/Dwn State\n"
           "10.255.245.35            65299   72        74        0      1     19:00        Establ\n"
           "10.255.245.36            65300   10        10        0      0     never        Active\n")
    objs = adapter.parse_output(Operation(Op.GET_NEIGHBORS, {"protocol": "bgp"}),
                                {"show bgp summary": text}, _profile())
    nbrs = {o.id: o.attributes["state"] for o in objs if o.type == "neighbor"}
    assert nbrs == {"10.255.245.35": "ESTABL", "10.255.245.36": "ACTIVE"}


def test_adapter_parses_lacp_bundled_and_down_distinguishing_actor_partner_table():
    """The 'Aggregated interface:' header supplies the ae* context; the
    Mux-State row is anchored on the Receive-State vocabulary so it can't
    be confused with the SAME command's Actor/Partner table (different
    column words entirely)."""
    adapter = JunosLikeAdapter()
    text = ("Aggregated interface: ae0\n"
           "LACP State:       Role   Exp   Def  Dist  Col  Syn  Aggr  Timeout  Activity\n"
           "xe-1/0/2          Actor    No    No   Yes  Yes  Yes   Yes     Fast   Active\n"
           "xe-1/0/2          Partner  No    No   Yes  Yes  Yes   Yes     Fast   Active\n"
           "LACP Protocol:    Receive State  Transmit State  Mux State\n"
           "xe-1/0/2          Current        Fast periodic   Collecting distributing\n")
    objs = adapter.parse_output(Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "lacp"}),
                                {"show lacp interfaces": text}, _profile())
    members = {o.id: o.attributes for o in objs if o.type == "neighbor"}
    assert members["xe-1/0/2"]["state"] == "BUNDLED"
    assert members["xe-1/0/2"]["aggregate"] == "ae0"
    # The Actor/Partner rows (same interface name, different table) must
    # never be misread as a second, conflicting state for xe-1/0/2.
    assert len(members) == 1


def test_adapter_parses_vrrp_master_and_backup():
    adapter = JunosLikeAdapter()
    text = ("Interface     State Group VR state VR Mode Timer Type Address\n"
           "ge-0/0/2.0    up    50    master   Active  A 0.093  lcl 172.16.50.2 vip 172.16.50.1\n"
           "ge-0/0/3.0    up    51    backup   Active  D 0.872  lcl 172.16.50.3 vip 172.16.50.1 mas 172.16.50.2\n")
    objs = adapter.parse_output(Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "vrrp"}),
                                {"show vrrp": text}, _profile())
    members = {o.id: o.attributes["state"] for o in objs if o.type == "neighbor"}
    assert members == {"ge-0/0/2.0:50": "MASTER", "ge-0/0/3.0:51": "BACKUP"}


def test_adapter_parses_stp_forwarding_and_blocking_state_before_role():
    """Junos's column order is State-then-Role -- the REVERSE of Cisco's
    Role-then-Sts -- confirmed against a complete real example."""
    adapter = JunosLikeAdapter()
    text = ("Interface Port ID Designated Designated Port State Role\n"
           "                port ID    bridge ID  Cost\n"
           "ge-0/0/0.0  128:513 128:513  8192.0019e2500340 1000 FWD DESG\n"
           "ge-0/0/2.0  128:515 128:515  8192.0019e2500340 1000 BLK DIS\n")
    objs = adapter.parse_output(Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "stp"}),
                                {"show spanning-tree interface": text}, _profile())
    members = {o.id: o.attributes["state"] for o in objs if o.type == "neighbor"}
    assert members == {"ge-0/0/0.0": "FORWARDING", "ge-0/0/2.0": "BLOCKING"}


# ── remediation recipes (real, verified Junos config syntax) ─────────────
def test_adapter_ospf_p2p_recipe_uses_real_junos_syntax():
    adapter = JunosLikeAdapter()
    intent = RemediationIntent(name="set_protocol_network_point_to_point",
                               params={"protocol": "ospf", "interface": "ge-0/0/1.0"})
    assert adapter.build_fix(intent, _profile()) == [
        "set protocols ospf area 0.0.0.0 interface ge-0/0/1.0 interface-type p2p"]
    assert adapter.build_rollback(intent, _profile()) == [
        "delete protocols ospf area 0.0.0.0 interface ge-0/0/1.0 interface-type p2p"]


def test_adapter_bgp_recipes_use_activate_deactivate_and_multihop():
    adapter = JunosLikeAdapter()
    shutdown_intent = RemediationIntent(name="remove_bgp_neighbor_shutdown",
                                        params={"protocol": "bgp", "neighbor_ip": "10.0.0.3", "group": "PEERS"})
    assert adapter.build_fix(shutdown_intent, _profile()) == [
        "activate protocols bgp group PEERS neighbor 10.0.0.3"]
    assert adapter.build_rollback(shutdown_intent, _profile()) == [
        "deactivate protocols bgp group PEERS neighbor 10.0.0.3"]

    multihop_intent = RemediationIntent(name="add_bgp_ebgp_multihop",
                                        params={"protocol": "bgp", "group": "PEERS", "hops": "3"})
    assert adapter.build_fix(multihop_intent, _profile()) == [
        "set protocols bgp group PEERS multihop ttl 3"]


def test_adapter_lacp_recipe_applies_to_aggregate_not_member():
    """A genuine, verified difference from Cisco: the fix targets the ae*
    aggregate interface, not the physical member port."""
    adapter = JunosLikeAdapter()
    intent = RemediationIntent(name="set_lacp_mode_active", params={"protocol": "lacp", "aggregate": "ae0"})
    assert adapter.build_fix(intent, _profile()) == [
        "set interfaces ae0 aggregated-ether-options lacp active"]


def test_junos_has_no_vrrp_or_stp_remediation_recipes_by_design():
    """VRRP: the real preempt command needs interface/unit/family/address
    hierarchy this signature can't supply. STP: matches Cisco's own STP,
    which also has no matching vendor-adapter intent."""
    assert JUNOS_ADAPTER_SPECS["vrrp"].recipes == []
    assert JUNOS_ADAPTER_SPECS["stp"].recipes == []


# ── end-to-end: real convergence through the live TroubleshootingEngine ──
def _make_ai(proto, restate, op_name):
    calls = {"n": 0}

    def ai(prompt: str) -> str:
        if "Restate this network troubleshooting" in prompt:
            return restate
        if "candidate ROOT CAUSES" in prompt:
            return json.dumps([])
        if "normalized diagnostic OPERATION" in prompt:
            calls["n"] += 1
            # Nothing on call 1 (engine.py's _observe_initial_state probes
            # BEFORE hypotheses are seeded — active_hypotheses() is empty
            # there, so any impact returned then has no hypothesis_id to
            # bind to). The real operation runs on call 2, inside the main
            # loop, once hypotheses exist — that's the analyze() call the
            # "Interpret this device output" branch below needs.
            if calls["n"] == 2:
                return json.dumps([{"device": "all", "operation": op_name,
                                    "params": {"protocol": proto}, "purpose": "diag",
                                    "tests_hypotheses": [], "value": 0.9}])
            return json.dumps([])
        if "Interpret this device output" in prompt:
            # A genuine (non-tautological) reading of the collected output —
            # the engine's own deterministic state-match tautology alone is
            # no longer sufficient to reach RESOLVED_PENDING_APPROVAL (see
            # Hypothesis.has_grounded_evidence / RootCauseRanker.converged()).
            # A "fact" must accompany the impact — engine.py's _ingest_output
            # only processes "impacts" while iterating "facts" (each impact
            # is anchored to that round's Observation), so an empty facts
            # list silently drops any impacts alongside it. Only BGP's
            # Active-state test needs this to converge; LACP's Detached-state
            # test asserts s.fix is None regardless.
            impacts = []
            m = re.search(r"\[(hyp_[0-9a-f]+)\][^\n]*TCP connection failures", prompt)
            if m:
                impacts.append({"hypothesis_id": m.group(1), "effect": "support",
                                "weight": 0.6,
                                "reason": "show bgp summary shows repeated Active with 0 in/out packets"})
            facts = [{"subject": f"{proto}.neighbor", "attribute": "state", "value": "ACTIVE"}]
            return json.dumps({"facts": facts, "impacts": impacts})
        return ""
    return ai


def test_junos_bgp_active_converges_to_real_vendor_fix_end_to_end():
    devices = [Dev("10.0.0.1")]
    active_text = ("Peer                     AS      InPkt     OutPkt    OutQ   Flaps Last Up/Dwn State\n"
                  "10.0.0.2                 65002   0         0         0      0     never        Active\n")
    gw = VendorGateway(send=lambda d, cmds: {c: active_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "juniper junos"})
    eng = TroubleshootingEngine(ai_call=_make_ai("bgp", "Resolve the BGP neighbor stuck in Active state.",
                                                 "get_neighbors"),
                                devices=devices, gateway=gw, config=TSConfig(max_steps=6))
    report = eng.run("why is the BGP neighbor stuck in Active state")
    s = report.session

    assert s.status == ResolutionStatus.RESOLVED_PENDING_APPROVAL, s.status
    top = s.top()
    assert top.confidence >= 0.8
    assert s.fix is not None
    assert s.fix.config_commands == ["set protocols bgp group external multihop ttl 2"]


def test_junos_lacp_individual_equivalent_stays_honest_uncertainty():
    """LACP's Down mux-state has no mapped remediation on either vendor
    (physical-layer issue outside LACP's own control) -- proves the SAME
    honest partial-coverage policy applies regardless of vendor."""
    devices = [Dev("10.0.0.1")]
    down_text = ("Aggregated interface: ae0\n"
                "LACP Protocol:    Receive State  Transmit State  Mux State\n"
                "xe-1/0/2          Current        Fast periodic   Detached\n")
    gw = VendorGateway(send=lambda d, cmds: {c: down_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "juniper junos"})
    eng = TroubleshootingEngine(ai_call=_make_ai("lacp", "Resolve the LACP member stuck Detached.",
                                                 "get_interface_details"),
                                devices=devices, gateway=gw, config=TSConfig(max_steps=6))
    report = eng.run("why is the LACP member stuck Detached")
    s = report.session
    assert s.fix is None
