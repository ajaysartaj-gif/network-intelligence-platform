"""
core/knowledge/compiler/compiler.py
======================================
SemanticCompiler — orchestrates the pipeline (lexer -> AST -> semantic
analysis -> canonicalization -> relationship derivation -> validation) and
publishes the result into the EXISTING core.knowledge_graph.KnowledgeGraph.
No new logic beyond sequencing + publish lives in this file; every stage is
implemented in its own module and reused as-is (see this package's
__init__.py docstring for the pipeline diagram).

The compiled graph is a dedicated singleton (get_compiled_graph()), kept
distinct from core.topology.knowledge_graph_bridge's per-site topology
graphs, per docs/nkc_architecture_blueprint.md's "family of typed graphs"
principle (also core.reasoning_blueprint.md Axiom 4): document-derived
compiled knowledge and live-discovered physical topology are different
graphs with different lifecycles, not one graph.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.knowledge.compiler import graph_ops
from core.knowledge.compiler.ast_builder import build_ast
from core.knowledge.compiler.canonicalizer import COMPILER_VERSION, finding_to_object
from core.knowledge.compiler.identity import merge_duplicate_objects
from core.knowledge.compiler.relationships import derive_relationships
from core.knowledge.compiler.semantic_analyzer import analyze, analyze_structured
from core.knowledge.compiler.validation import (
    Issue, validate_graph as _validate_graph, validate_objects, validate_relationships,
)
from core.knowledge.parsers import extract_text as parser_extract_text, supported_extensions
from core.knowledge_graph import GraphRelationship, KnowledgeGraph
from core.vendor.models import NormalizedObject

logger = logging.getLogger("AI Net Studio.Knowledge.Compiler")

_TEXT_EXTS = {".md", ".txt", ".rst", ".text", ".markdown", ".cfg", ".conf", ".log"}
_STRUCTURED_EXTS = {".json", ".yaml", ".yml", ".xml"}


@dataclass
class CompilationReport:
    source_doc_id: str
    objects: List[NormalizedObject] = field(default_factory=list)
    relationships: List[GraphRelationship] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    skipped: bool = False
    reason: str = ""

    def summary(self) -> str:
        if self.skipped:
            return f"{self.source_doc_id}: skipped ({self.reason})"
        errs = sum(1 for i in self.issues if i.severity == "error")
        return (f"{self.source_doc_id}: {len(self.objects)} object(s), "
                f"{len(self.relationships)} relationship(s), "
                f"{len(self.issues)} issue(s) ({errs} error-level)")


def _content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


def _read_text_or_structured(path: str):
    """Returns (kind, payload): kind='text' -> str, kind='structured' -> parsed
    dict/list. Reuses core.knowledge.parsers for binary/markup formats and
    plain read for text formats — the same dispatch shape as
    core.knowledge.enterprise.pipelines._read_any, kept local here since a
    structured *tree* (not the flattened text that pipeline produces) is
    what the Semantic Compiler needs."""
    ext = os.path.splitext(path)[1].lower()
    if ext in _STRUCTURED_EXTS:
        try:
            if ext == ".json":
                import json
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return "structured", json.load(f)
            if ext in (".yaml", ".yml"):
                import yaml
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return "structured", yaml.safe_load(f)
            if ext == ".xml":
                import xml.etree.ElementTree as ET
                from core.knowledge.parsers.structured_parser import _elem_to_dict
                tree = ET.parse(path)
                root = tree.getroot()
                return "structured", {root.tag: _elem_to_dict(root)}
        except Exception as exc:
            logger.warning(f"Failed to load structured data from {path}: {exc}")
            return "structured", None
    if ext in _TEXT_EXTS:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return "text", f.read()
    # PDF/DOCX/CSV/HTML — already-flattened text via the parser package.
    return "text", parser_extract_text(path)


# ── singleton compiled-knowledge graph ───────────────────────────────────
_compiled_graph: Optional[KnowledgeGraph] = None


def get_compiled_graph() -> KnowledgeGraph:
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = KnowledgeGraph()
    return _compiled_graph


class SemanticCompiler:
    """The Semantic Compiler. One instance accumulates compiled knowledge
    into its `graph` across calls, and tracks per-source content hashes for
    compile_incremental()."""

    def __init__(self, graph: Optional[KnowledgeGraph] = None):
        self.graph = graph if graph is not None else get_compiled_graph()
        self._last_hash: Dict[str, str] = {}
        self._last_export: Dict[str, Dict[str, Any]] = {}   # per-doc snapshot, for compile_incremental's delta

    # ── entry points ──────────────────────────────────────────────────────

    def compile_cli(self, text: str, *, device: str, vendor: str = "",
                     source_doc_id: Optional[str] = None) -> CompilationReport:
        doc_id = source_doc_id or f"cli:{device}:{_content_hash(text)[:12]}"
        return self._compile_text(text, device=device, vendor=vendor, source_doc_id=doc_id)

    def compile_configuration(self, text: str, *, device: str, vendor: str = "",
                               source_doc_id: Optional[str] = None) -> CompilationReport:
        """Same pipeline as compile_cli — kept as a distinct entry point
        because config text and show-output are different CALLER intents,
        not different pipelines (both are line-oriented text the lexer/AST
        handle identically)."""
        doc_id = source_doc_id or f"config:{device}:{_content_hash(text)[:12]}"
        return self._compile_text(text, device=device, vendor=vendor, source_doc_id=doc_id)

    def compile_document(self, path: str, *, device: str = "", vendor: str = "",
                          source_doc_id: Optional[str] = None) -> CompilationReport:
        doc_id = source_doc_id or path
        kind, payload = _read_text_or_structured(path)
        if payload is None:
            return CompilationReport(source_doc_id=doc_id, issues=[
                Issue(severity="error", code="unreadable",
                      message=f"Could not extract text/data from {path}")])
        if kind == "structured":
            return self._compile_structured(payload, device=device, vendor=vendor,
                                            source_doc_id=doc_id,
                                            source_format=os.path.splitext(path)[1].lstrip("."))
        return self._compile_text(payload, device=device, vendor=vendor, source_doc_id=doc_id)

    def compile_protocol(self, text: str, protocol: str, *, device: str,
                          vendor: str = "") -> CompilationReport:
        """Runs the normal pipeline, then filters the report to objects and
        relationships that concern the given protocol (protocol stanzas
        matching it, plus any neighbor/timer objects linked to them)."""
        report = self.compile_cli(text, device=device, vendor=vendor,
                                  source_doc_id=f"protocol:{protocol}:{device}:{_content_hash(text)[:12]}")
        proto_ids = {o.id for o in report.objects
                    if o.type == "protocol" and o.get("protocol") == protocol.lower()}
        linked_ids = set(proto_ids)
        for rel in report.relationships:
            if rel.source in proto_ids:
                linked_ids.add(rel.target)
            if rel.target in proto_ids:
                linked_ids.add(rel.source)
        report.objects = [o for o in report.objects if o.id in linked_ids]
        report.relationships = [r for r in report.relationships
                                if r.source in linked_ids and r.target in linked_ids]
        report.stats["filtered_to_protocol"] = protocol
        return report

    def compile_directory(self, path: str, *, vendor: str = "") -> CompilationReport:
        """Aggregate compile over every supported file under `path`. A
        single file's failure is collected as a stat, not fatal to the
        batch — same resilience convention as
        core.knowledge.enterprise.pipelines.ingest_directory."""
        all_exts = _TEXT_EXTS | _STRUCTURED_EXTS | supported_extensions()
        agg = CompilationReport(source_doc_id=f"directory:{path}")
        errors: List[str] = []
        files_compiled = 0
        if not os.path.isdir(path):
            agg.issues.append(Issue(severity="error", code="not_a_directory",
                                    message=f"{path} is not a directory"))
            return agg

        for dirpath, _dirs, files in os.walk(path):
            for fn in files:
                if os.path.splitext(fn)[1].lower() not in all_exts:
                    continue
                fpath = os.path.join(dirpath, fn)
                try:
                    r = self.compile_document(fpath)
                    agg.objects.extend(r.objects)
                    agg.relationships.extend(r.relationships)
                    agg.issues.extend(r.issues)
                    files_compiled += 1
                except Exception as exc:
                    errors.append(f"{fpath}: {exc}")

        agg.stats = {"files_compiled": files_compiled, "errors": errors,
                    "objects": len(agg.objects), "relationships": len(agg.relationships),
                    "issues": len(agg.issues)}
        return agg

    def compile_incremental(self, path: str, *, vendor: str = "") -> CompilationReport:
        """Skips recompilation if the file's content hash matches the last
        compile of this path (blueprint Part 11 incremental-compilation
        gate — a hash check in front of the existing pipeline, not a new
        build system). When the file DID change, additionally diffs this
        doc's compiled objects/relationships against its own last compile
        (graph_ops.diff_graph over per-doc snapshots) and attaches the
        result as report.stats["delta"] — reporting exactly what changed,
        even though publish already only ever touches this run's objects,
        never the whole graph."""
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError as exc:
            return CompilationReport(source_doc_id=path, issues=[
                Issue(severity="error", code="unreadable", message=str(exc))])

        h = hashlib.sha256(raw).hexdigest()
        if self._last_hash.get(path) == h:
            return CompilationReport(source_doc_id=path, skipped=True,
                                     reason="unchanged since last compile")

        report = self.compile_document(path, vendor=vendor)
        self._last_hash[path] = h

        current_snapshot = {
            "nodes": [{"node_id": o.id, "label": o.type, "attributes": o.attributes}
                     for o in report.objects],
            "relationships": [{"source": r.source, "target": r.target,
                              "relationship_type": r.relationship_type}
                             for r in report.relationships],
        }
        previous_snapshot = self._last_export.get(path, {"nodes": [], "relationships": []})
        report.stats["delta"] = graph_ops.diff_graph(previous_snapshot, current_snapshot)
        self._last_export[path] = current_snapshot
        return report

    def validate(self, report: CompilationReport) -> List[Issue]:
        """Re-run validation only, without recompiling."""
        return (validate_objects(report.objects) +
                validate_relationships(report.objects, report.relationships))

    # ── Graph API surface (Knowledge Graph Compiler stage) ────────────────

    def compile_graph(self, objects: List[NormalizedObject],
                      relationships: Optional[List[GraphRelationship]] = None,
                      *, source_doc_id: str = "external") -> CompilationReport:
        """Compile from an ALREADY-canonicalized object list, bypassing
        lexer/AST/semantic-analysis — for callers that have NormalizedObjects
        from elsewhere. Relationships are derived automatically if not
        supplied. Runs the same merge/validate/publish tail as every other
        compile_* entry point."""
        return self._finish_from_objects(objects, relationships, source_doc_id=source_doc_id)

    def validate_graph(self) -> List[Issue]:
        """Graph-level validation over the live graph: orphan nodes,
        dependency cycles, duplicate relationships, broken references."""
        return _validate_graph(self.graph)

    def optimize_graph(self) -> Dict[str, int]:
        """De-duplicates relationships already in the live graph."""
        return graph_ops.optimize_graph(self.graph)

    def diff_graph(self, before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
        """Compares two export_graph()-shaped snapshots."""
        return graph_ops.diff_graph(before, after)

    def export_graph(self) -> Dict[str, Any]:
        """JSON-serializable snapshot of the live graph."""
        return graph_ops.export_graph(self.graph)

    def import_graph(self, data: Dict[str, Any]) -> None:
        """Replaces self.graph with one rebuilt from an export_graph()-shaped
        snapshot."""
        self.graph = graph_ops.import_graph(data)

    def merge_graph(self, other: KnowledgeGraph) -> None:
        """Merges another KnowledgeGraph into self.graph (nodes merged via
        identity.merge_attributes on id collision, relationships deduped)."""
        self.graph = graph_ops.merge_two_graphs(self.graph, other)

    # ── internal pipeline ─────────────────────────────────────────────────

    def _compile_text(self, text: str, *, device: str, vendor: str,
                      source_doc_id: str) -> CompilationReport:
        ast = build_ast(text or "")
        findings = analyze(ast)
        return self._finish(findings, device=device, vendor=vendor, source_doc_id=source_doc_id)

    def _compile_structured(self, data: Any, *, device: str, vendor: str,
                            source_doc_id: str, source_format: str) -> CompilationReport:
        findings = analyze_structured(data, source_format=source_format)
        return self._finish(findings, device=device, vendor=vendor, source_doc_id=source_doc_id)

    def _finish(self, findings, *, device: str, vendor: str,
               source_doc_id: str) -> CompilationReport:
        objects: List[NormalizedObject] = []
        for f in findings:
            obj = finding_to_object(f, device=device, source_doc_id=source_doc_id, vendor=vendor)
            if obj is not None:
                objects.append(obj)
        report = self._finish_from_objects(objects, None, source_doc_id=source_doc_id)
        report.stats["findings"] = len(findings)
        return report

    def _finish_from_objects(self, objects: List[NormalizedObject],
                             relationships: Optional[List[GraphRelationship]],
                             *, source_doc_id: str) -> CompilationReport:
        # Within-batch identity resolution: two findings that normalized to
        # the SAME object id (e.g. "Gi0/1" and "GigabitEthernet0/1" for the
        # same interface) merge into one object here, before relationship
        # derivation/validation ever sees them as two — this is what makes
        # identity resolution actually prevent false conflicts rather than
        # just reporting them after the fact.
        objects, merge_issues = merge_duplicate_objects(objects)

        if relationships is None:
            relationships = derive_relationships(objects)

        issues = merge_issues + validate_objects(objects) + validate_relationships(objects, relationships)
        published_objects, published_rels, publish_issues = self._publish(objects, relationships, issues)
        issues = issues + publish_issues

        return CompilationReport(
            source_doc_id=source_doc_id, objects=published_objects,
            relationships=published_rels, issues=issues,
            stats={"objects": len(published_objects), "relationships": len(published_rels),
                  "issues": len(issues), "compiler_version": COMPILER_VERSION})

    def _publish(self, objects: List[NormalizedObject], relationships: List[GraphRelationship],
                issues: List[Issue]):
        """Writes into self.graph (core.knowledge_graph.KnowledgeGraph) via
        graph_ops.merge_into_graph — an object whose id already exists in
        the graph (from a PRIOR compile) is MERGED, not overwritten.
        Objects with an error-level issue (missing field / conflict) are
        excluded from publish but retained in the report so nothing is
        silently dropped without being visible to the caller."""
        bad_ids = {i.object_id for i in issues
                  if i.severity == "error" and i.code in ("missing_field", "conflict")}

        publishable = [o for o in objects if o.id not in bad_ids]
        published, publish_issues = graph_ops.merge_into_graph(self.graph, publishable)

        published_rels: List[GraphRelationship] = []
        for rel in relationships:
            if rel.source in self.graph.nodes and rel.target in self.graph.nodes:
                try:
                    self.graph.add_relationship(rel.source, rel.target, rel.relationship_type,
                                                rel.weight, rel.metadata)
                    published_rels.append(rel)
                except ValueError as exc:
                    logger.warning(f"Skipped relationship {rel.source}->{rel.target}: {exc}")

        return published, published_rels, publish_issues
