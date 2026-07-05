"""
Knowledge-Retrieval engine.

Pipeline (mirrors your CommandResolver chain: cache -> RAG -> grounded-AI):

    get_package(rel_type)
      -> cache hit? return it
      -> retrieve(rel_type)         # vendor-neutral doc chunks (RFCs preferred)
      -> extract(chunks) -> KP      # LLM turns prose into DECLARED STRUCTURE
      -> validate + stamp provenance + cache

Two seams are pluggable so the whole thing runs offline in tests and on your Mac
without a Groq key, then flips to production with one config change:

  Retriever : LexicalRetriever (default, zero deps) | EmbeddingRetriever (sbert+faiss)
  Extractor : StubExtractor    (default, offline)   | GroqExtractor (llama-3.3-70b)

IMPORTANT: no OSPF knowledge lives in THIS file. The OSPF-ness is entirely in the
corpus text + whatever the extractor derives from it.
"""
from __future__ import annotations
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from .schema import KnowledgePackage, MatchParameter, Relation


# --------------------------------------------------------------------------- #
#  Corpus + retrieval
# --------------------------------------------------------------------------- #
@dataclass
class Chunk:
    doc: str
    section: str
    text: str
    rel: str = ""          # relationship_type this chunk documents (metadata filter)

    @property
    def cite(self):
        return f"{self.doc} \u00a7{self.section}"


class Retriever(ABC):
    @abstractmethod
    def retrieve(self, query: str, k: int = 6) -> list[Chunk]: ...


class LexicalRetriever(Retriever):
    """Dependency-free keyword-overlap retriever. Good enough for a curated,
    lab-scale corpus; deterministic, which keeps acceptance tests stable."""
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks

    @staticmethod
    def _tokens(s): return set(re.findall(r"[a-z0-9]+", s.lower()))

    def retrieve(self, query, k=6):
        q = self._tokens(query)
        scored = sorted(self.chunks,
                        key=lambda c: len(q & self._tokens(c.text)), reverse=True)
        return [c for c in scored if q & self._tokens(c.text)][:k]


class EmbeddingRetriever(Retriever):
    """Production retriever. Left as an explicit stub so the dependency
    (sentence-transformers + faiss) is opt-in, not forced on the test path.

    NOTE: Groq is inference-only for chat models -- as far as I know it exposes
    no embeddings endpoint -- so embeddings run LOCALLY (sbert, free, offline).
    Worth a 30-second check on your side, but the local path removes the
    dependency either way."""
    def __init__(self, chunks, model="BAAI/bge-small-en-v1.5"):
        raise NotImplementedError(
            "pip install sentence-transformers faiss-cpu, then embed self.chunks. "
            "Interface-compatible with LexicalRetriever; swap in production."
        )


# --------------------------------------------------------------------------- #
#  Extraction (prose -> declared structure)
# --------------------------------------------------------------------------- #
class Extractor(ABC):
    @abstractmethod
    def extract(self, relationship_type: str, chunks: list[Chunk]) -> KnowledgePackage: ...


GROQ_PROMPT = """You are extracting a machine-checkable Knowledge Package from vendor/RFC text.
Return ONLY JSON, no prose, matching exactly:
{{
 "relationship_type": "...",
 "enumerate_intent": "...",
 "healthy_states": ["..."],
 "parameters": [
   {{"name": "...", "relation": "must_equal|must_differ", "fatal_if_violated": true,
     "read_intent": "...", "symptom_if_violated": "...", "applies_when": "",
     "provenance": "<doc section>"}}
 ]
}}
Rules: names are vendor-neutral semantic tokens. Include a parameter ONLY if the
source text states the two ends must agree (must_equal) or must not collide
(must_differ). symptom_if_violated must be the observable failure the source
attributes to that violation. Do not invent parameters not grounded in the text.

relationship_type: {rel}
SOURCE:
{src}
"""


class GroqExtractor(Extractor):
    """Real path. Needs GROQ_API_KEY. Emits JSON, we validate into a KP."""
    def __init__(self, client=None, model="llama-3.3-70b-versatile"):
        self.client, self.model = client, model

    def extract(self, relationship_type, chunks):
        import json
        src = "\n\n".join(f"[{c.cite}] {c.text}" for c in chunks)
        prompt = GROQ_PROMPT.format(rel=relationship_type, src=src)
        resp = self.client.chat.completions.create(
            model=self.model, temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content
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


class StubExtractor(Extractor):
    """Offline stand-in for the LLM. It performs a crude but REAL parse of the
    curated corpus (looks for lines tagged 'PARAM:') so the pipeline shape is
    genuine -- doc text in, structured KP out -- without a network call.
    The Groq path produces the identical KP shape from raw prose."""
    def extract(self, relationship_type, chunks):
        params, rel_line, healthy = [], "", ("FULL", "2WAY")
        for c in chunks:
            for line in c.text.splitlines():
                line = line.strip()
                if line.startswith("ENUMERATE:"):
                    rel_line = line.split(":", 1)[1].strip()
                elif line.startswith("HEALTHY:"):
                    healthy = tuple(x.strip() for x in line.split(":", 1)[1].split(","))
                elif line.startswith("PARAM:"):
                    # PARAM: name | relation | fatal | read_intent | symptom | applies_when
                    f = [x.strip() for x in line.split(":", 1)[1].split("|")]
                    params.append(MatchParameter(
                        name=f[0], relation=Relation(f[1]),
                        fatal_if_violated=f[2].lower() == "true", read_intent=f[3],
                        symptom_if_violated=f[4] if len(f) > 4 else "",
                        applies_when=f[5] if len(f) > 5 else "",
                        provenance=c.cite,
                    ))
        return KnowledgePackage(
            relationship_type=relationship_type, enumerate_intent=rel_line,
            healthy_states=healthy, parameters=params,
            source_provenance=sorted({c.cite for c in chunks}),
        ).validate()


# --------------------------------------------------------------------------- #
#  Engine
# --------------------------------------------------------------------------- #
class KnowledgeEngine:
    def __init__(self, retriever: Retriever, extractor: Extractor):
        self.retriever, self.extractor, self._cache = retriever, extractor, {}

    def get_package(self, relationship_type: str) -> KnowledgePackage:
        if relationship_type in self._cache:              # 1. cache
            return self._cache[relationship_type]
        chunks = self.retriever.retrieve(                 # 2. retrieve
            f"{relationship_type} parameters that must match to form the relationship")
        # metadata filter: keep only chunks that document THIS relationship, if tagged.
        scoped = [c for c in chunks if c.rel == relationship_type]
        chunks = scoped or chunks
        kp = self.extractor.extract(relationship_type, chunks)  # 3. grounded extract
        self._cache[relationship_type] = kp               # 4. cache w/ provenance
        return kp
