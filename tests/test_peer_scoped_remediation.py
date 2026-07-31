"""
Regression for a real production incident: a device with TWO real OSPF
neighbors (192.168.20.2, neighboring both R1 and a third router 192.168.21.1)
got its MTU-mismatch fix applied to the WRONG interface — FastEthernet0/0,
which faces 192.168.21.1, not R1 — because _compiled_remediation_intent's
interface resolution was scoped by device only, not by which specific
neighbor this root cause is actually about. Device-scoping alone isn't
enough once a device has more than one neighbor: "the most recent neighbor
interface fact for this device" silently picked an unrelated adjacency.

Symptom in the live report: the untouched, real problem interface (facing
R1) never got `ip ospf mtu-ignore`, and that adjacency actually regressed
from ExStart to Down after the "fix" — worse than before, not just
unresolved.

_compiled_remediation_intent(..., peer_ip=...) closes this: when the
caller knows which specific neighbor this fix is about (the two
participant IPs extracted by strategies/device_pair.py), the interface
lookup is scoped to facts naming THAT neighbor specifically, and refuses
to fall back to a different neighbor's interface if no peer-matching fact
exists.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.troubleshooting import TroubleshootingEngine
from core.troubleshooting.models import ExecutedCommand, Goal, Observation, Session


def _engine():
    return TroubleshootingEngine(ai_call=lambda p: "", devices=[])


def _session_with_two_neighbors(device_ip, other_neighbor_ip, other_iface,
                                real_peer_ip, real_iface):
    """A device with two real OSPF neighbors on two different interfaces —
    the exact shape of the reported incident."""
    session = Session(goal=Goal(query="why is OSPF stuck in EXSTART"))
    session.observations.append(Observation(
        device=device_ip, subject=f"neighbor.{other_neighbor_ip}",
        attribute="interface", value=other_iface))
    session.observations.append(Observation(
        device=device_ip, subject=f"neighbor.{real_peer_ip}",
        attribute="interface", value=real_iface))
    return session


STATEMENT = "MTU mismatch between OSPF neighbors prevents DBD packet exchange"


def test_peer_scoped_lookup_picks_the_correct_neighbors_interface():
    eng = _engine()
    device_ip = "192.168.20.2"
    session = _session_with_two_neighbors(
        device_ip, other_neighbor_ip="192.168.21.1", other_iface="FastEthernet0/0",
        real_peer_ip="192.168.96.136", real_iface="GigabitEthernet1/0")

    intent = eng._compiled_remediation_intent(
        session, STATEMENT, allowed_intents=["ignore_protocol_mtu"], protocol="ospf",
        discriminating_signals=["ExStart"], device_ip=device_ip, peer_ip="192.168.96.136")

    assert intent is not None
    assert intent["params"]["interface"] == "GigabitEthernet1/0", intent


def test_without_peer_ip_the_old_ambiguous_behavior_is_unchanged():
    """No peer_ip given (single-device / legacy call sites) -> falls back
    to the most-recent-neighbor-interface-for-this-device heuristic,
    exactly as before this fix. Documents the pre-existing ambiguity
    rather than silently changing behavior for callers that don't know
    a specific peer."""
    eng = _engine()
    device_ip = "192.168.20.2"
    session = _session_with_two_neighbors(
        device_ip, other_neighbor_ip="192.168.21.1", other_iface="FastEthernet0/0",
        real_peer_ip="192.168.96.136", real_iface="GigabitEthernet1/0")

    intent = eng._compiled_remediation_intent(
        session, STATEMENT, allowed_intents=["ignore_protocol_mtu"], protocol="ospf",
        discriminating_signals=["ExStart"], device_ip=device_ip)

    # most recent observation wins when unscoped -- the real_peer's fact
    # was appended last in this fixture, so it happens to win here; the
    # point is this path is NOT peer-aware, unlike the peer_ip path above.
    assert intent is not None
    assert intent["params"]["interface"] == "GigabitEthernet1/0"


def test_single_neighbor_device_is_used_even_when_its_subject_doesnt_match_peer_ip():
    """A device with only ONE real neighbor has no actual ambiguity to
    resolve, even if that neighbor's subject is keyed by its OSPF
    router-id rather than its device IP (a common, legitimate config --
    router-id is frequently loopback-based, independent of any interface
    address) and so never literally contains peer_ip. Requiring an exact
    peer_ip match here would wrongly skip the fix for the overwhelming
    common case just because of a naming mismatch that isn't actually
    ambiguous."""
    eng = _engine()
    device_ip = "192.168.20.2"
    session = Session(goal=Goal(query="why is OSPF stuck in EXSTART"))
    # router-id "2.2.2.2" != peer's device IP "192.168.96.136" -- a real,
    # common case (the original flagship end-to-end fixture uses this
    # exact shape) -- but this is the device's ONLY neighbor.
    session.observations.append(Observation(
        device=device_ip, subject="neighbor.2.2.2.2",
        attribute="interface", value="GigabitEthernet1/0"))

    intent = eng._compiled_remediation_intent(
        session, STATEMENT, allowed_intents=["ignore_protocol_mtu"], protocol="ospf",
        discriminating_signals=["ExStart"], device_ip=device_ip, peer_ip="192.168.96.136")

    assert intent is not None
    assert intent["params"]["interface"] == "GigabitEthernet1/0", intent


def test_multi_neighbor_device_returns_no_interface_when_the_real_peer_is_genuinely_absent():
    """With TWO distinct neighbors and neither one's subject matching the
    named peer at all, there IS real ambiguity -- iface must stay empty
    (causing this device to be skipped for the fix) rather than silently
    falling back to an unrelated neighbor's interface, the exact mistake
    that caused the real incident."""
    eng = _engine()
    device_ip = "192.168.20.2"
    session = Session(goal=Goal(query="why is OSPF stuck in EXSTART"))
    session.observations.append(Observation(
        device=device_ip, subject="neighbor.192.168.21.1",
        attribute="interface", value="FastEthernet0/0"))
    session.observations.append(Observation(
        device=device_ip, subject="neighbor.192.168.22.1",
        attribute="interface", value="FastEthernet0/1"))
    # neither neighbor fact names the real peer, 192.168.96.136

    intent = eng._compiled_remediation_intent(
        session, STATEMENT, allowed_intents=["ignore_protocol_mtu"], protocol="ospf",
        discriminating_signals=["ExStart"], device_ip=device_ip, peer_ip="192.168.96.136")

    assert intent is not None
    assert intent["params"]["interface"] == "", intent


def test_executed_command_interface_still_takes_priority_over_peer_scoping():
    """An explicit get_interface_details() executed for this device still
    wins first (unchanged priority order) -- peer_ip only affects the
    neighbor-table fallback below it."""
    eng = _engine()
    device_ip = "192.168.20.2"
    session = _session_with_two_neighbors(
        device_ip, other_neighbor_ip="192.168.21.1", other_iface="FastEthernet0/0",
        real_peer_ip="192.168.96.136", real_iface="GigabitEthernet1/0")
    session.executed.append(ExecutedCommand(
        device=device_ip, command="get_interface_details(interface=Loopback0)"))

    intent = eng._compiled_remediation_intent(
        session, STATEMENT, allowed_intents=["ignore_protocol_mtu"], protocol="ospf",
        discriminating_signals=["ExStart"], device_ip=device_ip, peer_ip="192.168.96.136")

    assert intent is not None
    assert intent["params"]["interface"] == "Loopback0"
