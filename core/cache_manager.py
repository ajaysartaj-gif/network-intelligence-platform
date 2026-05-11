"""Caching layer for database queries with TTL."""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from config import (
    TTL_DEVICES_SECONDS,
    TTL_INCIDENTS_SECONDS,
    TTL_CHANGES_SECONDS,
)


class CacheManager:
    """Simple in-memory cache with TTL support."""

    def __init__(self):
        self.cache: Dict[str, Any] = {}
        self.cache_time: Dict[str, datetime] = {}
        self.ttl_map = {
            "devices": TTL_DEVICES_SECONDS,
            "incidents": TTL_INCIDENTS_SECONDS,
            "changes": TTL_CHANGES_SECONDS,
        }

    def _is_expired(self, key: str) -> bool:
        """Check if cache entry is expired."""
        if key not in self.cache_time:
            return True

        cache_type = key.split(":")[0]
        ttl = self.ttl_map.get(cache_type, 60)
        elapsed = (datetime.utcnow() - self.cache_time[key]).total_seconds()
        return elapsed > ttl

    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired."""
        if key in self.cache and not self._is_expired(key):
            return self.cache[key]
        return None

    def set(self, key: str, value: Any) -> None:
        """Set cache value with current timestamp."""
        self.cache[key] = value
        self.cache_time[key] = datetime.utcnow()

    def invalidate(self, pattern: str) -> None:
        """Invalidate all cache entries matching pattern."""
        to_delete = [k for k in self.cache if pattern in k]
        for key in to_delete:
            del self.cache[key]
            if key in self.cache_time:
                del self.cache_time[key]

    def clear(self) -> None:
        """Clear all cache."""
        self.cache.clear()
        self.cache_time.clear()
