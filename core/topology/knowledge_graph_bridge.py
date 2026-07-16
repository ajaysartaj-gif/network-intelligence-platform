"""
core/topology/knowledge_graph_bridge.py
========================================
Populates a core.knowledge_graph.KnowledgeGraph from REAL CDP/LLDP adjacency
data, reusing core.topology.discovery.discover_neighbors() — the same,
already-tested discovery primitive core.topology.topology_engine.py uses for
the topology diagram feature.

Why this file exists instead of extending discovery.py or knowledge_graph.py
directly:
  - core/knowledge_graph.py is a small, dependency-free graph structure used
    in several places (core/orchestration_engine.py, core/resource/...); it
    should not gain a hard dependency on netmiko-based discovery.
  - core/topology/discovery.py's job is one device -> its neighbors. Turning
    a device LIST into a populated graph, with its own caching policy, is a
    distinct, smaller concern that belongs next to it, not inside it.

Caching: core/topology/topology_cache.py exists but is keyed by *site*
(site_name/city/country/region) for the full topology-diagram feature — a
different shape of request than "give me a graph for exactly these N devices
in this troubleshooting session." Reusing it would mean inventing site
metadata that doesn't exist at this call site. So this module keeps its own
small, short-TTL, in-process cache keyed by the exact device IP set instead —
this is a deliberately narrower cache for a deliberately narrower need, not a
second general-purpose topology cache.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from core.knowledge_graph import KnowledgeGraph

try:
    from core.topology.discovery import discover_neighbors
except Exception:  # pragma: no cover - defensive, mirrors other optional-dep guards in this repo
    discover_neighbors = None

logger = logging.getLogger("AI Net Studio.Topology.KnowledgeGraphBridge")

_DEFAULT_TTL_SECONDS = 15 * 60   # short: this feeds live troubleshooting, not a dashboard
_cache: Dict[Tuple[str, ...], Tuple[float, KnowledgeGraph]] = {}
_cache_lock = threading.Lock()


def _cache_key(devices: List[Any]) -> Tuple[str, ...]:
    return tuple(sorted({str(getattr(d, "ip", "")) for d in devices if getattr(d, "ip", "")}))


def build_knowledge_graph(devices: List[Any], use_cache: bool = True,
                          ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> KnowledgeGraph:
    """
    Poll CDP/LLDP on each device (parallelized) and return a populated
    KnowledgeGraph: one node per approved device (+ one node per discovered
    neighbor not in the approved set, so grounding can mention it even though
    it isn't a node the engine can query directly), one "adjacent_to" edge
    per neighbor relationship, with local_interface/neighbor_interface/
    protocol recorded in the edge metadata for callers that need real
    interface pairing (e.g. the Mismatch Investigation bridge).

    Never raises: discovery failures for individual devices are logged and
    skipped, and if netmiko isn't installed the graph is simply returned
    with nodes but no edges (callers already treat "no dependencies found"
    as a normal, ungrounded case).
    """
    key = _cache_key(devices)
    if use_cache and key:
        with _cache_lock:
            cached = _cache.get(key)
        if cached and (time.time() - cached[0]) < ttl_seconds:
            return cached[1]

    graph = KnowledgeGraph()
    ip_to_dev = {str(getattr(d, "ip", "")): d for d in devices if getattr(d, "ip", "")}
    for ip, d in ip_to_dev.items():
        graph.add_node(ip, getattr(d, "hostname", "") or ip, attributes={"approved": True})

    if discover_neighbors is None:
        logger.info("CDP/LLDP discovery unavailable (core.topology.discovery import failed); "
                    "returning ungrounded graph.")
        _store(key, graph, use_cache)
        return graph

    results = _discover_all(list(ip_to_dev.values()), discover_neighbors)

    for local_ip, result in results.items():
        if not result or not getattr(result, "success", False):
            continue
        for nbr in result.neighbors:
            neighbor_ip = (nbr.neighbor_ip or "").strip()
            neighbor_key = neighbor_ip if neighbor_ip in ip_to_dev else (
                neighbor_ip or f"discovered:{nbr.neighbor_name or local_ip + ':' + nbr.local_interface}")
            if neighbor_key not in graph.nodes:
                graph.add_node(neighbor_key, nbr.neighbor_name or neighbor_key,
                               attributes={"approved": neighbor_key in ip_to_dev,
                                          "platform": nbr.neighbor_platform})
            graph.add_relationship(
                local_ip, neighbor_key, "adjacent_to", weight=1.0,
                metadata={"local_interface": nbr.local_interface,
                         "neighbor_interface": nbr.neighbor_interface,
                         "protocol": nbr.protocol},
            )

    _store(key, graph, use_cache)
    return graph


def _discover_all(devices: List[Any], discover_fn) -> Dict[str, Any]:
    """Parallel CDP/LLDP poll, mirroring the concurrency pattern already used
    by core.topology.topology_engine.build_topology_for_site()."""
    import concurrent.futures

    out: Dict[str, Any] = {}
    if not devices:
        return out
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(devices))) as pool:
        futures = {pool.submit(discover_fn, d): getattr(d, "ip", "") for d in devices}
        for fut in concurrent.futures.as_completed(futures):
            ip = futures[fut]
            try:
                out[ip] = fut.result()
            except Exception as exc:
                logger.info("CDP/LLDP discovery failed for %s: %s", ip, exc)
    return out


def _store(key: Tuple[str, ...], graph: KnowledgeGraph, use_cache: bool) -> None:
    if use_cache and key:
        with _cache_lock:
            _cache[key] = (time.time(), graph)


def neighbor_interfaces(graph: KnowledgeGraph, local_ip: str, remote_ip: str) -> Optional[Tuple[str, str]]:
    """Convenience lookup for callers (e.g. GatewayDeviceAdapter) that need the
    real (local_interface, remote_interface) pair for a specific adjacency,
    rather than just the dependency list get_dependencies() already exposes."""
    for target, rel in graph.adjacency.get(local_ip, []):
        if target == remote_ip and rel.relationship_type == "adjacent_to":
            return rel.metadata.get("local_interface", ""), rel.metadata.get("neighbor_interface", "")
    return None
