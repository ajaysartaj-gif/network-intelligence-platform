"""
Regression for a real production report: the user asked "why OSPF stuck
into the Exstart?" but the actual collected evidence showed every neighbor
in Down, not ExStart. The engine correctly diagnosed the REAL observed
problem (Down: no hello packets exchanged) but never told the user their
own question's premise didn't match reality — the Goal text kept repeating
"stuck in the Exstart state" verbatim while the rest of the report quietly
answered a different question. A human engineer's first move is to say so
explicitly: "you asked about ExStart, but the evidence shows Down" — not
silently pivot underneath the user.

TroubleshootingEngine._check_goal_evidence_match() closes this gap by
setting session.goal_mismatch whenever the query names a specific FSM
state that the actually-observed state contradicts; the report surfaces it
as an explicit "Question vs. Evidence Mismatch" section.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.topology.knowledge_graph_bridge as kgb
from core.troubleshooting import TroubleshootingEngine, TSConfig
from core.troubleshooting.models import Observation, Session, Goal
from core.vendor import VendorGateway


class FakeDevice:
    def __init__(self, ip, hostname, device_type="cisco_ios"):
        self.ip = ip
        self.hostname = hostname
        self.device_type = device_type


def _no_real_topology(monkeypatch):
    monkeypatch.setattr(kgb, "build_knowledge_graph", lambda devices, **kw: kgb.KnowledgeGraph())


def _engine(devices=None, gateway=None):
    return TroubleshootingEngine(ai_call=lambda p: "", devices=devices or [], gateway=gateway)


# ── unit tests: _check_goal_evidence_match() in isolation ──────────────────
def test_asked_exstart_but_observed_down_sets_goal_mismatch():
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck into the Exstart?"))
    session.observations.append(Observation(device="10.0.0.1", subject="neighbor.2.2.2.2",
                                            attribute="state", value="Down"))
    eng._check_goal_evidence_match(session, session.goal.query)
    assert session.goal_mismatch is not None
    assert session.goal_mismatch["asked_state"] == "ExStart"
    assert session.goal_mismatch["observed_state"] == "Down"
    assert session.goal_mismatch["devices"] == ["10.0.0.1"]


def test_asked_and_observed_state_match_sets_no_mismatch():
    eng = _engine()
    session = Session(goal=Goal(query="why is the OSPF neighbor stuck in ExStart"))
    session.observations.append(Observation(device="10.0.0.1", subject="neighbor.2.2.2.2",
                                            attribute="state", value="ExStart"))
    eng._check_goal_evidence_match(session, session.goal.query)
    assert session.goal_mismatch is None


def test_query_without_a_named_state_sets_no_mismatch():
    eng = _engine()
    session = Session(goal=Goal(query="why is BGP not forming"))
    session.observations.append(Observation(device="10.0.0.1", subject="neighbor.2.2.2.2",
                                            attribute="state", value="Down"))
    eng._check_goal_evidence_match(session, session.goal.query)
    assert session.goal_mismatch is None


def test_no_observed_state_yet_sets_no_mismatch():
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck in ExStart"))
    eng._check_goal_evidence_match(session, session.goal.query)
    assert session.goal_mismatch is None


# ── end-to-end: real adapter/gateway, exact reported scenario ──────────────
def _ospf_interface_text(area, router_id, prefix_ip):
    return (
        f"GigabitEthernet0/0 is up, line protocol is up\n"
        f"  Internet Address {prefix_ip}/24, Area {area}\n"
        f"  Process ID 1, Router ID {router_id}, Network Type BROADCAST, Cost: 1\n"
        f"  Timer intervals configured, Hello 10, Dead 40, Wait 40, Retransmit 5\n"
        f"  Neighbor Count is 1, Adjacent neighbor count is 0\n"
    )


def _ospf_neighbor_text(neighbor_router_id, state, neighbor_addr):
    return (
        "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
        f"{neighbor_router_id}       0   {state}/  -        00:00:33    {neighbor_addr}       GigabitEthernet0/0\n"
    )


def _show_interface_text(mtu=1500):
    return (
        "GigabitEthernet0/0 is up, line protocol is up\n"
        "  Hardware is BCM1250 Internal MAC, address is 0011.2233.4455\n"
        f"  MTU {mtu} bytes, BW 1000000 Kbit/sec, DLY 10 usec,\n"
        "     reliability 255/255, txload 1/255, rxload 1/255\n"
    )


def _build_gateway_stuck_in_down():
    """Both neighbors genuinely stuck in Down (no hello exchange at all) —
    the real state behind the report, as opposed to the ExStart the user's
    question assumed."""
    r1 = FakeDevice("192.168.96.136", "R1")
    r2 = FakeDevice("192.168.20.2", "R2")

    responses = {
        ("192.168.96.136", "show ip ospf interface"): _ospf_interface_text("0", "1.1.1.1", "192.168.96.136"),
        ("192.168.96.136", "show ip ospf neighbor"): _ospf_neighbor_text("2.2.2.2", "DOWN", "192.168.20.2"),
        ("192.168.96.136", "show interface"): _show_interface_text(),
        ("192.168.96.136", "show running-config | section ^interface"): "",
        ("192.168.20.2", "show ip ospf interface"): _ospf_interface_text("0", "2.2.2.2", "192.168.20.2"),
        ("192.168.20.2", "show ip ospf neighbor"): _ospf_neighbor_text("1.1.1.1", "DOWN", "192.168.96.136"),
        ("192.168.20.2", "show interface"): _show_interface_text(),
        ("192.168.20.2", "show running-config | section ^interface"): "",
    }

    def send(device, cmds):
        return {c: responses.get((device.ip, c), "") for c in cmds}

    def hint_provider(device):
        return {"device_type": device.device_type, "hostname": device.hostname}

    gw = VendorGateway(send=send, hint_provider=hint_provider)
    ip_to_dev = {r1.ip: r1, r2.ip: r2}
    return gw, ip_to_dev


def test_asked_about_exstart_but_real_devices_are_down_surfaces_explicit_mismatch(monkeypatch):
    _no_real_topology(monkeypatch)
    gw, ip_to_dev = _build_gateway_stuck_in_down()
    devices = list(ip_to_dev.values())

    eng = TroubleshootingEngine(ai_call=lambda p: "", devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why OSPF stuck into the Exstart?")
    s = report.session

    assert s.goal_mismatch is not None, "engine never noticed the question's premise didn't match evidence"
    assert s.goal_mismatch["asked_state"] == "ExStart"
    assert s.goal_mismatch["observed_state"] == "Down"

    md = report.to_markdown()
    assert "Question vs. Evidence Mismatch" in md
    assert "ExStart" in md and "Down" in md

    # The engine must still investigate and report on the REAL observed
    # problem (Down), not fabricate an ExStart diagnosis to match the
    # user's (incorrect) premise.
    top = s.top()
    assert top is not None
    assert "ExStart" not in (top.rationale or "") or "Down" in (top.rationale or "")


# ── same check on a SECOND, differently-shaped protocol (BGP) — proves the
# mismatch detector generalizes across protocols instead of only having
# been verified for the one protocol a user happened to report ──────────
def test_asked_about_bgp_active_but_real_neighbor_is_idle_surfaces_mismatch():
    devices = [FakeDevice("10.0.0.1", "R1")]
    idle_text = (
        "BGP router identifier 1.1.1.1, local AS number 65001\n\n"
        "Neighbor        V           AS MsgRcvd MsgSent   TblVer  InQ OutQ  Up/Down  State/PfxRcd\n"
        "10.0.0.3        4        65003        0        0        0    0    0 never    Idle\n"
    )
    gw = VendorGateway(send=lambda d, cmds: {c: idle_text for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=lambda p: "", devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    report = eng.run("why is the BGP neighbor stuck in Active state")
    s = report.session

    assert s.goal_mismatch is not None, "BGP goal/evidence mismatch was never detected"
    assert s.goal_mismatch["asked_state"] == "Active"
    assert s.goal_mismatch["observed_state"] == "Idle"
    assert "Question vs. Evidence Mismatch" in report.to_markdown()
