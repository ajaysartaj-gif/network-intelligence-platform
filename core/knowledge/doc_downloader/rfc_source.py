"""
core/knowledge/doc_downloader/rfc_source.py
============================================
Populates pdf_downloads/rfc/ — vendor-NEUTRAL, deliberately not nested
under any OEM folder, since an RFC is a protocol standard, not one
vendor's document. Reuses the already-existing, already-working
core.knowledge.fetchers.rfc_fetcher.fetch_rfc_text() (rfc-editor.org is a
public IETF archive with no restrictions worth noting — no evaluation
needed the way cisco.com/versa/fortinet required).

Saved as plain text (.txt), matching what fetch_rfc_text() actually
returns — rfc-editor.org's own PDF renditions live at a different,
less reliable path, and this project's existing fetcher already has a
proven, working URL for the plain-text body.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import List

from core.knowledge.doc_downloader.manifest import DownloadManifest, ManifestEntry
from core.knowledge.fetchers.rfc_fetcher import fetch_rfc_text

logger = logging.getLogger("AI Net Studio.Knowledge.DocDownloader.RFC")

# Curated for THIS tool's actual protocol coverage (OSPF/BGP/VRRP/LACP-
# adjacent) plus the foundational specs those protocols depend on — not
# an attempt to mirror the entire RFC series.
DEFAULT_RFC_NUMBERS = [
    # OSPF
    2328,   # OSPF version 2
    5340,   # OSPF for IPv6 (OSPFv3)
    # BGP
    4271,   # BGP-4
    4360,   # BGP extended communities
    2385,   # BGP MD5 authentication
    5065,   # BGP confederations
    4724,   # BGP graceful restart
    6793,   # 4-byte AS number space
    7911,   # BGP additional paths
    # FHRP
    5798,   # VRRP version 3
    3768,   # VRRP version 2
    # EIGRP (informational, Cisco-authored but IETF-published)
    7868,   # EIGRP
    # IS-IS
    1195,   # IS-IS for IP
    # RIP
    2453,   # RIPv2
    # MPLS / VPN / overlay
    3031,   # MPLS architecture
    4364,   # BGP/MPLS IP VPNs (L3VPN)
    7432,   # EVPN
    7348,   # VXLAN
    # Foundational L2/L3
    826,    # ARP
    792,    # ICMP
    2131,   # DHCP
    3046,   # DHCP relay agent information
    4861,   # IPv6 Neighbor Discovery
    4862,   # IPv6 SLAAC
    8200,   # IPv6 (Internet Protocol, Version 6) Specification
    1918,   # private address allocation
    # Spanning tree / bridging context (informational — actual spec is
    # IEEE 802.1D, but this RFC documents bridging concepts in IETF terms)
    5556,   # Transparent Interconnection of Lots of Links (TRILL) problem statement
    # QoS / signaling
    2475,   # DiffServ architecture
    3168,   # ECN
    # First-hop / reachability diagnostics
    1256,   # ICMP router discovery
]


def run(out_root: str, rfc_numbers: List[int] = None) -> dict:
    summary = {"vendor": "rfc", "downloaded": 0, "skipped": 0, "errors": []}
    rfc_numbers = rfc_numbers if rfc_numbers is not None else DEFAULT_RFC_NUMBERS
    manifest = DownloadManifest(out_root)
    dest_dir = os.path.join(out_root, "rfc")
    os.makedirs(dest_dir, exist_ok=True)

    for number in rfc_numbers:
        source_url = f"https://www.rfc-editor.org/rfc/rfc{number}.txt"
        if manifest.has(source_url):
            summary["skipped"] += 1
            continue
        try:
            fetched = fetch_rfc_text(number)
        except Exception as exc:
            summary["errors"].append(f"RFC {number}: {exc}")
            continue
        if not fetched:
            summary["errors"].append(f"RFC {number}: fetch failed or not found")
            continue

        dest_path = os.path.join(dest_dir, f"rfc{number}.txt")
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(fetched["content"])

        sha256 = hashlib.sha256(fetched["content"].encode("utf-8")).hexdigest()
        manifest.record(ManifestEntry(
            source_url=source_url, vendor="rfc", doc_type="standard",
            title=fetched["title"], local_path=dest_path, sha256=sha256))
        summary["downloaded"] += 1
        logger.info("Downloaded RFC %d -> %s", number, dest_path)

    return summary
