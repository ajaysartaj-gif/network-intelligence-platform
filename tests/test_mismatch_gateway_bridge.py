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
