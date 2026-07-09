"""
Tests for core/topology/knowledge_graph_bridge.py — the fix for the
previously-verified bug where core/intent_engine.py's _topology_facts()
instantiated a fresh, never-populated KnowledgeGraph() on every call (so
"LIVE TOPOLOGY" grounding was silently always empty).

discover_neighbors() itself (real netmiko CDP/LLDP polling) is mocked here —
that function already has its own coverage concerns (vendor command tables,
TextFSM/regex parsing) and isn't what this module is responsible for. This
suite only tests: does real neighbor data get turned into a correctly
populated graph, is the cache honored, and does the interface pairing lookup
work.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.topology.knowledge_graph_bridge as kgb
from core.topology.discovery import DiscoveryResult, NeighborRecord


class FakeDevice:
    def __init__(self, ip, hostname):
        self.ip = ip
        self.hostname = hostname


def setup_function(_):
    # Each test gets a clean slate — the module-level cache is process-global.
    kgb._cache.clear()


def _fake_discover_neighbors(r1_to_r2_iface="GigabitEthernet0/0", r2_to_r1_iface="GigabitEthernet0/0"):
    def discover(device):
        if device.ip == "10.0.12.1":
            return DiscoveryResult(
                device_ip="10.0.12.1", success=True, local_hostname="R1",
                neighbors=[NeighborRecord(
                    local_interface=r1_to_r2_iface, neighbor_name="R2",
                    neighbor_ip="10.0.12.2", neighbor_platform="cisco_ios",
                    neighbor_interface=r2_to_r1_iface, protocol="cdp",
                )],
            )
        if device.ip == "10.0.12.2":
            return DiscoveryResult(
                device_ip="10.0.12.2", success=True, local_hostname="R2",
                neighbors=[NeighborRecord(
                    local_interface=r2_to_r1_iface, neighbor_name="R1",
                    neighbor_ip="10.0.12.1", neighbor_platform="cisco_ios",
                    neighbor_interface=r1_to_r2_iface, protocol="cdp",
                )],
            )
        return DiscoveryResult(device_ip=device.ip, success=False, error="unknown")
    return discover


def test_build_knowledge_graph_populates_real_adjacency(monkeypatch):
    monkeypatch.setattr(kgb, "discover_neighbors", _fake_discover_neighbors())
    devices = [FakeDevice("10.0.12.1", "R1"), FakeDevice("10.0.12.2", "R2")]

    graph = kgb.build_knowledge_graph(devices, use_cache=False)

    assert graph.get_dependencies("10.0.12.1") == ["10.0.12.2"]
    assert graph.get_dependencies("10.0.12.2") == ["10.0.12.1"]


def test_neighbor_interfaces_lookup(monkeypatch):
    monkeypatch.setattr(kgb, "discover_neighbors",
                        _fake_discover_neighbors(r1_to_r2_iface="Gi0/0", r2_to_r1_iface="Gi0/1"))
    devices = [FakeDevice("10.0.12.1", "R1"), FakeDevice("10.0.12.2", "R2")]

    graph = kgb.build_knowledge_graph(devices, use_cache=False)

    pair = kgb.neighbor_interfaces(graph, "10.0.12.1", "10.0.12.2")
    assert pair == ("Gi0/0", "Gi0/1")
    assert kgb.neighbor_interfaces(graph, "10.0.12.2", "10.0.12.1") == ("Gi0/1", "Gi0/0")
    assert kgb.neighbor_interfaces(graph, "10.0.12.1", "10.9.9.9") is None


def test_cache_avoids_reduplicated_discovery(monkeypatch):
    calls = {"n": 0}

    def counting_discover(device):
        calls["n"] += 1
        return _fake_discover_neighbors()(device)

    monkeypatch.setattr(kgb, "discover_neighbors", counting_discover)
    devices = [FakeDevice("10.0.12.1", "R1"), FakeDevice("10.0.12.2", "R2")]

    kgb.build_knowledge_graph(devices, use_cache=True, ttl_seconds=999)
    first_call_count = calls["n"]
    assert first_call_count == 2   # one poll per device

    kgb.build_knowledge_graph(devices, use_cache=True, ttl_seconds=999)
    assert calls["n"] == first_call_count, "second call within TTL should not re-poll"


def test_discovery_failure_yields_ungrounded_but_valid_graph(monkeypatch):
    def failing_discover(device):
        raise ConnectionError("no route to host")

    monkeypatch.setattr(kgb, "discover_neighbors", failing_discover)
    devices = [FakeDevice("10.0.12.1", "R1"), FakeDevice("10.0.12.2", "R2")]

    graph = kgb.build_knowledge_graph(devices, use_cache=False)

    # Nodes still exist (from the approved device list); no edges — same
    # observable shape as "genuinely no dependencies", which callers already
    # handle as a normal case, not a crash.
    assert "10.0.12.1" in graph.nodes
    assert graph.get_dependencies("10.0.12.1") == []


def test_topology_facts_now_reports_real_adjacency(monkeypatch):
    """Direct regression test for the bug this fix addresses: intent_engine's
    _topology_facts() used to always return "" because it built an empty
    KnowledgeGraph() every call. With a populated graph, it must not."""
    monkeypatch.setattr(kgb, "discover_neighbors", _fake_discover_neighbors())
    import types
    sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
    from core.intent_engine import IntentEngine

    devices = [FakeDevice("10.0.12.1", "R1"), FakeDevice("10.0.12.2", "R2")]
    ie = IntentEngine.__new__(IntentEngine)  # bypass heavy __init__, we only need _topology_facts
    text = ie._topology_facts(devices)
    assert "LIVE TOPOLOGY" in text
    assert "R2" in text or "10.0.12.2" in text
