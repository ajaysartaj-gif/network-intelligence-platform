"""Load corpus/*.txt into Chunks. Trivial section-based chunking for the demo;
real ingestion adds PDF/HTML parsing + smarter chunking, same Chunk output."""
from __future__ import annotations
import os, re
from .rag_engine import Chunk


def load_corpus(path: str) -> list[Chunk]:
    chunks = []
    for fn in sorted(os.listdir(path)):
        if not fn.endswith(".txt"):
            continue
        text = open(os.path.join(path, fn), encoding="utf-8").read()
        doc = re.search(r"# DOC:\s*(\S+)", text)
        sec = re.search(r"SECTION:\s*(\S+)", text)
        rel = re.search(r"# REL:\s*(\S+)", text)
        body = "\n".join(l for l in text.splitlines() if not l.startswith("#"))
        chunks.append(Chunk(doc=doc.group(1) if doc else fn,
                            section=sec.group(1) if sec else "1",
                            text=body.strip(),
                            rel=rel.group(1) if rel else ""))
    return chunks
