"""
Regression for a real production report: a re-investigation asked about a
neighbor stuck in "Down". The goal/evidence mismatch check correctly found
the neighbor is actually FULL now (real OSPF re-convergence) and said so
in the banner. But run() continued on to ask the LLM for MORE hypotheses
about the already-disproven "Down" symptom anyway, seeded a 20%-confidence,
zero-evidence guess ("OSPF authentication mismatch"), and closed with
"Escalated" -- a confusing, alarming verdict for what the evidence plainly
shows is a healthy, converged adjacency.

run() now short-circuits straight to _finish() once the goal-mismatch
check confirms the named target is already at the protocol's healthy
terminal state, skipping the LLM hypothesis round entirely -- so no
speculative zero-evidence hypothesis ever gets a chance to hijack the
conclusion, and _finish()'s own healthy/escalate guard (built earlier this
session) reaches HEALTHY from an empty, un-polluted hypothesis set.
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


def _ospf_neighbor_text(neighbor_router_id, state, neighbor_addr, iface="GigabitEthernet1/0"):
    return (
        "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
        f"{neighbor_router_id}       1   {state}/DR         00:00:35    {neighbor_addr}       {iface}\n"
    )


def test_asking_about_a_named_neighbor_thats_now_full_concludes_healthy_not_escalated(monkeypatch):
    _no_real_topology(monkeypatch)
    r1 = FakeDevice("192.168.96.136", "R1")
    r2 = FakeDevice("192.168.20.2", "R2")

    # The named target (192.168.20.2) is actually FULL now -- real
    # re-convergence after an earlier reset. No LLM configured (ai
    # returns ""), so the only way a hypothesis appears is if generate_
    # hypotheses() gets called at all -- this test proves it must not be.
    # router-id == address for both rows, matching this lab's real
    # convention (established in tests/test_target_scoped_observation.py) --
    # a mismatched router-id/address pair breaks target_ip-based subject
    # matching, since the observation subject is keyed off the router-id
    # column.
    responses = {
        ("192.168.96.136", "show ip ospf neighbor"): _ospf_neighbor_text(
            "192.168.20.2", "FULL", "192.168.20.2"),
        ("192.168.20.2", "show ip ospf neighbor"): _ospf_neighbor_text(
            "192.168.96.136", "FULL", "192.168.96.136"),
    }

    def send(device, cmds):
        return {c: responses.get((device.ip, c), "") for c in cmds}

    def hint_provider(device):
        return {"device_type": device.device_type, "hostname": device.hostname}

    gw = VendorGateway(send=send, hint_provider=hint_provider)
    devices = [r1, r2]

    def ai(_prompt):
        return ""

    eng = TroubleshootingEngine(ai_call=ai, devices=devices, gateway=gw, config=TSConfig(max_steps=6))
    report = eng.run("why is the OSPF neighbor 192.168.20.2 on interface GigabitEthernet1/0 stuck in Down")
    s = report.session

    assert s.goal_mismatch is not None, "the named target's real state (FULL) must still be flagged as a mismatch vs the asked state (Down)"
    assert s.status == ResolutionStatus.HEALTHY, s.status
    assert s.top() is None, "no speculative hypothesis should have been seeded once the target was confirmed healthy"
