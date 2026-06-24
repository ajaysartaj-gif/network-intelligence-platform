#!/usr/bin/env python3
"""
rag_ingest.py — load knowledge into NetBrain's RAG store
========================================================
Real RAG only helps once knowledge is ingested. This CLI loads the two
source types (phased rollout):

  1) Documents / runbooks / design guides  (start here)
  2) Past incidents: symptom -> resolution (add as you accumulate them)

Examples
--------
  # Ingest every .md/.txt under a folder as runbooks (recursively):
  python3 rag_ingest.py docs ./runbooks --vendor cisco

  # Ingest a single document:
  python3 rag_ingest.py doc ./design/ospf_standard.md --vendor cisco --platform ios

  # Record one past incident (symptom + resolution):
  python3 rag_ingest.py incident \
      --id inc-204 \
      --symptom "OSPF neighbors stuck in EXSTART after MTU change" \
      --resolution "MTU mismatch on Gi0/1; set both sides to 1500, adjacency formed" \
      --vendor cisco

  # Show what's in the store:
  python3 rag_ingest.py stats

  # Wipe the store (start over):
  python3 rag_ingest.py reset

Notes
-----
* First run downloads the local embedding model (~130MB) from Hugging Face;
  subsequent runs are offline.
* Re-ingesting the same doc id / file path refreshes it (no duplication).
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.knowledge.rag import get_rag_engine

_TEXT_EXTS = {".md", ".txt", ".rst", ".text", ".markdown"}


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def cmd_doc(args):
    eng = get_rag_engine()
    doc_id = args.id or os.path.relpath(args.path)
    title = args.title or os.path.splitext(os.path.basename(args.path))[0]
    n = eng.ingest_document(
        doc_id=doc_id, title=title, content=_read(args.path),
        vendor=args.vendor or "", platform=args.platform or "", source="runbook",
    )
    print(f"Ingested '{doc_id}' as runbook — {n} chunk(s). Store now has {eng.count()}.")


def cmd_docs(args):
    eng = get_rag_engine()
    root = args.path
    if not os.path.isdir(root):
        print(f"Not a directory: {root}")
        return
    total_files = total_chunks = 0
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if os.path.splitext(fn)[1].lower() not in _TEXT_EXTS:
                continue
            fpath = os.path.join(dirpath, fn)
            doc_id = os.path.relpath(fpath, root)
            title = os.path.splitext(fn)[0]
            try:
                n = eng.ingest_document(
                    doc_id=doc_id, title=title, content=_read(fpath),
                    vendor=args.vendor or "", platform=args.platform or "",
                    source="runbook",
                )
                total_files += 1
                total_chunks += n
                print(f"  + {doc_id} ({n} chunk(s))")
            except Exception as exc:
                print(f"  ! {doc_id} failed: {exc}")
    print(f"\nIngested {total_files} file(s), {total_chunks} chunk(s). "
          f"Store now has {eng.count()}.")


def cmd_incident(args):
    eng = get_rag_engine()
    n = eng.ingest_incident(
        incident_id=args.id, symptom=args.symptom, resolution=args.resolution,
        vendor=args.vendor or "", platform=args.platform or "",
    )
    print(f"Recorded incident '{args.id}' — {n} chunk(s). Store now has {eng.count()}.")


def cmd_stats(args):
    eng = get_rag_engine()
    s = eng.stats()
    print("RAG store:")
    for k, v in s.items():
        print(f"  {k}: {v}")


def cmd_reset(args):
    eng = get_rag_engine()
    eng.reset()
    print("RAG store cleared.")


def cmd_search(args):
    eng = get_rag_engine()
    hits = eng.search(args.query, top_k=args.k, min_score=0.0,
                      vendor=args.vendor or None)
    if not hits:
        print("(no hits)")
        return
    for h in hits:
        print(f"\n[{h.score:.3f}] {h.source} · {h.title}")
        print("  " + h.text[:240].replace("\n", " "))


def main():
    ap = argparse.ArgumentParser(description="Load knowledge into NetBrain RAG.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doc", help="ingest one document/runbook file")
    p.add_argument("path")
    p.add_argument("--id"); p.add_argument("--title")
    p.add_argument("--vendor"); p.add_argument("--platform")
    p.set_defaults(func=cmd_doc)

    p = sub.add_parser("docs", help="ingest a directory of .md/.txt as runbooks")
    p.add_argument("path")
    p.add_argument("--vendor"); p.add_argument("--platform")
    p.set_defaults(func=cmd_docs)

    p = sub.add_parser("incident", help="record a past incident (symptom->resolution)")
    p.add_argument("--id", required=True)
    p.add_argument("--symptom", required=True)
    p.add_argument("--resolution", required=True)
    p.add_argument("--vendor"); p.add_argument("--platform")
    p.set_defaults(func=cmd_incident)

    p = sub.add_parser("search", help="test a query against the store")
    p.add_argument("query"); p.add_argument("-k", type=int, default=5)
    p.add_argument("--vendor")
    p.set_defaults(func=cmd_search)

    sub.add_parser("stats", help="show store stats").set_defaults(func=cmd_stats)
    sub.add_parser("reset", help="wipe the store").set_defaults(func=cmd_reset)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
