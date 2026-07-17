"""
Regression for a real production report: a re-investigation whose Goal
explicitly named "the OSPF neighbor 192.168.20.2 ... stuck in EXSTART"
nonetheless produced a Question vs. Evidence Mismatch banner built from a
COMPLETELY DIFFERENT neighbor's state (192.168.96.136's own healthy
adjacency, FULL) — the investigation's actual target had silently shifted,
with no explanation, to an unrelated neighbor collected in the same
evidence-gathering sweep (get_neighbors() naturally returns every neighbor
on a device, not just the one under investigation).

Root cause: _observed_protocol_state_obs() (and the ad-hoc neighbor-
observation scan inside _check_goal_evidence_match()) picked "the most
recent" or "the first" neighbor-state fact in the WHOLE session, with no
concept of which neighbor the CURRENT investigation is actually about.

Fix: _query_target_ip() extracts the specific neighbor IP a re-
investigation query names (_continue_investigation_if_needed's own
phrasing: "...the OSPF neighbor 192.168.20.2 on interface X..."), and
_observed_protocol_state_obs()/_check_goal_evidence_match()/
_bind_compiled_signature_evidence()/_compile_reasoning_chain()/
_ensure_protocol_state_observed() all scope to that neighbor when present
— returning None/continuing to probe rather than silently falling back to
an unrelated neighbor's fact.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.topology.knowledge_graph_bridge as kgb
from core.troubleshooting import TroubleshootingEngine, TSConfig
from core.troubleshooting.models import Goal, Observation, Session
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


# ── unit: _query_target_ip() ────────────────────────────────────────────────
def test_query_target_ip_extracts_the_named_neighbor():
    eng = _engine()
    query = "why is the OSPF neighbor 192.168.20.2 on interface GigabitEthernet1/0 stuck in Down"
    assert eng._query_target_ip(query) == "192.168.20.2"


def test_query_target_ip_none_for_a_generic_query():
    eng = _engine()
    assert eng._query_target_ip("why OSPF stuck in ExStart") is None


# ── unit: _observed_protocol_state_obs() scoping ────────────────────────────
def test_observed_protocol_state_obs_scoped_to_target_ip_ignores_other_neighbors():
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck"))
    session.observations.append(Observation(device="192.168.96.136", subject="neighbor.192.168.21.2",
                                            attribute="state", value="Full"))
    session.observations.append(Observation(device="192.168.20.2", subject="neighbor.192.168.21.1",
                                            attribute="state", value="Down"))

    obs = eng._observed_protocol_state_obs(session, target_ip="192.168.21.1")
    assert obs is not None and obs.value == "Down"

    obs2 = eng._observed_protocol_state_obs(session, target_ip="192.168.21.2")
    assert obs2 is not None and obs2.value == "Full"


def test_observed_protocol_state_obs_returns_none_when_target_has_no_evidence_yet():
    """Must NOT fall back to an unrelated neighbor's fact just because one
    exists — that's the exact bug being fixed."""
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck"))
    session.observations.append(Observation(device="192.168.96.136", subject="neighbor.192.168.21.2",
                                            attribute="state", value="Full"))
    obs = eng._observed_protocol_state_obs(session, target_ip="192.168.20.2")
    assert obs is None


def test_observed_protocol_state_obs_unscoped_behavior_unchanged_without_a_target():
    eng = _engine()
    session = Session(goal=Goal(query="why OSPF stuck"))
    session.observations.append(Observation(device="192.168.96.136", subject="neighbor.192.168.21.2",
                                            attribute="state", value="Full"))
    obs = eng._observed_protocol_state_obs(session)
    assert obs is not None and obs.value == "Full"


# ── unit: _check_goal_evidence_match() scoping ──────────────────────────────
def test_goal_mismatch_uses_the_named_neighbors_own_state_not_an_unrelated_one():
    eng = _engine()
    query = "why is the OSPF neighbor 192.168.20.2 on interface GigabitEthernet1/0 stuck in EXSTART"
    session = Session(goal=Goal(query=query))
    # An unrelated, healthy neighbor collected in the same sweep — must be ignored.
    session.observations.append(Observation(device="192.168.96.136", subject="neighbor.192.168.21.2",
                                            attribute="state", value="Full"))
    # The ACTUAL target neighbor's real state.
    session.observations.append(Observation(device="192.168.20.2", subject="neighbor.192.168.20.2",
                                            attribute="state", value="Down"))

    eng._check_goal_evidence_match(session, query)

    assert session.goal_mismatch is not None
    assert session.goal_mismatch["asked_state"] == "ExStart"
    assert session.goal_mismatch["observed_state"] == "Down"
    assert all(ns["subject"] == "neighbor.192.168.20.2" for ns in session.goal_mismatch["neighbor_states"])


def test_goal_mismatch_withholds_when_named_neighbor_has_no_evidence_yet():
    eng = _engine()
    query = "why is the OSPF neighbor 192.168.20.2 on interface GigabitEthernet1/0 stuck in EXSTART"
    session = Session(goal=Goal(query=query))
    session.observations.append(Observation(device="192.168.96.136", subject="neighbor.192.168.21.2",
                                            attribute="state", value="Full"))

    eng._check_goal_evidence_match(session, query)
    assert session.goal_mismatch is None


# ── real end-to-end: multi-neighbor device, re-investigation query ─────────
def _ospf_neighbor_text_two_rows(id1, state1, addr1, iface1, id2, state2, addr2, iface2):
    return (
        "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
        f"{id1}       1   {state1}/DR        00:00:33    {addr1}       {iface1}\n"
        f"{id2}       1   {state2}/BDR       00:00:36    {addr2}       {iface2}\n"
    )


def test_reinvestigation_of_one_neighbor_is_not_confused_by_a_different_healthy_neighbor(monkeypatch):
    """The exact reported scenario: R1 has TWO real OSPF neighbors — one
    healthy (FULL), one genuinely stuck (Down). A re-investigation query
    naming the STUCK one specifically must report ITS real state, never
    the healthy one's, in both the mismatch banner and the evidence used
    for hypothesis contradiction."""
    _no_real_topology(monkeypatch)
    r1 = FakeDevice("192.168.96.136", "R1")

    def send(device, cmds):
        # Router ID matches the neighbor's own address, same as every real
        # transcript in this investigation (the neighbor SUBJECT the
        # adapter builds is keyed off the row's first column, which real
        # IOS shows as the neighbor's router ID — in this lab's config
        # that's numerically identical to its address either way).
        text = _ospf_neighbor_text_two_rows(
            "192.168.21.2", "FULL", "192.168.21.2", "GigabitEthernet2/0",
            "192.168.20.2", "DOWN", "192.168.20.2", "GigabitEthernet1/0")
        return {c: text for c in cmds}

    gw = VendorGateway(send=send, hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=lambda p: "", devices=[r1], gateway=gw, config=TSConfig(max_steps=6))

    report = eng.run(
        "why is the OSPF neighbor 192.168.20.2 on interface GigabitEthernet1/0 stuck in EXSTART")
    s = report.session

    assert s.goal_mismatch is not None
    assert s.goal_mismatch["asked_state"] == "ExStart"
    # Must be Down (the NAMED neighbor's real state) -- NOT Full (the other one).
    assert s.goal_mismatch["observed_state"] == "Down", s.goal_mismatch
    assert all(ns["subject"].endswith("192.168.20.2") for ns in s.goal_mismatch["neighbor_states"])
