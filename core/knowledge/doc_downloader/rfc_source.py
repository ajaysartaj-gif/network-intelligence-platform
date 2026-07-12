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

logger = logging.getLogger("NetBrain.Knowledge.DocDownloader.RFC")

# Curated for THIS tool's actual protocol coverage (OSPF/BGP/VRRP/LACP-
# adjacent) plus the foundational specs those protocols depend on — not
# an attempt to mirror the entire RFC series.
DEFAULT_RFC_NUMBERS = [
    2328,   # OSPF version 2
    5340,   # OSPF for IPv6 (OSPFv3)
    4271,   # BGP-4
    5798,   # VRRP version 3
    826,    # ARP
    792,    # ICMP
    2131,   # DHCP
    4861,   # IPv6 Neighbor Discovery
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
