"""
core/knowledge/compiler/facts.py
===================================
Fact Compiler — turns REFERENCE-KNOWLEDGE prose (RFCs, vendor docs, KB
articles, runbooks — text already ingested into
core.knowledge.enterprise.knowledge_layer.EnterpriseKnowledgeLayer) into
atomic, evidence-backed Facts. This is a different domain from
core/knowledge/compiler/semantic_analyzer.py's extractors, which parse
DEVICE-SPECIFIC CLI/config syntax into device-scoped NormalizedObjects —
Facts are vendor/protocol-scoped general assertions, not per-device state.

Scope is deliberately narrow: ONE well-defined, deterministic pattern —
default-value assertions ("the default value of X is Y", "X defaults to
Y", "by default, X is Y", "default X is Y"). Vendor docs and RFCs phrase
these consistently enough that regex extraction is genuinely reliable.
General-purpose semantic fact extraction from arbitrary prose is NOT
deterministic, and faking precision there would produce "trusted
knowledge" that isn't actually trustworthy — see
docs/nkc_fact_and_conflict_model.md for the full rationale.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.vendor.models import NormalizedObject

COMPILER_VERSION = "nkc-cross-document-compiler/0.1"


@dataclass
class Fact:
    """One atomic assertion extracted from reference-knowledge text."""
    subject: str
    predicate: str
    object: str
    context: str = ""              # the sentence this was extracted from
    source_doc_id: str = ""
    vendor: str = ""
    source_type: str = ""          # core.knowledge.enterprise.knowledge_layer.SourceType value
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)
    compiler_version: str = COMPILER_VERSION
    citation: Dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Groups facts about the same (subject, predicate) for conflict
        detection / confidence blending — see fact_conflicts.py."""
        return f"{self.subject}::{self.predicate}"

    def content_hash(self) -> str:
        return hashlib.sha256(
            f"{self.subject}|{self.predicate}|{self.object}|{self.source_doc_id}".encode()
        ).hexdigest()[:12]


def _normalize_subject(text: str) -> str:
    t = re.sub(r"^(the|a|an)\s+", "", text.strip(), flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", t).strip().lower()


# Ordered most-specific-first; a sentence is matched against these in order
# and stops at the first hit — a sentence produces at most one Fact, so
# overlapping phrasings never double-count.
_DEFAULT_VALUE_PATTERNS = [
    re.compile(r"default\s+value\s+of\s+(?:the\s+)?(.+?)\s+is\s+(.+?)\s*$", re.IGNORECASE),
    re.compile(r"by\s+default,?\s+(?:the\s+)?(.+?)\s+is\s+(.+?)\s*$", re.IGNORECASE),
    re.compile(r"(.+?)\s+defaults?\s+to\s+(.+?)\s*$", re.IGNORECASE),
    re.compile(r"(?:the\s+)?default\s+(.+?)\s+is\s+(.+?)\s*$", re.IGNORECASE),
]


def _split_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def extract_facts_from_text(
    text: str,
    *,
    source_doc_id: str = "",
    vendor: str = "",
    source_type: str = "",
    confidence: float = 0.7,
) -> List[Fact]:
    """
    Extract default-value Facts from reference-knowledge prose. Each
    matching sentence produces one Fact(predicate="default_value").
    Confidence here is a base value (extraction reliability); the REAL,
    context-aware confidence blending authority/evidence/recency happens
    in fact_conflicts.fact_confidence() once facts from multiple sources
    are compared.
    """
    facts: List[Fact] = []
    for sentence in _split_sentences(text):
        clean = sentence.rstrip(".!?").strip()
        for pattern in _DEFAULT_VALUE_PATTERNS:
            m = pattern.search(clean)
            if not m:
                continue
            subject_raw, object_raw = m.group(1), m.group(2)
            subject = _normalize_subject(subject_raw)
            obj = object_raw.strip()
            if not subject or not obj or len(subject) > 120:
                continue
            facts.append(Fact(
                subject=subject, predicate="default_value", object=obj,
                context=sentence, source_doc_id=source_doc_id, vendor=vendor,
                source_type=source_type, confidence=confidence,
            ))
            break   # first matching pattern wins for this sentence
    return facts


def fact_to_object(fact: Fact) -> NormalizedObject:
    """
    Adapter so a Fact can be published into the EXISTING KnowledgeGraph via
    core.knowledge.compiler.graph_ops.merge_into_graph — reused unchanged,
    not reimplemented for facts.
    """
    obj_id = f"fact:{fact.subject}:{fact.predicate}:{fact.source_doc_id or fact.content_hash()}"
    attributes: Dict[str, Any] = {
        "subject": fact.subject,
        "predicate": fact.predicate,
        "object": fact.object,
        "context": fact.context,
        "_confidence": fact.confidence,
        "_source_doc_id": fact.source_doc_id,
        "_vendor": fact.vendor,
        "_source_type": fact.source_type,
        "_extracted_by": "deterministic",
        "_compiler_version": fact.compiler_version,
        "_hash": fact.content_hash(),
    }
    return NormalizedObject(type="fact", id=obj_id, device="", attributes=attributes)
