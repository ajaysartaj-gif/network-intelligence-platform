"""
core/knowledge/rag
==================
Real semantic RAG for NetBrain: local embeddings (sentence-transformers)
+ persistent ChromaDB + symptom/resolution incident memory.

Public surface:
  - get_rag_engine()  : singleton RAGEngine
  - RAGEngine, RAGHit : engine + result types
  - get_embedder/set_embedder, Embedder, LocalEmbedder, FakeEmbedder
"""
from core.knowledge.rag.embedder import (
    Embedder, LocalEmbedder, FakeEmbedder, get_embedder, set_embedder,
)
from core.knowledge.rag.rag_engine import (
    RAGEngine, RAGHit, get_rag_engine,
)

__all__ = [
    "Embedder", "LocalEmbedder", "FakeEmbedder", "get_embedder", "set_embedder",
    "RAGEngine", "RAGHit", "get_rag_engine",
]
