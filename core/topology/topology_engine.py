"""
core/topology/topology_engine.py
=================================
Orchestrates building a TopologyGraph for one site:
  1. Pull approved devices belonging to that site from device_discovery
  2. Run CDP/LLDP discovery on each (parallel, via discovery.py)
  3. Merge neighbor reports into nodes + links
  4. Classify each node's role (router/switch/AP/firewall)
  5. Compute (x, y) layout coordinates
  6. Cache the result

Devices discovered as a CDP/LLDP neighbor but NOT in the approved
inventory still appear in the diagram (marked discovered_only=True)
so the topology reflects what's physically connected, even if it
hasn't been formally approved yet.
"""
from __future__ import annotations

import concurrent.futures
import logging
from typing import Any, List, Optional

from core.topology.topology_models import TopologyGraph, TopologyNode, TopologyLink, DeviceRole
from core.topology.discovery import discover_neighbors, normalize_interface_name
from core.topology.l3_discovery import discover_ip_subnets
from core.topology.role_classifier import classify_role
from core.topology.layout import compute_layout
from core.topology.topology_cache import get_topology_cache

logger = logging.getLogger("NetBrain.Topology.Engine")


def build_topology_for_site(
    site_name: str,
    city: str,
    country: str,
    region: str,
    all_approved_devices: List[Any],
    use_cache: bool = True,
    cache_ttl_minutes: int = 60,
    max_workers: int = 6,
) -> TopologyGraph:
    """
    Build (or return cached) topology for one site.

    `all_approved_devices` is the full approved inventory (DiscoveredDevice
    list) — this function filters to the ones matching the given site.
    """
    cache = get_topology_cache()

    if use_cache and cache.is_fresh(site_name, city, country, region, cache_ttl_minutes):
        cached = cache.get(site_name, city, country, region)
        if cached:
            logger.info(f"Using cached discovery data for site '{site_name}' (recomputing layout fresh)")
            # Layout is cheap pure-math, unlike CDP/LLDP polling -- recompute
            # it every time even on a cache hit, so improvements to the
            # layout algorithm show up immediately without requiring a full
            # (expensive, network-polling) Force Refresh. Only the discovery
            # data itself (which devices exist, what they're linked to) is
            # what's actually worth caching.
            compute_layout(cached)
            return cached

    site_devices = [
        d for d in all_approved_devices
        if d.site_name == site_name and d.city == city
        and d.country == country and d.region == region
    ]

    graph = TopologyGraph(site_name=site_name, city=city, country=country, region=region)

    if not site_devices:
        return graph

    # Seed nodes from our approved inventory (known devices, real metadata)
    for dev in site_devices:
        role = classify_role(
            vendor=dev.vendor, device_type=dev.device_type,
            platform_string="", capabilities="",
        )
        graph.add_node(TopologyNode(
            ip=dev.ip, hostname=dev.hostname, vendor=dev.vendor,
            device_type=dev.device_type, role=role,
            site_name=site_name, city=city, country=country, region=region,
        ))

    # Run CDP/LLDP discovery on all site devices in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(discover_neighbors, dev): dev for dev in site_devices}
        for fut in concurrent.futures.as_completed(futures, timeout=120):
            dev = futures[fut]
            try:
                result = fut.result()
            except Exception as exc:
                graph.devices_failed.append(f"{dev.hostname or dev.ip} ({exc})")
                continue

            if not result.success:
                graph.devices_failed.append(f"{dev.hostname or dev.ip} ({result.error})")
                continue

            graph.devices_polled += 1

            for nb in result.neighbors:
                # Does this neighbor match a known approved device by IP?
                neighbor_node = None
                if nb.neighbor_ip and nb.neighbor_ip in graph.nodes:
                    neighbor_node = graph.nodes[nb.neighbor_ip]
                elif nb.neighbor_ip:
                    # Discovered via CDP/LLDP but not in our approved inventory yet
                    role = classify_role(
                        platform_string=nb.neighbor_platform,
                        capabilities=nb.capabilities,
                    )
                    neighbor_node = TopologyNode(
                        ip=nb.neighbor_ip,
                        hostname=nb.neighbor_name,
                        platform_string=nb.neighbor_platform,
                        role=role,
                        site_name=site_name, city=city, country=country, region=region,
                        discovered_only=True,
                    )
                    graph.add_node(neighbor_node)
                else:
                    # No IP reported — use hostname as a synthetic key so it still shows
                    synthetic_ip = f"unknown:{nb.neighbor_name or 'device'}"
                    if synthetic_ip not in graph.nodes:
                        role = classify_role(
                            platform_string=nb.neighbor_platform,
                            capabilities=nb.capabilities,
                        )
                        graph.add_node(TopologyNode(
                            ip=synthetic_ip, hostname=nb.neighbor_name or synthetic_ip,
                            platform_string=nb.neighbor_platform, role=role,
                            site_name=site_name, city=city, country=country, region=region,
                            discovered_only=True,
                        ))
                    neighbor_node = graph.nodes[synthetic_ip]

                graph.add_link(TopologyLink(
                    device_a_ip=dev.ip,
                    device_a_port=nb.local_interface,
                    device_b_ip=neighbor_node.ip,
                    device_b_port=nb.neighbor_interface or nb.local_interface,
                    protocol=nb.protocol,
                ))

    # L3 (IP subnet) discovery -- separate pass from CDP/LLDP above, kept
    # modular since it's a genuinely different concern (interface_subnets
    # for the Logical view vs. physical adjacency for the Physical view).
    # Scoped only to site_devices (our approved inventory) -- NOT to
    # discovered_only neighbors picked up via CDP/LLDP above, since we
    # only have SSH credentials/trust for devices we've actually approved.
    # A discovered_only neighbor with no L3 data simply renders as
    # "unknown" status on its links in the Logical view rather than
    # "mismatched", which is the correct, honest state for a device we
    # haven't polled.
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(discover_ip_subnets, dev): dev for dev in site_devices}
        for fut in concurrent.futures.as_completed(futures, timeout=120):
            dev = futures[fut]
            try:
                l3_result = fut.result()
            except Exception as exc:
                logger.debug(f"L3 discovery failed for {dev.hostname or dev.ip}: {exc}")
                continue

            if not l3_result.success or dev.ip not in graph.nodes:
                continue

            node = graph.nodes[dev.ip]
            for rec in l3_result.subnets:
                node.interface_subnets[rec.interface] = rec.subnet

    compute_layout(graph)
    cache.set(graph)
    return graph


def list_available_sites(all_approved_devices: List[Any]) -> List[dict]:
    """
    Return distinct (region, country, city, site_name) tuples from approved
    devices that have site metadata set, with device counts — used to
    populate the site picker UI.
    """
    seen: dict = {}
    for dev in all_approved_devices:
        if not dev.site_name:
            continue
        key = (dev.region, dev.country, dev.city, dev.site_name)
        if key not in seen:
            seen[key] = {
                "region": dev.region, "country": dev.country,
                "city": dev.city, "site_name": dev.site_name,
                "device_count": 0,
            }
        seen[key]["device_count"] += 1
    return sorted(seen.values(), key=lambda s: (s["region"], s["country"], s["city"], s["site_name"]))
