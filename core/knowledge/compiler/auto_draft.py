"""
Offline, authoring-time knowledge drafter — Build item A of the industry-
wide knowledge-scaling plan.

Reuses the exact extraction machinery already proven LIVE at query time for
OSPF/HSRP (knowledge/rag_engine.py's GROQ_PROMPT schema, via
core.troubleshooting.strategies._ai_extractor.AiCallExtractor) but runs it
offline, once per protocol, against real already-ingested prose
(corpus/general/<protocol>.txt — hand-composed once from real vendor/RFC
knowledge, currently used only for RAG grounding, never structured), and
PERSISTS the result as a new corpus/<relationship_type>.txt file instead of
caching it in memory for a single query. It then auto-registers the new
relationship_type so it's live immediately — no separate review/publish
step, per the chosen speed-over-review-gate strategy.

Scope of this pass: drafts Mismatch Investigation PARAM lines only — the
one extraction shape already proven to work reliably in production. FSM
state models / FailureSignatures / RemediationRecipes are still hand-
authored Python in protocol_registry.py; auto-generating those from prose
is a separate, higher-risk follow-on, not attempted here (see the plan's
Build item A passes 1/2/4).
"""
from __future__ import annotations

import os
import re
from typing import Callable, List

from knowledge.rag_engine import Chunk
from knowledge.schema import KnowledgePackage
from core.troubleshooting.strategies._ai_extractor import AiCallExtractor

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_CORPUS_DIR = os.path.join(_REPO_ROOT, "corpus")
_GENERAL_CORPUS_DIR = os.path.join(_CORPUS_DIR, "general")


def load_prose_chunks(protocol: str) -> List[Chunk]:
    """Reads corpus/general/<protocol>.txt and splits it on its own
    "Heading\\n---...\\n" section markers — the same shape every file in
    that directory already uses. Returns [] if no prose exists yet for
    this protocol (the caller should ingest real vendor docs first)."""
    path = os.path.join(_GENERAL_CORPUS_DIR, f"{protocol}.txt")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    sections = re.split(r"\n(?=[^\n]{1,80}\n-{3,}\n)", text)
    chunks: List[Chunk] = []
    for i, sec in enumerate(sections):
        sec = sec.strip()
        if not sec:
            continue
        title = sec.splitlines()[0][:60]
        chunks.append(Chunk(doc=f"{protocol}.txt", section=title or str(i), text=sec, rel=protocol))
    return chunks


def draft_match_parameters(relationship_type: str, protocol: str,
                           ai_call: Callable[[str], str]) -> KnowledgePackage:
    """Pass 3 from the plan: turns real prose into a KnowledgePackage of
    MatchParameters, using the exact prompt/schema already live for OSPF
    and HSRP query-time extraction — just run once, offline, over the
    protocol's whole corpus instead of per-query over retrieved chunks."""
    chunks = load_prose_chunks(protocol)
    if not chunks:
        raise ValueError(
            f"no ingested prose found for protocol {protocol!r} "
            f"(expected corpus/general/{protocol}.txt) — ingest real vendor "
            f"docs for this protocol before drafting")
    return AiCallExtractor(ai_call).extract(relationship_type, chunks)


def persist_corpus_file(kp: KnowledgePackage, relationship_type: str) -> str:
    """Serializes a KnowledgePackage back into the ENUMERATE:/HEALTHY:/
    PARAM: text schema knowledge/rag_engine.py's StubExtractor already
    parses (and completeness_check.py's _parse_corpus_params reads
    directly) — the exact inverse of that parse, so a drafted KP plugs
    into the existing pipeline completely unmodified. Each PARAM line
    keeps its source citation as a trailing comment, since nothing else
    reviews these before they publish."""
    path = os.path.join(_CORPUS_DIR, f"{relationship_type}.txt")
    lines = [
        f"# Auto-drafted by core.knowledge.compiler.auto_draft from "
        f"corpus/general/ prose — published without a review gate; each "
        f"PARAM's trailing comment cites its source section for later audit.",
        "",
        f"ENUMERATE: {kp.enumerate_intent}",
        f"HEALTHY: {', '.join(kp.healthy_states)}",
        "",
    ]
    for p in kp.parameters:
        fields = [p.name, p.relation.value, str(p.fatal_if_violated).lower(),
                 p.read_intent, p.symptom_if_violated, p.applies_when]
        lines.append("PARAM: " + " | ".join(fields) + f"  # source: {p.provenance}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def _mismatch_bridge_path() -> str:
    return os.path.join(_REPO_ROOT, "core", "troubleshooting", "strategies", "mismatch_bridge.py")


def _gateway_adapter_path() -> str:
    return os.path.join(_REPO_ROOT, "core", "troubleshooting", "strategies", "gateway_adapter.py")


def _insert_dict_entry(path: str, dict_name: str, new_line: str) -> None:
    """Idempotently inserts one `"key": value,` line as the first entry of
    an existing flat dict literal `dict_name = {`. Deliberately does NOT
    attempt to parse/regenerate the surrounding Python — a targeted,
    mechanical single-line insert into a dict literal that already exists
    is far lower-risk than code-generating and splicing in whole new
    dataclass blocks, which is why this pass is scoped to corpus/PARAM
    drafting only (see module docstring)."""
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if new_line.strip() in text:
        return  # already registered — idempotent
    pattern = re.compile(re.escape(dict_name) + r"\s*=\s*\{\n")
    m = pattern.search(text)
    if not m:
        raise ValueError(f"could not find dict literal {dict_name!r} in {path}")
    insert_at = m.end()
    text = text[:insert_at] + new_line + "\n" + text[insert_at:]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def register_relationship(relationship_type: str, protocol: str) -> None:
    """Auto-publish step: wires the new relationship_type into the two
    flat dicts that make it live end to end —
    mismatch_bridge.py's _RELATIONSHIP_KEYWORDS (query keyword ->
    relationship_type, so a real question about this protocol reaches the
    Mismatch Investigation at all) and gateway_adapter.py's
    RELATIONSHIP_PROTOCOL (relationship_type -> protocol, so the adapter
    knows which vendor commands/attributes to use). Idempotent."""
    _insert_dict_entry(
        _mismatch_bridge_path(), "_RELATIONSHIP_KEYWORDS",
        f'    "{relationship_type}": ("{protocol}",),')
    _insert_dict_entry(
        _gateway_adapter_path(), "RELATIONSHIP_PROTOCOL",
        f'    "{relationship_type}": "{protocol}",')


def draft_and_publish(relationship_type: str, protocol: str,
                      ai_call: Callable[[str], str]) -> str:
    """The one call a CLI/batch runner needs: draft from real ingested
    prose, persist as a corpus file, and register it live — no separate
    review/approval step, per the chosen speed-over-review-gate strategy.
    Returns the path written."""
    kp = draft_match_parameters(relationship_type, protocol, ai_call)
    path = persist_corpus_file(kp, relationship_type)
    register_relationship(relationship_type, protocol)
    return path
