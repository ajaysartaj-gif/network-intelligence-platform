"""
core/knowledge/doc_downloader/run.py
=====================================
Orchestrates every registered vendor doc source into pdf_downloads/.
Run directly: `python3 -m core.knowledge.doc_downloader.run [--limit N]`
"""
from __future__ import annotations

import argparse
import json
import os

from core.knowledge.doc_downloader import (
    cisco_devnet_source, fortinet_source, paloalto_source, rfc_source, versa_source,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_OUT_ROOT = os.path.join(REPO_ROOT, "pdf_downloads")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download vendor docs into pdf_downloads/")
    parser.add_argument("--out", default=DEFAULT_OUT_ROOT, help="Output root directory")
    parser.add_argument("--versa-limit", type=int, default=20,
                        help="Max Versa pages to attempt this run (bounded by default)")
    parser.add_argument("--fortinet-limit", type=int, default=20,
                        help="Max Fortinet pages to attempt this run (bounded by default)")
    parser.add_argument("--paloalto-limit", type=int, default=20,
                        help="Max pan.dev pages to attempt this run (bounded by default)")
    parser.add_argument("--skip-versa", action="store_true")
    parser.add_argument("--skip-cisco", action="store_true")
    parser.add_argument("--skip-fortinet", action="store_true")
    parser.add_argument("--skip-paloalto", action="store_true")
    parser.add_argument("--skip-rfc", action="store_true")
    args = parser.parse_args()

    results = {}
    if not args.skip_versa:
        results["versa"] = versa_source.run(args.out, limit=args.versa_limit)
    if not args.skip_cisco:
        results["cisco"] = cisco_devnet_source.run(args.out)
    if not args.skip_fortinet:
        results["fortinet"] = fortinet_source.run(args.out, limit=args.fortinet_limit)
    if not args.skip_paloalto:
        results["paloalto"] = paloalto_source.run(args.out, limit=args.paloalto_limit)
    if not args.skip_rfc:
        results["rfc"] = rfc_source.run(args.out)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
