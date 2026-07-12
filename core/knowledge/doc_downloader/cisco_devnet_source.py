"""
core/knowledge/doc_downloader/cisco_devnet_source.py
=====================================================
Populates pdf_downloads/cisco/<doc_type>/ using ONLY Cisco's own free,
official DevNet Content Search MCP (core.knowledge.mcp.devnet_content_source)
— already built and wired into this codebase's live troubleshooting path.
No scraping of cisco.com: that domain returned HTTP 403 on every request
tried during evaluation, including its own robots.txt, meaning its
edge/WAF actively blocks non-browser automated access. Defeating that
would mean deliberately circumventing a vendor's own access control, which
this module does not attempt.

Real, honest scope limit: the DevNet Content Search MCP's own coverage is
Meraki and Catalyst Center APIs specifically (see devnet_content_source.py's
own module docstring) — not classic IOS/OSPF/BGP CLI documentation. Saved
files are plain-text/markdown (the MCP returns structured API-doc fields,
not a scanned/authored PDF), clearly labeled with their real source so
nothing here is mistaken for a scraped vendor PDF.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import List

from core.knowledge.doc_downloader.classify import classify_doc_type, safe_filename
from core.knowledge.doc_downloader.manifest import DownloadManifest, ManifestEntry
from core.knowledge.mcp.devnet_content_source import DevNetContentMCPSource

logger = logging.getLogger("NetBrain.Knowledge.DocDownloader.CiscoDevNet")

# A curated topic list spanning the MCP's real coverage (Meraki + Catalyst
# Center) and every doc_type category that coverage can plausibly satisfy —
# NOT an attempt to enumerate "all Cisco docs" (that's exactly the scope
# the 403s rule out doing via automation).
DEFAULT_TOPICS = [
    # Meraki dashboard API — organizations/networks/devices
    ("meraki dashboard API organizations", "meraki"),
    ("meraki dashboard API networks", "meraki"),
    ("meraki dashboard API devices", "meraki"),
    ("meraki dashboard API licensing", "meraki"),
    ("meraki dashboard API webhooks alerts", "meraki"),
    # Meraki wireless
    ("meraki wireless troubleshooting client connectivity", "meraki"),
    ("meraki wireless SSID configuration API", "meraki"),
    ("meraki wireless RF profiles API", "meraki"),
    # Meraki switch
    ("meraki switch port configuration API", "meraki"),
    ("meraki switch stack configuration API", "meraki"),
    ("meraki switch STP configuration API", "meraki"),
    # Meraki security appliance / SD-WAN
    ("meraki security appliance VPN configuration API", "meraki"),
    ("meraki security appliance firewall rules API", "meraki"),
    ("meraki SD-WAN uplink configuration API", "meraki"),
    # Meraki camera / sensor
    ("meraki camera configuration API", "meraki"),
    ("meraki sensor telemetry API", "meraki"),
    # Catalyst Center — device lifecycle
    ("catalyst center device provisioning API", "catalyst"),
    ("catalyst center device onboarding API", "catalyst"),
    ("catalyst center software image management API", "catalyst"),
    # Catalyst Center — assurance/health
    ("catalyst center assurance troubleshooting API", "catalyst"),
    ("catalyst center network health API", "catalyst"),
    ("catalyst center path trace API", "catalyst"),
    # Catalyst Center — configuration/automation
    ("catalyst center template configuration API", "catalyst"),
    ("catalyst center SDA fabric configuration API", "catalyst"),
    ("catalyst center event notification webhook API", "catalyst"),
]


def run(out_root: str, topics: List[tuple] = None) -> dict:
    summary = {"vendor": "cisco", "downloaded": 0, "skipped": 0, "errors": []}
    topics = topics if topics is not None else DEFAULT_TOPICS
    manifest = DownloadManifest(out_root)
    source = DevNetContentMCPSource()

    for command, platform in topics:
        source_key = f"devnet-mcp:{command}:{platform}"
        if manifest.has(source_key):
            summary["skipped"] += 1
            continue
        try:
            entry = source.lookup("cisco", command, platform)
        except Exception as exc:
            summary["errors"].append(f"{command}: {exc}")
            continue
        if entry is None:
            summary["errors"].append(f"{command}: no result from DevNet MCP")
            continue

        title = entry.citation.source_title or command
        content = (
            f"# {title}\n\n"
            f"Source: Cisco DevNet Content Search MCP (official API, no scraping)\n"
            f"Source URL: {entry.citation.source_url or 'n/a'}\n"
            f"Platform: {entry.platform or platform}\n"
            f"Fetched: {entry.fetched_at}\n\n"
            f"## Command / topic\n{entry.command}\n\n"
            f"## Syntax\n{entry.syntax}\n\n"
            f"## Description\n{entry.description}\n\n"
        )
        if entry.example_output:
            content += f"## Example output\n```\n{entry.example_output}\n```\n"

        doc_type = classify_doc_type(title=title, path=command)
        dest_dir = os.path.join(out_root, "cisco", doc_type)
        os.makedirs(dest_dir, exist_ok=True)
        # Filename is built from the QUERY topic, never entry.citation.
        # source_title alone — the DevNet MCP's source_title reflects which
        # underlying TOOL answered (e.g. "Meraki-API-Doc-Search"), which is
        # shared by every topic routed to that same tool. Two different
        # topics landing on the same tool would otherwise produce the exact
        # same filename and silently overwrite each other on disk (caught
        # in a real run: "catalyst center device provisioning API" and
        # "catalyst center template configuration API" both resolved to
        # "CatalystCenter-API-Doc-Search" and the second wiped out the
        # first's saved content before this fix).
        filename = safe_filename(command, fallback=f"cisco_{doc_type}_{len(manifest)}", ext=".md")
        dest_path = os.path.join(dest_dir, filename)
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(content)

        sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        manifest.record(ManifestEntry(
            source_url=source_key, vendor="cisco", doc_type=doc_type,
            title=title, local_path=dest_path, sha256=sha256))
        summary["downloaded"] += 1
        logger.info("Saved [%s] %s -> %s", doc_type, title, dest_path)

    return summary
