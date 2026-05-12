from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class KnowledgeDocument:
    id: str
    title: str
    vendor: str
    protocol: str
    content: str
    metadata: Dict[str, str] = field(default_factory=dict)


class RAGEngine:
    """In-memory retrieval augmented generation engine for network operations."""

    def __init__(self, documents: Optional[List[KnowledgeDocument]] = None) -> None:
        self.documents: List[KnowledgeDocument] = documents or []

    def add_document(self, document: KnowledgeDocument) -> None:
        self.documents.append(document)

    def _tokenize(self, text: str) -> List[str]:
        return [token.lower() for token in text.split() if token.strip()]

    def _score_document(self, query_tokens: List[str], document: KnowledgeDocument) -> float:
        content_tokens = self._tokenize(document.content)
        overlap = len(set(query_tokens) & set(content_tokens))
        vendor_bonus = 1.5 if document.vendor and any(v.lower() in query_tokens for v in [document.vendor.lower()]) else 1.0
        protocol_bonus = 1.5 if document.protocol and any(p.lower() in query_tokens for p in [document.protocol.lower()]) else 1.0
        return overlap * vendor_bonus * protocol_bonus

    def search(
        self,
        query: str,
        vendor: Optional[str] = None,
        protocol: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, object]]:
        query_tokens = self._tokenize(query)
        scored: List[Dict[str, object]] = []

        for document in self.documents:
            if vendor and vendor.lower() != document.vendor.lower():
                continue
            if protocol and protocol.lower() != document.protocol.lower():
                continue

            base_score = self._score_document(query_tokens, document)
            if base_score <= 0:
                continue

            scored.append(
                {
                    "id": document.id,
                    "title": document.title,
                    "vendor": document.vendor,
                    "protocol": document.protocol,
                    "score": round(base_score, 2),
                    "snippet": document.content[:240],
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def seed_documents(self, documents: List[Dict[str, str]]) -> None:
        for entry in documents:
            self.add_document(
                KnowledgeDocument(
                    id=entry.get("id", entry.get("title", "")),
                    title=entry.get("title", ""),
                    vendor=entry.get("vendor", ""),
                    protocol=entry.get("protocol", ""),
                    content=entry.get("content", ""),
                    metadata={k: v for k, v in entry.items() if k not in ["id", "title", "vendor", "protocol", "content"]},
                )
            )
