#!/usr/bin/env python3
"""
diagnose_topology.py
====================
Standalone topology-discovery diagnostic. Run this from the repo root:

    python3 diagnose_topology.py

It bypasses the Streamlit UI AND the topology cache entirely, talks to your
real devices, and prints exactly what discovery sees at every stage:

  1. Each approved device + the hostname captured from its OWN CLI prompt
     (find_prompt) -- the anchor the dedup logic relies on.
  2. Every CDP/LLDP neighbor each device reports: name, advertised mgmt IP,
     local/remote interface.
  3. The final reconciled graph: node list (with hostname + discovered_only),
     link list, and whether it forms ONE connected diagram or fragments.

Paste the full output back and it tells us, with zero guessing, whether the
hostname capture is working and where any duplication is coming from.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env / secrets the same way app.py does, so SSH creds are present.
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
except Exception:
    pass

from core.device_discovery import get_discovery_engine
from core.topology.discovery import discover_neighbors
from core.topology.topology_engine import build_topology_for_site, list_available_sites


def main():
    print("=" * 70)
    print("NETBRAIN TOPOLOGY DISCOVERY DIAGNOSTIC")
    print("=" * 70)

    disc = get_discovery_engine()
    approved = disc.get_approved()
    print(f"\nApproved devices in inventory: {len(approved)}")
    if not approved:
        print("  (none) -- nothing to discover. Approve devices first.")
        return

    # ── STAGE 1 + 2: per-device discovery, raw ──────────────────────────────
    print("\n" + "-" * 70)
    print("STAGE 1+2: PER-DEVICE DISCOVERY (live, no cache)")
    print("-" * 70)
    for dev in approved:
        print(f"\nDevice {dev.ip}  (inventory hostname: {dev.hostname or '(empty)'}, "
              f"type: {dev.device_type}, ssh_port: {getattr(dev, 'ssh_port', 22)})")
        try:
            result = discover_neighbors(dev)
        except Exception as exc:
            print(f"  !! discover_neighbors raised: {exc}")
            continue

        if not result.success:
            print(f"  !! discovery FAILED: {result.error}")
            continue

        print(f"  -> hostname captured from prompt: "
              f"{result.local_hostname or '(EMPTY -- this is the problem if so)'}")
        if not result.neighbors:
            print("  -> no CDP/LLDP neighbors reported")
        for nb in result.neighbors:
            print(f"  -> neighbor: name={nb.neighbor_name or '(none)':10s} "
                  f"ip={nb.neighbor_ip or '(none)':16s} "
                  f"local={nb.local_interface or '?':8s} "
                  f"remote={nb.neighbor_interface or '?':8s} "
                  f"proto={nb.protocol}")

    # ── STAGE 3: reconciled graph per site ───────────────────────────────────
    print("\n" + "-" * 70)
    print("STAGE 3: RECONCILED GRAPH (use_cache=False)")
    print("-" * 70)
    sites = list_available_sites(approved)
    for site in sites:
        g = build_topology_for_site(
            site_name=site["site_name"], city=site["city"],
            country=site["country"], region=site["region"],
            all_approved_devices=approved, use_cache=False,
        )
        print(f"\nSite: {site['site_name']} ({site['city']}, {site['country']}, {site['region']})")
        print(f"  Nodes: {g.node_count()}   Links: {g.link_count()}   Polled: {g.devices_polled}")
        if g.devices_failed:
            print(f"  Failed: {g.devices_failed}")
        print("  Node list:")
        for ip, n in g.nodes.items():
            print(f"    - {ip:22s} hostname={n.hostname or '(none)':10s} "
                  f"role={n.role.value:12s} discovered_only={n.discovered_only}")
        print("  Link list:")
        for l in g.links:
            print(f"    - {l.device_a_ip} [{l.device_a_port}] <-> "
                  f"{l.device_b_ip} [{l.device_b_port}]  ({l.protocol})")

        # connectivity
        from collections import deque
        adj = {}
        for l in g.links:
            adj.setdefault(l.device_a_ip, set()).add(l.device_b_ip)
            adj.setdefault(l.device_b_ip, set()).add(l.device_a_ip)
        if g.nodes:
            start = next(iter(g.nodes))
            seen = {start}
            q = deque([start])
            while q:
                cur = q.popleft()
                for nb in adj.get(cur, ()):
                    if nb not in seen:
                        seen.add(nb)
                        q.append(nb)
            if len(seen) == g.node_count():
                print(f"  Connectivity: SINGLE connected diagram ({g.node_count()} nodes) -- correct")
            else:
                print(f"  Connectivity: FRAGMENTED -- reached {len(seen)} of "
                      f"{g.node_count()} nodes from one start. "
                      f"This means duplicate identities still exist.")

    print("\n" + "=" * 70)
    print("END DIAGNOSTIC -- paste this whole output back.")
    print("=" * 70)


if __name__ == "__main__":
    main()
