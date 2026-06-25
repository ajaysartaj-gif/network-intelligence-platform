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

logger = logging.getLogger("NetBrain.Knowledge.Pipelines")

_TEXT_EXTS = {".md", ".txt", ".rst", ".text", ".markdown", ".cfg", ".conf"}


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


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
    Ingest every text file under `path` as the given source type. Idempotent.
    """
    layer = layer or get_knowledge_layer()
    summary = {"source_type": source_type.value, "ingested": 0, "skipped": 0,
               "versions": {}, "errors": []}
    if not os.path.isdir(path):
        summary["errors"].append(f"not a directory: {path}")
        return summary

    walker = os.walk(path) if recursive else [(path, [], os.listdir(path))]
    for dirpath, _dirs, files in walker:
        for fn in files:
            if os.path.splitext(fn)[1].lower() not in _TEXT_EXTS:
                continue
            fpath = os.path.join(dirpath, fn)
            doc_id = os.path.relpath(fpath, path)
            try:
                rec = KnowledgeRecord(
                    doc_id=f"{source_type.value}:{doc_id}",
                    title=os.path.splitext(fn)[0],
                    content=_read(fpath),
                    source_type=source_type,
                    vendor=vendor, platform=platform, tags=tags or [],
                    extra={"path": doc_id},
                )
                r = layer.ingest(rec)
                if r.get("skipped"):
                    summary["skipped"] += 1
                else:
                    summary["ingested"] += 1
                    summary["versions"][rec.doc_id] = r.get("version")
            except Exception as exc:
                summary["errors"].append(f"{doc_id}: {exc}")
    return summary


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
        base_dir/vendor_docs/   -> VENDOR_DOCS
        base_dir/rfcs/          -> RFC
        base_dir/runbooks/      -> RUNBOOK
        base_dir/standards/     -> CONFIG_STANDARD
        base_dir/best_practices/-> BEST_PRACTICE
    Missing folders are simply skipped.
    """
    layer = layer or get_knowledge_layer()
    mapping = {
        "vendor_docs": SourceType.VENDOR_DOCS,
        "rfcs": SourceType.RFC,
        "runbooks": SourceType.RUNBOOK,
        "standards": SourceType.CONFIG_STANDARD,
        "best_practices": SourceType.BEST_PRACTICE,
    }
    out = {}
    for folder, stype in mapping.items():
        p = os.path.join(base_dir, folder)
        if os.path.isdir(p):
            out[folder] = ingest_directory(p, stype, layer=layer)
    return out
