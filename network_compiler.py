#!/usr/bin/env python3
"""
network_compiler.py — the Network Compiler CLI
================================================
Universal knowledge loader for the platform's Enterprise Knowledge Layer
(core/knowledge/enterprise/): ingests RFCs, vendor docs, release notes,
design/config guides, golden configs, TAC/bug text, runbooks, YANG models,
etc. — in PDF/DOCX/JSON/YAML/XML/CSV/HTML/Markdown/plain-text form — into
the same versioned, deduped, hybrid-search knowledge base the
troubleshooting engine already queries via
core.knowledge.orchestrator.KnowledgeOrchestrator.rag_query()
(see core/intent_engine.py:_ground / _rag_context_for).

This is the "phase 2" CLI: rag_ingest.py talks directly to the bare
RAGEngine (no source-type taxonomy, no versioning); this one drives the
EnterpriseKnowledgeLayer instead. Both write to the same ChromaDB
collection, so either can be used interchangeably for retrieval.

Examples
--------
  # Ingest one file (format auto-detected from extension):
  python3 network_compiler.py ingest ./docs/ospf_design.pdf --source-type design_guide --vendor cisco

  # Ingest a whole directory, recursively, any supported format:
  python3 network_compiler.py ingest ./tac_cases --source-type bug_report

  # Run the conventional folder-tree pipeline (vendor_docs/, rfcs/, runbooks/, ...):
  python3 network_compiler.py standard ./knowledge

  # Fetch and ingest an RFC by number:
  python3 network_compiler.py rfc 2328

  # Trigger a live vendor doc fetch and persist it into the knowledge base:
  python3 network_compiler.py vendor-doc cisco "show ip ospf neighbor" --platform ios-xe

  # Query the knowledge base:
  python3 network_compiler.py search "OSPF stuck in EXSTART" --source-types vendor_docs,rfc

  # Show what's in the store:
  python3 network_compiler.py stats
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.knowledge.enterprise.knowledge_layer import SourceType, get_knowledge_layer
from core.knowledge.enterprise.pipelines import (
    ingest_directory, ingest_file, ingest_rfc, run_standard_pipelines,
)


def _tags(arg):
    return [t.strip() for t in (arg or "").split(",") if t.strip()]


def cmd_ingest(args):
    layer = get_knowledge_layer()
    source_type = SourceType(args.source_type)
    if os.path.isdir(args.path):
        summary = ingest_directory(
            args.path, source_type, vendor=args.vendor or "",
            platform=args.platform or "", tags=_tags(args.tags), layer=layer,
        )
        print(f"Ingested directory '{args.path}' as {source_type.value}:")
        print(f"  files ingested: {summary['ingested']}, skipped: {summary['skipped']}")
        if summary["errors"]:
            print(f"  errors: {len(summary['errors'])}")
            for e in summary["errors"][:10]:
                print(f"    ! {e}")
    else:
        r = ingest_file(
            args.path, source_type, vendor=args.vendor or "",
            platform=args.platform or "", tags=_tags(args.tags), layer=layer,
        )
        if r.get("skipped"):
            print(f"Skipped '{args.path}': {r.get('reason')}")
        else:
            print(f"Ingested '{args.path}' as {source_type.value} — "
                  f"version {r.get('version')}, {r.get('chunks')} chunk(s).")


def cmd_standard(args):
    out = run_standard_pipelines(args.base_dir)
    if not out:
        print(f"No known subfolders found under {args.base_dir}")
        return
    for folder, summary in out.items():
        print(f"{folder}: ingested {summary['ingested']}, skipped {summary['skipped']}, "
              f"errors {len(summary['errors'])}")


def cmd_rfc(args):
    r = ingest_rfc(args.number)
    if r.get("skipped"):
        print(f"RFC {args.number}: skipped — {r.get('reason')}")
    else:
        print(f"RFC {args.number}: ingested — version {r.get('version')}, "
              f"{r.get('chunks')} chunk(s).")


def cmd_vendor_doc(args):
    from core.knowledge.vendor_router import get_fetcher

    fetcher = get_fetcher(args.vendor)
    if not fetcher:
        print(f"No fetcher registered for vendor '{args.vendor}'")
        return
    entry = fetcher.fetch(args.command, args.platform)
    if not entry:
        print(f"No live doc found for '{args.command}' ({args.vendor})")
        return
    layer = get_knowledge_layer()
    from core.knowledge.enterprise.knowledge_layer import KnowledgeRecord

    doc_id = f"vendor_docs:{args.vendor}:{args.command}"
    content = f"{entry.description}\n\nSyntax:\n{entry.syntax}".strip()
    rec = KnowledgeRecord(
        doc_id=doc_id, title=entry.citation.source_title or args.command,
        content=content, source_type=SourceType.VENDOR_DOCS,
        vendor=args.vendor, platform=args.platform or "",
        tags=["vendor_doc", "live_fetch"],
        extra={"source_url": entry.citation.source_url or ""},
    )
    r = layer.ingest(rec)
    if r.get("skipped"):
        print(f"Fetched but not re-ingested (unchanged) — version {r.get('version')}")
    else:
        print(f"Fetched from {entry.citation.source_url} and ingested — "
              f"version {r.get('version')}, {r.get('chunks')} chunk(s).")


def cmd_search(args):
    layer = get_knowledge_layer()
    source_types = _tags(args.source_types) or None
    hits = layer.search(
        args.query, top_k=args.k, source_types=source_types,
        vendor=args.vendor or None, platform=args.platform or None,
    )
    if not hits:
        print("(no hits)")
        return
    for h in hits:
        print(f"\n[{h.confidence:.2f} conf · {h.source_type} · v{h.version}] {h.title}")
        print("  " + h.text[:240].replace("\n", " "))


def cmd_stats(args):
    layer = get_knowledge_layer()
    m = layer.metrics()
    print("Enterprise Knowledge Layer:")
    for k, v in m.items():
        print(f"  {k}: {v}")


def main():
    ap = argparse.ArgumentParser(description="Network Compiler — universal knowledge ingestion.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    source_choices = [s.value for s in SourceType]

    p = sub.add_parser("ingest", help="ingest one file or a directory (any supported format)")
    p.add_argument("path")
    p.add_argument("--source-type", required=True, choices=source_choices)
    p.add_argument("--vendor"); p.add_argument("--platform"); p.add_argument("--tags")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("standard", help="ingest a conventional folder tree (vendor_docs/, rfcs/, ...)")
    p.add_argument("base_dir")
    p.set_defaults(func=cmd_standard)

    p = sub.add_parser("rfc", help="fetch + ingest an RFC by number")
    p.add_argument("number", type=int)
    p.set_defaults(func=cmd_rfc)

    p = sub.add_parser("vendor-doc", help="live-fetch a vendor doc for a command and persist it")
    p.add_argument("vendor")
    p.add_argument("command")
    p.add_argument("--platform")
    p.set_defaults(func=cmd_vendor_doc)

    p = sub.add_parser("search", help="hybrid semantic+keyword search over the knowledge base")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=5)
    p.add_argument("--source-types", help="comma-separated source type filter")
    p.add_argument("--vendor"); p.add_argument("--platform")
    p.set_defaults(func=cmd_search)

    sub.add_parser("stats", help="show knowledge base metrics").set_defaults(func=cmd_stats)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
