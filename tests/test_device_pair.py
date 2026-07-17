"""
Unit tests for core/troubleshooting/strategies/device_pair.py — the single
source of truth for the "between A and B" root-cause-statement convention
mismatch_bridge.py produces, shared by engine.py's fix-targeting logic and
copilot_engine.py's post-fix verification scoping so the two can never
silently drift out of sync.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.troubleshooting.strategies.device_pair import extract_between_devices


def test_extract_between_devices_finds_a_real_pair():
    statement = ("interface_mtu must equal violated on ospf_adjacency between "
                "192.168.96.136 and 192.168.20.2 (local=1500, remote=1200)")
    assert extract_between_devices(statement) == ("192.168.96.136", "192.168.20.2")


def test_extract_between_devices_none_for_a_single_device_cause():
    assert extract_between_devices("OSPF hello/dead timer mismatch on GigabitEthernet1/0") is None


def test_extract_between_devices_none_for_empty_or_malformed_text():
    assert extract_between_devices("") is None
    assert extract_between_devices(None) is None
    assert extract_between_devices("between 192.168.1.1 and not-an-ip") is None
    assert extract_between_devices("between only-one-ip-here") is None
