"""
NetBrain Knowledge System
=========================
Vendor-neutral knowledge layer for the network intelligence platform.

Public API:
  - KnowledgeOrchestrator, get_orchestrator() — main entry point
  - KnowledgeEntry, Citation, ConfidenceLevel — data types
  - CitationTracker — pipeline citation collector
  - detect_vendor(), detect_platform() — helpers
  - supported_vendors() — list of vendors with fetchers
"""
from core.knowledge.base import (
    Citation,
    ConfidenceLevel,
    KnowledgeEntry,
    KnowledgeSource,
    detect_vendor,
    detect_platform,
)
from core.knowledge.cache.cache_db import KnowledgeCacheDB, get_cache
from core.knowledge.citation_tracker import CitationTracker
from core.knowledge.orchestrator import KnowledgeOrchestrator, get_orchestrator
from core.knowledge.vendor_router import (
    get_fetcher,
    supported_vendors,
    health_check_all,
)

__all__ = [
    "Citation",
    "CitationTracker",
    "ConfidenceLevel",
    "KnowledgeCacheDB",
    "KnowledgeEntry",
    "KnowledgeOrchestrator",
    "KnowledgeSource",
    "detect_vendor",
    "detect_platform",
    "get_cache",
    "get_fetcher",
    "get_orchestrator",
    "health_check_all",
    "supported_vendors",
]
