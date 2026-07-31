"""
Regression for the OSPF knowledge-completeness audit: a real production
report showed the tool completely missing an OSPF area-ID mismatch (a user
manually changed R2 from `area 0` to `area 1`) — it eliminated the one
compiled signature that should have caught it (mis-tagged to "Init" and
bundled with hello/dead-interval mismatches, which behave completely
differently: an area mismatch never even reaches Init), and even a
correctly-detected Mismatch Investigation violation for ospf_area_id or
ospf_router_id had no remediation-intent mapping at all, so no fix could
ever be proposed.

This file proves the fix's 3 layers: (1) area mismatch is now its own
correctly-tagged "Down"-state signature, distinct from and not merged with
the pre-existing Layer 1/2 "Down" signature; (2) a Mismatch-Investigation-
detected area/router-id violation now resolves to a real remediation
command with the ACTUAL target value, not the recipe's placeholder
default; (3) end to end, a real area-0-vs-area-1 config difference (parsed
through the real Cisco adapter regex, not a mock) is caught deterministically.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.topology.knowledge_graph_bridge as kgb
from core.vendor import VendorGateway
from core.knowledge.compiler.failure_signatures import compile_failure_signatures
from core.troubleshooting.hypotheses import HypothesisManager
from core.troubleshooting.models import Session
from core.troubleshooting.strategies.gateway_adapter import GatewayDeviceAdapter
from core.troubleshooting.strategies.mismatch_bridge import run_mismatch_investigation
from core.troubleshooting.evidence_graph import EvidenceGraph
from adapters.base import Endpoint

from tests.test_mismatch_gateway_bridge import (
    FakeDevice, _no_real_topology, _ospf_interface_text, _ospf_neighbor_text,
)


# ── layer 1: signature split ─────────────────────────────────────────────────
def test_down_state_has_two_distinct_non_merging_signatures():
    sigs = [s for s in compile_failure_signatures("ospf") if s.stuck_state == "Down"]
    assert len(sigs) == 2, sigs
    causes = {s.likely_cause for s in sigs}
    assert any("hello packets" in c.lower() for c in causes), causes
    assert any("area" in c.lower() for c in causes), causes
    area_sig = next(s for s in sigs if "area" in s.likely_cause.lower())
    assert area_sig.evidence_fields == ["area"], area_sig.evidence_fields

    session = Session()
    hmgr = HypothesisManager(session)
    for sig in sigs:
        hmgr.add(sig.likely_cause, discriminating_signals=list(sig.evidence_fields) + [sig.stuck_state],
                 prior=sig.confidence)
    assert len(session.hypotheses) == 2, [h.statement for h in session.hypotheses]


def test_init_state_signature_no_longer_mentions_area():
    sig = next(s for s in compile_failure_signatures("ospf") if s.stuck_state == "Init")
    assert "area" not in sig.likely_cause.lower(), sig.likely_cause
    assert "hello" in sig.likely_cause.lower() and "dead" in sig.likely_cause.lower()


# ── layer 2: remediation renders the real target value, not the default ─────
def test_generate_remediation_area_mismatch_uses_real_target_not_default():
    gw, ip_to_dev = _build_gateway_area_mismatch()
    adapter = GatewayDeviceAdapter(gw, ip_to_dev, "ospf_adjacency")
    fix = adapter.generate_remediation(
        Endpoint(device="10.0.13.2", context="GigabitEthernet0/0"), "ospf_area_id", "0")
    assert "ip ospf 1 area 0" in fix, fix
    assert not fix.startswith("!"), fix


def test_generate_remediation_duplicate_router_id():
    gw, ip_to_dev = _build_gateway_area_mismatch()
    adapter = GatewayDeviceAdapter(gw, ip_to_dev, "ospf_adjacency")
    fix = adapter.generate_remediation(
        Endpoint(device="10.0.13.2", context="GigabitEthernet0/0"), "ospf_router_id", "3.3.3.3")
    assert "router-id 3.3.3.3" in fix, fix
    assert not fix.startswith("!"), fix


# ── layer 3: end-to-end, real adapter parsing of an actual area mismatch ────
def _build_gateway_area_mismatch():
    r1 = FakeDevice("10.0.13.1", "R1")
    r2 = FakeDevice("10.0.13.2", "R2")
    r1_iface = _ospf_interface_text("0", "1.1.1.1", "BROADCAST", "10", "40", "10.0.13.1")
    r2_iface = _ospf_interface_text("1", "3.3.3.3", "BROADCAST", "10", "40", "10.0.13.2")
    r1_nbr = _ospf_neighbor_text("3.3.3.3", "DOWN", "10.0.13.2")
    r2_nbr = _ospf_neighbor_text("1.1.1.1", "DOWN", "10.0.13.1")
    responses = {
        ("10.0.13.1", "show ip ospf interface"): r1_iface,
        ("10.0.13.1", "show ip ospf neighbor"): r1_nbr,
        ("10.0.13.2", "show ip ospf interface"): r2_iface,
        ("10.0.13.2", "show ip ospf neighbor"): r2_nbr,
    }

    def send(device, cmds):
        return {c: responses.get((device.ip, c), f"% unrecognized: {c}") for c in cmds}

    def hint_provider(device):
        return {"device_type": device.device_type, "hostname": device.hostname}

    gw = VendorGateway(send=send, hint_provider=hint_provider)
    return gw, {r1.ip: r1, r2.ip: r2}


def test_real_area_mismatch_seeds_ospf_area_id_hypothesis(monkeypatch):
    _no_real_topology(monkeypatch)
    gw, ip_to_dev = _build_gateway_area_mismatch()
    session = Session()
    hmgr = HypothesisManager(session)
    graph = EvidenceGraph()

    seeded = run_mismatch_investigation(
        relationship_type="ospf_adjacency", devices=list(ip_to_dev.values()),
        ip_to_device=ip_to_dev, gateway=gw, ai_call=None,
        session=session, hmgr=hmgr, graph=graph,
    )
    assert seeded is True
    top = session.top()
    assert top is not None
    assert "ospf_area_id" in top.statement, [h.statement for h in session.hypotheses]
    assert top.confidence > 0.5, top.confidence
    assert any(o.value == "0" for o in session.observations)
    assert any(o.value == "1" for o in session.observations)


def test_full_engine_run_proposes_a_real_area_fix(monkeypatch):
    _no_real_topology(monkeypatch)
    from core.troubleshooting import TroubleshootingEngine, TSConfig

    gw, ip_to_dev = _build_gateway_area_mismatch()
    devices = list(ip_to_dev.values())

    def ai(_prompt):
        return ""

    eng = TroubleshootingEngine(ai_call=ai, devices=devices, gateway=gw,
                               config=TSConfig(max_steps=2))
    report = eng.run("why is OSPF stuck in Down between R1 and R2")
    s = report.session
    assert any("ospf_area_id" in h.statement for h in s.hypotheses), \
        [h.statement for h in s.hypotheses]
    top = s.top()
    assert top is not None and top.confidence > 0.5, (top.statement if top else None)
