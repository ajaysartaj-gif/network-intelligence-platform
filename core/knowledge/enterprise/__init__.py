"""
core/knowledge/enterprise
=========================
Enterprise Knowledge Layer — extends the existing RAG engine with multi-source
typed knowledge, versioning, hybrid search, confidence/ranking, dedup,
automatic ingestion pipelines, and a capability-registry surface.

Bind it into the Capability Registry with bind_knowledge_capability().
"""
from core.knowledge.enterprise.knowledge_layer import (
    EnterpriseKnowledgeLayer, KnowledgeRecord, EnterpriseHit,
    SourceType, SOURCE_RANK, get_knowledge_layer,
)
from core.knowledge.enterprise.pipelines import (
    ingest_directory, ingest_remediation, ingest_incident_report,
    run_standard_pipelines,
)

__all__ = [
    "EnterpriseKnowledgeLayer", "KnowledgeRecord", "EnterpriseHit",
    "SourceType", "SOURCE_RANK", "get_knowledge_layer",
    "ingest_directory", "ingest_remediation", "ingest_incident_report",
    "run_standard_pipelines", "bind_knowledge_capability",
]


def bind_knowledge_capability() -> None:
    """
    Plug the Enterprise Knowledge Layer's live health into the Capability
    Registry's 'knowledge' pillar, so the backbone reports enterprise status
    (source counts, etc.) instead of the basic RAG probe. Safe to call at
    startup; no-ops if the registry isn't importable.
    """
    try:
        from core.intelligence.capability_model import (
            get_capability_registry, CapabilityHealth, CapabilityStatus,
        )
    except Exception:
        return

    def _probe() -> "CapabilityHealth":
        try:
            layer = get_knowledge_layer()
            h = layer.health()
            stats = layer.source_statistics()
            status = {
                "active": CapabilityStatus.ACTIVE,
                "partial": CapabilityStatus.PARTIAL,
                "error": CapabilityStatus.ERROR,
            }.get(h.get("status", "partial"), CapabilityStatus.PARTIAL)
            return CapabilityHealth(
                status, h.get("detail", ""),
                metrics={
                    "chunks": h.get("chunks", 0),
                    "by_source": stats.get("by_source", {}),
                    "distinct_documents": stats.get("distinct_documents", 0),
                    "retrieval_latency_ms": layer.retrieval_latency(),
                },
            )
        except Exception as exc:
            return CapabilityHealth(CapabilityStatus.PARTIAL, f"knowledge layer: {exc}")

    get_capability_registry().bind_probe("knowledge", _probe)
