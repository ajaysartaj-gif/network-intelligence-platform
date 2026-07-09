"""
core/knowledge/compiler/cross_document_compiler.py
======================================================
CrossDocumentCompiler — the orchestrator for NKC Phase 3. Turns the
EnterpriseKnowledgeLayer's ingested reference corpus (RFCs, vendor docs,
release notes, KB articles, runbooks — all typed sources from
core/knowledge/enterprise/, built in an earlier session) into Facts,
correlates/validates/resolves conflicts among them, and cross-checks
already-compiled device objects (Phase 1/2's SemanticCompiler output,
living in the shared KnowledgeGraph) against each other.

Every method here is a thin composition of an existing module — this file
introduces no new extraction/scoring/graph logic of its own beyond
sequencing, same discipline as core/knowledge/compiler/compiler.py.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from core.knowledge.compiler import fact_conflicts, graph_ops, protocol_models
from core.knowledge.compiler.facts import Fact, extract_facts_from_text, fact_to_object
from core.knowledge.compiler.fact_conflicts import ConflictRecord
from core.knowledge.compiler.protocol_models import ProtocolStateModel
from core.knowledge.compiler.validation import Issue
from core.knowledge.enterprise.knowledge_layer import EnterpriseKnowledgeLayer, get_knowledge_layer
from core.knowledge_graph import KnowledgeGraph

# Reuses the SAME compiled-graph singleton Phase 1/2's SemanticCompiler
# publishes device objects into, so reference Facts and device objects can
# eventually cross-link (e.g. via the already-defined but unused
# RelationType.VALIDATED_BY) — a future integration point, not built here.
from core.knowledge.compiler.compiler import get_compiled_graph


class CrossDocumentCompiler:
    def __init__(self, layer: Optional[EnterpriseKnowledgeLayer] = None,
                graph: Optional[KnowledgeGraph] = None):
        self.layer = layer if layer is not None else get_knowledge_layer()
        self.graph = graph if graph is not None else get_compiled_graph()
        # subject::predicate -> chronological list of (timestamp, facts-at-that-time)
        self._history: Dict[str, List[Tuple[float, List[Fact]]]] = {}

    # ── Fact Compiler entry point ─────────────────────────────────────────

    def compile_facts(self, subject_query: str, *, predicate: Optional[str] = None,
                      source_types: Optional[List[str]] = None, top_k: int = 10) -> List[Fact]:
        """Searches the EXISTING EnterpriseKnowledgeLayer (hybrid RRF,
        already built) for chunks about `subject_query`, and runs
        deterministic default-value extraction over each hit's text."""
        hits = self.layer.search(subject_query, top_k=top_k, source_types=source_types)
        facts: List[Fact] = []
        for hit in hits:
            extracted = extract_facts_from_text(
                hit.text, source_doc_id=hit.doc_id, vendor=hit.vendor,
                source_type=hit.source_type, confidence=hit.confidence)
            facts.extend(extracted)

        if predicate:
            facts = [f for f in facts if f.predicate == predicate]

        key = subject_query.strip().lower()
        self._history.setdefault(key, []).append((time.time(), facts))
        return facts

    # ── Validation / Conflict Detection & Resolution ─────────────────────

    def validate_facts(self, facts: List[Fact]) -> List[Issue]:
        """Flags facts missing a subject/predicate/source — reuses
        validation.py's Issue shape, not a parallel one."""
        issues: List[Issue] = []
        for f in facts:
            if not f.subject or not f.predicate:
                issues.append(Issue(severity="error", code="missing_field",
                                    message="Fact is missing subject/predicate", object_id=f.key))
            if not f.source_doc_id:
                issues.append(Issue(severity="warning", code="no_citation",
                                    message=f"Fact '{f.key}' has no source_doc_id", object_id=f.key))
        return issues

    def resolve_conflicts(self, facts: List[Fact]) -> List[ConflictRecord]:
        return fact_conflicts.detect_fact_conflicts(facts)

    def detect_cross_device_conflicts(self) -> List[ConflictRecord]:
        return fact_conflicts.detect_cross_device_conflicts(self.graph)

    # ── Correlation / Evidence ─────────────────────────────────────────────

    def correlate_documents(self, subject: str) -> Dict[str, List[Fact]]:
        """What does each document/vendor say about `subject`? Groups
        compile_facts()'s results by vendor (falling back to source_doc_id
        when vendor is unset)."""
        facts = self.compile_facts(subject)
        grouped: Dict[str, List[Fact]] = {}
        for f in facts:
            key = f.vendor or f.source_doc_id or "unknown"
            grouped.setdefault(key, []).append(f)
        return grouped

    def merge_evidence(self, facts: List[Fact]) -> Dict[str, List[Fact]]:
        """Groups facts by (subject, predicate) regardless of agreement —
        the raw evidence pool conflict/confidence calculations draw from.
        Never discards a fact."""
        grouped: Dict[str, List[Fact]] = {}
        for f in facts:
            grouped.setdefault(f.key, []).append(f)
        return grouped

    # ── Protocol models ────────────────────────────────────────────────────

    def build_protocol_model(self, protocol: str) -> Optional[ProtocolStateModel]:
        return protocol_models.build_protocol_model(protocol)

    # ── Optimization / Publishing ──────────────────────────────────────────

    def optimize_knowledge(self, facts: List[Fact]) -> List[Fact]:
        """Dedups facts identical on (subject, predicate, object,
        source_doc_id) — the fact-level analogue of
        graph_ops.optimize_graph's edge dedup."""
        seen = set()
        out: List[Fact] = []
        for f in facts:
            key = (f.subject, f.predicate, f.object.strip().lower(), f.source_doc_id)
            if key in seen:
                continue
            seen.add(key)
            out.append(f)
        return out

    def publish_facts(self, facts: List[Fact]) -> List[str]:
        """Converts Facts to NormalizedObjects (facts.fact_to_object) and
        publishes via Phase 2's graph_ops.merge_into_graph, reused
        unchanged."""
        objects = [fact_to_object(f) for f in facts]
        published, _issues = graph_ops.merge_into_graph(self.graph, objects)
        return [o.id for o in published]

    # ── Historical knowledge ───────────────────────────────────────────────

    def compare_versions(self, subject: str) -> Dict[str, Any]:
        """Diffs the OLDEST vs. NEWEST recorded compile_facts() call for
        this subject (in-memory history, same shape as Phase 2's
        _last_export snapshot tracking — no new persistence layer)."""
        key = subject.strip().lower()
        history = self._history.get(key, [])
        if len(history) < 2:
            return {"error": "not enough history recorded for this subject yet"}

        _, oldest_facts = history[0]
        _, newest_facts = history[-1]
        oldest_values = {f.key: f.object for f in oldest_facts}
        newest_values = {f.key: f.object for f in newest_facts}

        added = [k for k in newest_values if k not in oldest_values]
        removed = [k for k in oldest_values if k not in newest_values]
        changed = [k for k in newest_values
                  if k in oldest_values and oldest_values[k] != newest_values[k]]

        return {"added": added, "removed": removed, "changed": changed,
                "compile_count": len(history)}
