"""
AiCallExtractor — the LLM-grounded KP extractor, wired to the platform's
existing ai_call(prompt) -> str callable (the same Groq entry point the whole
TroubleshootingEngine already uses) instead of knowledge/rag_engine.py's
GroqExtractor, which expects a raw `client.chat.completions.create()` object.

Reuses the exact prompt template and validation from knowledge/rag_engine.py
and knowledge/schema.py unmodified — only the "how do I call the model" seam
changes, so there is exactly one LLM entry point in the engine, not two.
"""
from __future__ import annotations

import json
import re
from typing import Callable, List

from knowledge.rag_engine import GROQ_PROMPT, Chunk, Extractor
from knowledge.schema import KnowledgePackage, MatchParameter, Relation


class AiCallExtractor(Extractor):
    def __init__(self, ai_call: Callable[[str], str]):
        self.ai_call = ai_call

    def extract(self, relationship_type: str, chunks: List[Chunk]) -> KnowledgePackage:
        src = "\n\n".join(f"[{c.cite}] {c.text}" for c in chunks)
        prompt = GROQ_PROMPT.format(rel=relationship_type, src=src)
        raw = self.ai_call(prompt) or ""
        raw = re.sub(r"^```json|```$", "", raw.strip(), flags=re.M).strip()
        d = json.loads(raw)
        return KnowledgePackage(
            relationship_type=d["relationship_type"],
            enumerate_intent=d["enumerate_intent"],
            healthy_states=tuple(d["healthy_states"]),
            parameters=[MatchParameter(
                name=p["name"], relation=Relation(p["relation"]),
                fatal_if_violated=p["fatal_if_violated"], read_intent=p["read_intent"],
                symptom_if_violated=p.get("symptom_if_violated", ""),
                applies_when=p.get("applies_when", ""), provenance=p.get("provenance", ""),
            ) for p in d["parameters"]],
            source_provenance=sorted({c.cite for c in chunks}),
        ).validate()
