"""Regression proving the registry grows by data alone -- no orchestration
or executor code should need to change to add a technology."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.diagnostics import registry
from core.diagnostics.capability import DiagnosticActionSpec, DiagnosticCapability


def test_the_first_three_registered_technologies_are_ospf_hsrp_vrrp():
    assert registry.list_technologies() == ["hsrp", "ospf", "vrrp"]


def test_get_capability_is_case_and_whitespace_insensitive():
    assert registry.get_capability("OSPF") is registry.get_capability(" ospf ")


def test_get_capability_returns_none_for_unregistered_technology():
    assert registry.get_capability("bgp") is None


def test_get_action_spec_returns_none_for_unregistered_vendor():
    assert registry.get_action_spec("junos_like", "ospf") is None


def test_get_action_spec_returns_none_for_unregistered_technology():
    assert registry.get_action_spec("ios-like", "bgp") is None


def test_cisco_ospf_action_spec_matches_the_registered_capability():
    spec = registry.get_action_spec("ios-like", "ospf")
    assert spec.enable_commands == ["debug ip ospf adj"]


def test_a_new_technology_can_be_registered_with_pure_data(monkeypatch):
    """The actual extensibility guarantee: register a 4th technology by
    adding dict entries only, then confirm the accessors see it -- proving
    no orchestration/executor code needs touching to grow the registry."""
    fake_cap = DiagnosticCapability(
        technology="bgp", action="neighbor_debug", description="BGP neighbor events",
        safety_level="low", preconditions=[], max_duration_s=10,
        expected_evidence="BGP FSM state transitions",
    )
    fake_spec = DiagnosticActionSpec(enable_commands=["debug ip bgp neighbor"])
    monkeypatch.setitem(registry.DIAGNOSTIC_CAPABILITIES, "bgp", fake_cap)
    monkeypatch.setitem(registry.CISCO_DIAGNOSTIC_ACTIONS, "bgp", fake_spec)

    assert registry.get_capability("bgp") is fake_cap
    assert registry.get_action_spec("ios-like", "bgp") is fake_spec
    assert "bgp" in registry.list_technologies()
