"""
The one end-to-end test that was missing for this platform's flagship
scenario: OSPF neighbor stuck in ExStart due to an MTU mismatch, driven
through the REAL production stack (TroubleshootingEngine.run() -> real
VendorGateway -> real IosLikeAdapter regex parsing -> Mismatch Investigation
+ compiled FailureSignature seeding running together, exactly as
copilot_engine.py invokes it).

Every other protocol in this repo (BGP/LACP/HSRP/VRRP/STP) has a
"converges_to_real_vendor_fix_end_to_end" test. OSPF/ExStart/MTU — the exact
scenario a real user reported "no fix generated" against — never had one,
despite being the platform's original, most-discussed scenario. This closes
that gap and proves (rather than assumes) that the hypothesis-merge fix and
the state-contradiction elimination fix actually combine to reach a real,
proposed fix end to end.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.topology.knowledge_graph_bridge as kgb
from core.troubleshooting import ResolutionStatus, TroubleshootingEngine, TSConfig
from core.vendor import VendorGateway


class FakeDevice:
    def __init__(self, ip, hostname, device_type="cisco_ios"):
        self.ip = ip
        self.hostname = hostname
        self.device_type = device_type


def _no_real_topology(monkeypatch):
    monkeypatch.setattr(kgb, "build_knowledge_graph", lambda devices, **kw: kgb.KnowledgeGraph())


def _ospf_interface_text(area, router_id, hello="10", dead="40", prefix_ip="10.0.12.1"):
    return (
        f"GigabitEthernet0/0 is up, line protocol is up\n"
        f"  Internet Address {prefix_ip}/24, Area {area}\n"
        f"  Process ID 1, Router ID {router_id}, Network Type BROADCAST, Cost: 1\n"
        f"  Timer intervals configured, Hello {hello}, Dead {dead}, Wait {dead}, Retransmit 5\n"
        f"  Neighbor Count is 1, Adjacent neighbor count is 1\n"
    )


def _ospf_neighbor_text(neighbor_router_id, state, neighbor_addr):
    return (
        "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
        f"{neighbor_router_id}       0   {state}/  -        00:00:33    {neighbor_addr}       GigabitEthernet0/0\n"
    )


def _show_interface_text(mtu):
    return (
        "GigabitEthernet0/0 is up, line protocol is up\n"
        "  Hardware is BCM1250 Internal MAC, address is 0011.2233.4455\n"
        f"  MTU {mtu} bytes, BW 1000000 Kbit/sec, DLY 10 usec,\n"
        "     reliability 255/255, txload 1/255, rxload 1/255\n"
    )


def _build_gateway_with_mtu_mismatch():
    """R1's neighbor table reports R2 stuck in EXSTART; R1 and R2's hardware
    MTU genuinely differ (1500 vs 1200) — the real ExStart/MTU-mismatch
    scenario, no explicit `ip mtu` override needed (gateway_adapter.py falls
    back to hardware MTU when no override is configured, same as real IOS)."""
    r1 = FakeDevice("192.168.96.136", "R1")
    r2 = FakeDevice("192.168.20.2", "R2")

    responses = {
        ("192.168.96.136", "show ip ospf interface"): _ospf_interface_text("0", "1.1.1.1", prefix_ip="192.168.96.136"),
        ("192.168.96.136", "show ip ospf neighbor"): _ospf_neighbor_text("2.2.2.2", "EXSTART", "192.168.20.2"),
        ("192.168.96.136", "show interface"): _show_interface_text(1500),
        ("192.168.96.136", "show running-config | section ^interface"): "",
        ("192.168.20.2", "show ip ospf interface"): _ospf_interface_text("0", "2.2.2.2", prefix_ip="192.168.20.2"),
        ("192.168.20.2", "show ip ospf neighbor"): _ospf_neighbor_text("1.1.1.1", "EXSTART", "192.168.96.136"),
        ("192.168.20.2", "show interface"): _show_interface_text(1200),
        ("192.168.20.2", "show running-config | section ^interface"): "",
    }

    def send(device, cmds):
        return {c: responses.get((device.ip, c), "") for c in cmds}

    def hint_provider(device):
        return {"device_type": device.device_type, "hostname": device.hostname}

    gw = VendorGateway(send=send, hint_provider=hint_provider)
    ip_to_dev = {r1.ip: r1, r2.ip: r2}
    return gw, ip_to_dev


def test_ospf_exstart_mtu_mismatch_converges_to_a_real_proposed_fix(monkeypatch):
    _no_real_topology(monkeypatch)
    gw, ip_to_dev = _build_gateway_with_mtu_mismatch()
    devices = list(ip_to_dev.values())

    def ai(_prompt):
        return ""   # deterministic paths (mismatch investigation + compiled signatures) carry this

    eng = TroubleshootingEngine(ai_call=ai, devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why is the OSPF neighbor stuck in EXSTART")
    s = report.session

    # The two MTU hypotheses (mismatch-investigation + compiled ExStart
    # signature) must have MERGED into one, not split confidence across two.
    mtu_hyps = [h for h in s.hypotheses if "mtu" in " ".join(h.discriminating_signals).lower()]
    assert len(mtu_hyps) == 1, [h.statement for h in mtu_hyps]

    # Every OTHER compiled-signature state hypothesis must have been
    # eliminated outright by the real observed state (EXSTART), not merely
    # demoted and left cluttering the report.
    other_state_hyps = [
        h for h in s.hypotheses
        if any(st in h.discriminating_signals for st in
              ("Down", "Attempt", "Init", "2-Way", "Exchange", "Loading"))
    ]
    assert all(h.state.value == "eliminated" for h in other_state_hyps), \
        [(h.statement, h.state.value) for h in other_state_hyps]

    # The actual complaint this closes: convergence + a real proposed fix,
    # not "no fix generated" despite a clear, well-grounded diagnosis.
    assert s.status == ResolutionStatus.RESOLVED_PENDING_APPROVAL, s.status
    top = s.top()
    assert top is not None and top.confidence >= 0.80, (top.statement if top else None, top.confidence if top else None)
    assert s.fix is not None, "no fix generated despite a converged, grounded MTU diagnosis"
    assert s.fix.config_commands

    # The reasoning-chain feedback this session also closes: the report
    # explains WHY ExStart implicates MTU, not just the bare conclusion.
    assert s.reasoning_chain is not None
    assert s.reasoning_chain["stuck_state"] == "ExStart"
    md = report.to_markdown()
    assert "Reasoning Chain" in md
