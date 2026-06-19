"""Cache layer for NetBrain knowledge system."""
from core.knowledge.cache.cache_db import KnowledgeCacheDB, get_cache
from core.knowledge.cache.ttl_policy import get_ttl, VENDOR_TTL_DAYS

__all__ = ["KnowledgeCacheDB", "get_cache", "get_ttl", "VENDOR_TTL_DAYS"]
