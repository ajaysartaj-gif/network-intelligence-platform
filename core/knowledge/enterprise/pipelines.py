"""
core/knowledge/enterprise/pipelines.py
======================================
Automatic ingestion pipelines for the Enterprise Knowledge Layer.

Each pipeline knows how to turn a source location into typed KnowledgeRecords
and feed them through the layer (which versions + dedups them). Re-running a
pipeline is idempotent: unchanged files are skipped by content-hash dedup,
changed files create a new version.

Pipelines are intentionally simple/extensible — add a new source by writing a
small adapter that yields KnowledgeRecords with the right SourceType.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Iterable, List, Optional

from core.knowledge.enterprise.knowledge_layer import (
    EnterpriseKnowledgeLayer, KnowledgeRecord, SourceType, get_knowledge_layer,
)
from core.knowledge.parsers import extract_text, supported_extensions

logger = logging.getLogger("AI Net Studio.Knowledge.Pipelines")

_TEXT_EXTS = {".md", ".txt", ".rst", ".text", ".markdown", ".cfg", ".conf"}


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _read_any(path: str) -> Optional[str]:
    """Read a file as text directly if it's a plain-text format, otherwise
    dispatch to the parser package (PDF/DOCX/JSON/YAML/XML/CSV/HTML)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in _TEXT_EXTS:
        return _read(path)
    return extract_text(path)


def ingest_file(
    path: str,
    source_type: SourceType,
    vendor: str = "",
    platform: str = "",
    tags: Optional[List[str]] = None,
    layer: Optional[EnterpriseKnowledgeLayer] = None,
    doc_id: Optional[str] = None,
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Ingest a single file (any supported format) as the given source type.
    Returns the layer.ingest() summary, or {"skipped": True, "reason": ...}
    if the format is unsupported or the file is empty.
    """
    layer = layer or get_knowledge_layer()
    fn = os.path.basename(path)
    content = _read_any(path)
    if not content:
        return {"doc_id": doc_id or fn, "skipped": True,
                "reason": "unsupported format or empty content"}
    rec = KnowledgeRecord(
        doc_id=doc_id or f"{source_type.value}:{fn}",
        title=title or os.path.splitext(fn)[0],
        content=content,
        source_type=source_type,
        vendor=vendor, platform=platform, tags=tags or [],
        extra={"path": path},
    )
    return layer.ingest(rec)


def ingest_directory(
    path: str,
    source_type: SourceType,
    vendor: str = "",
    platform: str = "",
    tags: Optional[List[str]] = None,
    layer: Optional[EnterpriseKnowledgeLayer] = None,
    recursive: bool = True,
) -> Dict[str, Any]:
    """
    Ingest every supported file under `path` as the given source type
    (plain text read directly; PDF/DOCX/JSON/YAML/XML/CSV/HTML routed
    through core.knowledge.parsers). Idempotent.
    """
    layer = layer or get_knowledge_layer()
    summary = {"source_type": source_type.value, "ingested": 0, "skipped": 0,
               "versions": {}, "errors": []}
    if not os.path.isdir(path):
        summary["errors"].append(f"not a directory: {path}")
        return summary

    all_exts = _TEXT_EXTS | supported_extensions()
    walker = os.walk(path) if recursive else [(path, [], os.listdir(path))]
    for dirpath, _dirs, files in walker:
        for fn in files:
            if os.path.splitext(fn)[1].lower() not in all_exts:
                continue
            fpath = os.path.join(dirpath, fn)
            doc_id = os.path.relpath(fpath, path)
            try:
                r = ingest_file(
                    fpath, source_type, vendor=vendor, platform=platform,
                    tags=tags, layer=layer,
                    doc_id=f"{source_type.value}:{doc_id}",
                    title=os.path.splitext(fn)[0],
                )
                if r.get("skipped"):
                    summary["skipped"] += 1
                else:
                    summary["ingested"] += 1
                    summary["versions"][r.get("doc_id", doc_id)] = r.get("version")
            except Exception as exc:
                summary["errors"].append(f"{doc_id}: {exc}")
    return summary


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def ensure_general_corpus_ingested(layer: Optional[EnterpriseKnowledgeLayer] = None) -> Dict[str, Any]:
    """Idempotently ingests corpus/general/*.txt — real, researched prose
    coverage for technologies with no compiled protocol signatures (VXLAN/
    EVPN, multicast/PIM, QoS, MPLS L3VPN, EIGRP, VRRP, IPv6 ND/SLAAC, port
    security/802.1X) — into the SAME EnterpriseKnowledgeLayer core.
    knowledge.orchestrator.rag_query() reads from at query time.

    Before this function existed and was wired into IntentEngine.
    _rag_context_for(), this corpus sat on disk unused in production: only
    tests/test_general_corpus.py ever ingested it, into an isolated temp
    store nothing else could query — a live troubleshooting session could
    never actually be grounded in it, regardless of how good the content
    was.

    Safe to call on every request: ingest_directory()/layer.ingest() dedup
    by content hash, so re-ingesting unchanged files is a cheap no-op, the
    same "safe to call every time" contract core.troubleshooting.
    strategies.live_retriever.ensure_corpus_ingested() already relies on
    for the top-level corpus/ files."""
    corpus_dir = os.path.join(_REPO_ROOT, "corpus", "general")
    return ingest_directory(corpus_dir, SourceType.BEST_PRACTICE,
                            tags=["general-corpus"], layer=layer, recursive=False)


# Doc-type folder name -> SourceType, mirroring core.knowledge.doc_downloader.
# classify.DOC_TYPES. Kept here rather than imported to avoid this leaf
# module depending on doc_downloader (which itself doesn't touch the RAG
# layer at all — the two packages are deliberately independent; this is
# the one bridge between them).
_PDF_DOWNLOADS_SOURCE_TYPE = {
    "white_paper": SourceType.WHITEPAPER,
    "configuration": SourceType.VENDOR_DOCS,
    "troubleshooting": SourceType.VENDOR_DOCS,
    "data_sheet": SourceType.VENDOR_DOCS,
    "command_reference": SourceType.VENDOR_DOCS,
}


def ensure_pdf_downloads_ingested(layer: Optional[EnterpriseKnowledgeLayer] = None) -> Dict[str, Any]:
    """Idempotently ingests pdf_downloads/ (core.knowledge.doc_downloader's
    real, live-verified Cisco/Versa/Fortinet/Palo Alto/RFC corpus — 77
    documents at the time this was wired in) into the SAME
    EnterpriseKnowledgeLayer core.knowledge.orchestrator.rag_query() reads
    from at query time.

    Exactly the same gap ensure_general_corpus_ingested() closed for
    corpus/general/*.txt: before this function existed, pdf_downloads/ was
    real content sitting on disk with nothing ever ingesting it into the
    store a live troubleshooting session actually queries — grep confirms
    zero references to "pdf_downloads" anywhere outside
    core/knowledge/doc_downloader/ itself. Downloading real vendor
    documents is only half the job; this is the other half.

    Ingests per <vendor>/<doc_type>/ subfolder (not the whole tree in one
    call) so each folder gets the SourceType its content actually is
    (white_paper/ -> WHITEPAPER, everything else -> VENDOR_DOCS, rfc/ ->
    RFC) and the correct `vendor` tag — ingest_directory() only accepts one
    SourceType/vendor per call. Safe to call on every request: same
    content-hash dedup contract as ensure_general_corpus_ingested() and
    core.troubleshooting.strategies.live_retriever.ensure_corpus_ingested()."""
    layer = layer or get_knowledge_layer()
    root = os.path.join(_REPO_ROOT, "pdf_downloads")
    summary = {"ingested": 0, "skipped": 0, "errors": []}
    if not os.path.isdir(root):
        return summary

    for vendor in sorted(os.listdir(root)):
        vendor_dir = os.path.join(root, vendor)
        if not os.path.isdir(vendor_dir):
            continue
        if vendor == "rfc":
            r = ingest_directory(vendor_dir, SourceType.RFC,
                                 tags=["pdf_downloads", "rfc"], layer=layer, recursive=False)
            summary["ingested"] += r["ingested"]
            summary["skipped"] += r["skipped"]
            summary["errors"].extend(r["errors"])
            continue
        for doc_type, source_type in _PDF_DOWNLOADS_SOURCE_TYPE.items():
            doc_type_dir = os.path.join(vendor_dir, doc_type)
            if not os.path.isdir(doc_type_dir):
                continue
            r = ingest_directory(doc_type_dir, source_type, vendor=vendor,
                                 tags=["pdf_downloads", vendor, doc_type],
                                 layer=layer, recursive=False)
            summary["ingested"] += r["ingested"]
            summary["skipped"] += r["skipped"]
            summary["errors"].extend(r["errors"])
    return summary


def ingest_rfc(
    number: int,
    layer: Optional[EnterpriseKnowledgeLayer] = None,
) -> Dict[str, Any]:
    """Fetch an RFC by number from rfc-editor.org and ingest it as SourceType.RFC."""
    from core.knowledge.fetchers.rfc_fetcher import fetch_rfc_text

    layer = layer or get_knowledge_layer()
    fetched = fetch_rfc_text(number)
    if not fetched:
        return {"doc_id": f"rfc:{number}", "skipped": True,
                "reason": "fetch failed or RFC not found"}
    rec = KnowledgeRecord(
        doc_id=f"rfc:{number}",
        title=fetched["title"],
        content=fetched["content"],
        source_type=SourceType.RFC,
        tags=["rfc"],
        extra={"rfc_number": number},
    )
    return layer.ingest(rec)


def fetch_and_ingest_vendor_doc(
    vendor: str,
    command: str,
    platform: str = "",
    layer: Optional[EnterpriseKnowledgeLayer] = None,
) -> Dict[str, Any]:
    """
    Live-fetches a vendor doc for `command` (core.knowledge.vendor_router's
    per-vendor fetchers) and ingests the result as SourceType.VENDOR_DOCS.
    This is the ONE implementation shared by network_compiler.py's
    `vendor-doc` CLI command and the supply-chain facade's
    fetch_vendor_updates() — extracted here so neither duplicates it.
    """
    from core.knowledge.vendor_router import get_fetcher

    layer = layer or get_knowledge_layer()
    fetcher = get_fetcher(vendor)
    if not fetcher:
        return {"skipped": True, "reason": f"no fetcher registered for vendor '{vendor}'"}
    entry = fetcher.fetch(command, platform)
    if not entry:
        return {"skipped": True, "reason": f"no live doc found for '{command}' ({vendor})"}

    doc_id = f"vendor_docs:{vendor}:{command}"
    content = f"{entry.description}\n\nSyntax:\n{entry.syntax}".strip()
    rec = KnowledgeRecord(
        doc_id=doc_id, title=entry.citation.source_title or command,
        content=content, source_type=SourceType.VENDOR_DOCS,
        vendor=vendor, platform=platform, tags=["vendor_doc", "live_fetch"],
        extra={"source_url": entry.citation.source_url or ""},
    )
    return layer.ingest(rec)


def archive_source(doc_id: str, layer: Optional[EnterpriseKnowledgeLayer] = None) -> bool:
    """
    Marks every chunk of `doc_id` (all versions) as archived — retired from
    active use without being deleted, so it remains available as historical
    evidence (per Level 1's "never modify the original source" rule).
    Reuses the exact "rebuild clean primitive metadata" technique
    EnterpriseKnowledgeLayer.ingest() already uses for `superseded` (Chroma
    silently drops non-primitive metadata values on write, so this is not a
    new technique, just the same one applied to a new flag).
    """
    layer = layer or get_knowledge_layer()
    col = layer._col()
    existing = col.get(where={"doc_id": doc_id}, include=["metadatas"])
    ids = existing.get("ids", []) or []
    metas = existing.get("metadatas", []) or []
    if not ids:
        return False
    fixed = []
    for mm in metas:
        nm = {k: v for k, v in (mm or {}).items() if isinstance(v, (str, int, float, bool))}
        nm["archived"] = True
        fixed.append(nm)
    col.update(ids=ids, metadatas=fixed)
    return True


def ingest_remediation(
    remediation_id: str,
    intent: str,
    commands: List[str],
    outcome: str,
    vendor: str = "",
    platform: str = "",
    layer: Optional[EnterpriseKnowledgeLayer] = None,
) -> Dict[str, Any]:
    """
    Record a PREVIOUS SUCCESSFUL remediation as reusable knowledge. This is the
    bridge for Continuous Learning: a verified outcome contract becomes a
    'remediation' knowledge record that future similar intents can retrieve.
    """
    layer = layer or get_knowledge_layer()
    content = (
        f"Intent: {intent}\n\n"
        f"Commands applied:\n" + "\n".join(commands) + "\n\n"
        f"Verified outcome:\n{outcome}"
    )
    rec = KnowledgeRecord(
        doc_id=f"remediation:{remediation_id}",
        title=f"Successful remediation: {intent[:80]}",
        content=content,
        source_type=SourceType.REMEDIATION,
        vendor=vendor, platform=platform,
        tags=["remediation", "verified"],
    )
    return layer.ingest(rec)


def ingest_incident_report(
    incident_id: str, symptom: str, resolution: str,
    vendor: str = "", platform: str = "",
    layer: Optional[EnterpriseKnowledgeLayer] = None,
) -> Dict[str, Any]:
    layer = layer or get_knowledge_layer()
    rec = KnowledgeRecord(
        doc_id=f"incident:{incident_id}",
        title=f"Incident: {symptom[:80]}",
        content=f"Symptom:\n{symptom}\n\nResolution:\n{resolution}",
        source_type=SourceType.INCIDENT,
        vendor=vendor, platform=platform, tags=["incident"],
    )
    return layer.ingest(rec)


# Convenience: map a source folder layout to pipelines in one call.
def run_standard_pipelines(
    base_dir: str, layer: Optional[EnterpriseKnowledgeLayer] = None,
) -> Dict[str, Any]:
    """
    Ingest a conventional knowledge tree:
        base_dir/vendor_docs/    -> VENDOR_DOCS
        base_dir/rfcs/           -> RFC (local RFC text files; use ingest_rfc()
                                    to fetch by number instead)
        base_dir/runbooks/       -> RUNBOOK
        base_dir/standards/      -> CONFIG_STANDARD
        base_dir/best_practices/ -> BEST_PRACTICE
        base_dir/release_notes/  -> RELEASE_NOTES
        base_dir/bug_reports/    -> BUG_REPORT (TAC cases / bug DB exports)
        base_dir/design_guides/  -> DESIGN_GUIDE
        base_dir/whitepapers/    -> WHITEPAPER
        base_dir/golden_configs/ -> GOLDEN_CONFIG
        base_dir/yang_models/    -> YANG_MODEL
        base_dir/customer_docs/  -> CUSTOMER_DOC
        base_dir/wikis/          -> INTERNAL_WIKI
    Missing folders are simply skipped.
    """
    layer = layer or get_knowledge_layer()
    mapping = {
        "vendor_docs": SourceType.VENDOR_DOCS,
        "rfcs": SourceType.RFC,
        "runbooks": SourceType.RUNBOOK,
        "standards": SourceType.CONFIG_STANDARD,
        "best_practices": SourceType.BEST_PRACTICE,
        "release_notes": SourceType.RELEASE_NOTES,
        "bug_reports": SourceType.BUG_REPORT,
        "design_guides": SourceType.DESIGN_GUIDE,
        "whitepapers": SourceType.WHITEPAPER,
        "golden_configs": SourceType.GOLDEN_CONFIG,
        "yang_models": SourceType.YANG_MODEL,
        "customer_docs": SourceType.CUSTOMER_DOC,
        "wikis": SourceType.INTERNAL_WIKI,
    }
    out = {}
    for folder, stype in mapping.items():
        p = os.path.join(base_dir, folder)
        if os.path.isdir(p):
            out[folder] = ingest_directory(p, stype, layer=layer)
    return out
