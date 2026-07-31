"""
Live-gateway-backed Mismatch Investigation tests.

Unlike tests/test_mismatch_ospf.py (which drives strategies.mismatch through
adapters.generic.GenericAdapter + adapters.transport.MockTransport), these
tests exercise the REAL production stack end to end:

    core.troubleshooting.strategies.gateway_adapter.GatewayDeviceAdapter
      -> core.vendor.VendorGateway
        -> core.vendor.adapters.cisco_ios_like.IosLikeAdapter (real regex parsing)

Only the SSH transport itself is stubbed (a plain dict lookup keyed by
command) — exactly the same boundary tests/test_vendor_framework.py already
mocks at. Nothing about knowledge/schema.py, strategies/mismatch.py,
strategies/relation_eval.py, or knowledge/normalize.py is mocked: this is the
real deterministic comparison running on real (adapter-parsed) values.

Corpus retrieval uses the offline lexical/stub path deliberately (no network,
no chromadb) so this suite runs the same everywhere test_mismatch_ospf.py does.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.topology.knowledge_graph_bridge as kgb
from core.vendor import VendorGateway
from core.troubleshooting.strategies.mismatch_bridge import (
    detect_relationship_type, run_mismatch_investigation,
)
from core.troubleshooting.evidence_graph import EvidenceGraph
from core.troubleshooting.hypotheses import HypothesisManager
from core.troubleshooting.models import Session


def _no_real_topology(monkeypatch):
    """Every test in this file exercises the Mismatch Investigation in
    isolation from real CDP/LLDP discovery (that's covered separately in
    tests/test_knowledge_graph_bridge.py) — this keeps these tests fast and
    deterministic instead of depending on how a real netmiko connection
    attempt to a non-existent lab IP happens to fail in any given
    environment (fast refusal here, but a slow timeout elsewhere)."""
    monkeypatch.setattr(kgb, "build_knowledge_graph", lambda devices, **kw: kgb.KnowledgeGraph())


class FakeDevice:
    def __init__(self, ip, hostname, device_type="cisco_ios"):
        self.ip = ip
        self.hostname = hostname
        self.device_type = device_type


# ── fixture: two Cisco IOS routers, real "show" output text ─────────────────
def _ospf_interface_text(area, router_id, ntype, hello, dead, prefix_ip, prefix_len=24):
    return (
        f"GigabitEthernet0/0 is up, line protocol is up\n"
        f"  Internet Address {prefix_ip}/{prefix_len}, Area {area}\n"
        f"  Process ID 1, Router ID {router_id}, Network Type {ntype}, Cost: 1\n"
        f"  Timer intervals configured, Hello {hello}, Dead {dead}, Wait {dead}, Retransmit 5\n"
        f"  Neighbor Count is 1, Adjacent neighbor count is 1\n"
    )


def _ospf_neighbor_text(neighbor_router_id, state, neighbor_addr, iface="GigabitEthernet0/0"):
    return (
        "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
        f"{neighbor_router_id}       0   {state}/  -        00:00:33    {neighbor_addr}       {iface}\n"
    )


def _build_gateway(r1_hello="10", r2_hello="10", r2_state="FULL"):
    r1 = FakeDevice("10.0.12.1", "R1")
    r2 = FakeDevice("10.0.12.2", "R2")

    r1_ospf_iface = _ospf_interface_text("0", "1.1.1.1", "BROADCAST", r1_hello, "40", "10.0.12.1")
    r2_ospf_iface = _ospf_interface_text("0", "2.2.2.2", "BROADCAST", r2_hello, "40", "10.0.12.2")
    r1_ospf_nbr = _ospf_neighbor_text("2.2.2.2", r2_state, "10.0.12.2")
    r2_ospf_nbr = _ospf_neighbor_text("1.1.1.1", r2_state, "10.0.12.1")

    responses = {
        ("10.0.12.1", "show ip ospf interface"): r1_ospf_iface,
        ("10.0.12.1", "show ip ospf neighbor"): r1_ospf_nbr,
        ("10.0.12.2", "show ip ospf interface"): r2_ospf_iface,
        ("10.0.12.2", "show ip ospf neighbor"): r2_ospf_nbr,
    }

    def send(device, cmds):
        return {c: responses.get((device.ip, c), f"% unrecognized: {c}") for c in cmds}

    def hint_provider(device):
        return {"device_type": device.device_type, "hostname": device.hostname}

    gw = VendorGateway(send=send, hint_provider=hint_provider)
    ip_to_dev = {r1.ip: r1, r2.ip: r2}
    return gw, ip_to_dev


# ── detect_relationship_type ─────────────────────────────────────────────────
def test_detect_relationship_type():
    assert detect_relationship_type("why is OSPF stuck in EXSTART") == "ospf_adjacency"
    assert detect_relationship_type("HSRP keeps flapping between routers") == "hsrp_pairing"
    assert detect_relationship_type("why is the switchport down") is None


# ── healthy case: no findings, nothing seeded ────────────────────────────────
def test_healthy_link_seeds_nothing(monkeypatch):
    _no_real_topology(monkeypatch)
    gw, ip_to_dev = _build_gateway(r1_hello="10", r2_hello="10")
    session = Session()
    hmgr = HypothesisManager(session)
    graph = EvidenceGraph()

    seeded = run_mismatch_investigation(
        relationship_type="ospf_adjacency", devices=list(ip_to_dev.values()),
        ip_to_device=ip_to_dev, gateway=gw, ai_call=None,
        session=session, hmgr=hmgr, graph=graph,
    )
    assert seeded is False
    assert session.hypotheses == []


# ── real mismatch: hello-interval disagreement through the REAL adapter ─────
def test_hello_mismatch_seeds_evidence_backed_hypothesis(monkeypatch):
    _no_real_topology(monkeypatch)
    gw, ip_to_dev = _build_gateway(r1_hello="10", r2_hello="30", r2_state="INIT")
    session = Session()
    hmgr = HypothesisManager(session)
    graph = EvidenceGraph()

    seeded = run_mismatch_investigation(
        relationship_type="ospf_adjacency", devices=list(ip_to_dev.values()),
        ip_to_device=ip_to_dev, gateway=gw, ai_call=None,
        session=session, hmgr=hmgr, graph=graph,
    )
    assert seeded is True
    assert len(session.hypotheses) >= 1

    top = session.top()
    assert top is not None
    assert "ospf_hello_interval" in top.statement
    assert top.confidence > 0.5, top.confidence

    # Evidence is traceable: both endpoint values were recorded as Observations,
    # attributed to the REAL device IPs (not the OSPF router-ids).
    devices_seen = {o.device for o in session.observations}
    assert devices_seen == {"10.0.12.1", "10.0.12.2"}
    assert any(o.value == "10" for o in session.observations)
    assert any(o.value == "30" for o in session.observations)

    # Evidence objects link back to the seeded hypothesis.
    assert any(e.hypothesis_id == top.id for e in session.evidence)


# ── router-id resolution: neighbor is identified by router-id, not mgmt IP ──
def test_neighbor_router_id_resolves_to_management_ip():
    """R1's 'show ip ospf neighbor' reports R2 by router-id 2.2.2.2, not by
    R2's management IP 10.0.12.2. The bridge must still recognize R2 as an
    approved device via the router_id -> device_ip map, not skip it."""
    from core.troubleshooting.strategies.gateway_adapter import GatewayDeviceAdapter

    gw, ip_to_dev = _build_gateway(r1_hello="10", r2_hello="10")
    adapter = GatewayDeviceAdapter(gw, ip_to_dev, "ospf_adjacency")
    instances = adapter.enumerate_relationship("ospf_adjacency", "")
    assert len(instances) == 1
    inst = instances[0]
    assert {inst.local.device, inst.remote.device} == {"10.0.12.1", "10.0.12.2"}
    assert inst.local.context == "GigabitEthernet0/0"
    assert inst.remote.context == "GigabitEthernet0/0"


# ── end-to-end: the REAL production entry point, TroubleshootingEngine.run() ─
def test_full_engine_run_wires_mismatch_investigation(monkeypatch):
    """Proves the wiring at the top level actually used in production
    (core/copilot_engine.py calls exactly this): TroubleshootingEngine.run()
    reaches an evidence-backed hypothesis from the Mismatch Investigation
    alone, with no LLM interpretation needed to explain the symptom."""
    _no_real_topology(monkeypatch)
    from core.troubleshooting import TroubleshootingEngine, TSConfig

    gw, ip_to_dev = _build_gateway(r1_hello="10", r2_hello="30", r2_state="INIT")
    devices = list(ip_to_dev.values())

    def ai(_prompt):
        return ""  # LLM path contributes nothing; the KP comparison is what matters here

    eng = TroubleshootingEngine(ai_call=ai, devices=devices, gateway=gw,
                               config=TSConfig(max_steps=2))
    report = eng.run("why is OSPF stuck")
    s = report.session

    assert any("ospf_hello_interval" in h.statement for h in s.hypotheses), \
        [h.statement for h in s.hypotheses]
    top = s.top()
    assert top is not None and top.confidence > 0.5, (top.statement if top else None)
    # Evidence trail survives all the way to the markdown report.
    md = report.to_markdown()
    assert "ospf_hello_interval" in md


# ── multi-homed device: interface pairing must not silently give up ─────────
# Regression for a real production report: R1 had THREE OSPF-enabled
# interfaces (a real multi-neighbor router). The user manually introduced an
# OSPF area-ID mismatch between R1 and R2 specifically, but the Mismatch
# Investigation produced ZERO findings for it. Root cause: without real
# CDP/LLDP topology discovery, _infer_local_interface/_infer_remote_interface
# only resolved a device's interface when it had EXACTLY ONE protocol-enabled
# interface -- any device with more than one neighbor (R1 here) always fell
# through to "ambiguous, skip", regardless of how unambiguous the ACTUAL
# neighbor relationship being investigated was. Fix: use the specific
# neighbor's OWN interface (already captured by _OSPF_NEIGHBOR_PARSER's
# trailing Interface column) instead of guessing from the device as a whole.

def _multi_homed_r1_gateway(r1_area="0", r2_area="0"):
    r1 = FakeDevice("10.0.12.1", "R1")
    r2 = FakeDevice("10.0.12.2", "R2")

    # R1: three real OSPF interfaces -- only Gi1/0 faces the approved
    # device R2; the other two face routers this test never approves.
    r1_ospf_iface = "\n".join([
        _ospf_interface_text(r1_area, "1.1.1.1", "BROADCAST", "10", "40", "10.0.12.1")
            .replace("GigabitEthernet0/0", "GigabitEthernet1/0"),
        _ospf_interface_text("0", "1.1.1.1", "BROADCAST", "10", "40", "10.0.13.1")
            .replace("GigabitEthernet0/0", "FastEthernet0/0"),
        _ospf_interface_text("0", "1.1.1.1", "BROADCAST", "10", "40", "10.0.14.1")
            .replace("GigabitEthernet0/0", "GigabitEthernet2/0"),
    ])
    r1_ospf_nbr = "\n".join([
        "Neighbor ID     Pri   State           Dead Time   Address         Interface",
        "2.2.2.2       0   FULL/  -        00:00:33    10.0.12.2       GigabitEthernet1/0",
        "9.9.9.9       0   FULL/  -        00:00:33    10.0.13.9       FastEthernet0/0",
        "8.8.8.8       0   FULL/  -        00:00:33    10.0.14.9       GigabitEthernet2/0",
    ])

    r2_ospf_iface = _ospf_interface_text(r2_area, "2.2.2.2", "BROADCAST", "10", "40", "10.0.12.2") \
        .replace("GigabitEthernet0/0", "GigabitEthernet1/0")
    r2_ospf_nbr = ("Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
                  "1.1.1.1       0   FULL/  -        00:00:33    10.0.12.1       GigabitEthernet1/0\n")

    responses = {
        ("10.0.12.1", "show ip ospf interface"): r1_ospf_iface,
        ("10.0.12.1", "show ip ospf neighbor"): r1_ospf_nbr,
        ("10.0.12.2", "show ip ospf interface"): r2_ospf_iface,
        ("10.0.12.2", "show ip ospf neighbor"): r2_ospf_nbr,
    }

    def send(device, cmds):
        return {c: responses.get((device.ip, c), f"% unrecognized: {c}") for c in cmds}

    def hint_provider(device):
        return {"device_type": device.device_type, "hostname": device.hostname}

    gw = VendorGateway(send=send, hint_provider=hint_provider)
    ip_to_dev = {r1.ip: r1, r2.ip: r2}
    return gw, ip_to_dev


def test_multi_homed_device_resolves_the_specific_neighbors_own_interface():
    """Unit-level proof: R1 has 3 OSPF interfaces. enumerate_relationship
    must still resolve the R1<->R2 pair to R1's Gi1/0 specifically (the
    interface the neighbor table says R2 is actually on) instead of giving
    up because R1 as a whole has more than one OSPF interface."""
    from core.troubleshooting.strategies.gateway_adapter import GatewayDeviceAdapter

    gw, ip_to_dev = _multi_homed_r1_gateway()
    adapter = GatewayDeviceAdapter(gw, ip_to_dev, "ospf_adjacency")
    instances = adapter.enumerate_relationship("ospf_adjacency", "")

    assert len(instances) == 1, instances
    inst = instances[0]
    assert {inst.local.device, inst.remote.device} == {"10.0.12.1", "10.0.12.2"}
    local = inst.local if inst.local.device == "10.0.12.1" else inst.remote
    assert local.context == "GigabitEthernet1/0", local.context


def test_multi_homed_device_area_mismatch_is_seeded_not_silently_skipped(monkeypatch):
    """Real end-to-end reproduction of the reported bug: R1 (3 OSPF
    interfaces) and R2 have genuinely different Area IDs on the link
    between them. Before the fix, run_mismatch_investigation returned
    seeded=False here -- not because the comparison logic was wrong, but
    because interface pairing gave up on R1 for having more than one OSPF
    interface, regardless of how unambiguous THIS specific neighbor was."""
    _no_real_topology(monkeypatch)
    gw, ip_to_dev = _multi_homed_r1_gateway(r1_area="0", r2_area="1")
    session = Session()
    hmgr = HypothesisManager(session)
    graph = EvidenceGraph()

    seeded = run_mismatch_investigation(
        relationship_type="ospf_adjacency", devices=list(ip_to_dev.values()),
        ip_to_device=ip_to_dev, gateway=gw, ai_call=None,
        session=session, hmgr=hmgr, graph=graph,
    )
    assert seeded is True
    assert any("ospf_area_id" in h.statement for h in session.hypotheses), \
        [h.statement for h in session.hypotheses]
    top = session.top()
    assert top is not None and top.confidence > 0.5, (top.statement if top else None)


# ── safety: missing gateway / no relationship keyword never raises ──────────
def test_no_gateway_returns_false_not_exception():
    session = Session()
    hmgr = HypothesisManager(session)
    graph = EvidenceGraph()
    seeded = run_mismatch_investigation(
        relationship_type="ospf_adjacency", devices=[], ip_to_device={},
        gateway=None, ai_call=None, session=session, hmgr=hmgr, graph=graph,
    )
    assert seeded is False
