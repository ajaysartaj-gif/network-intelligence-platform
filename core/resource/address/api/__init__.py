"""NRIE Address bounded context — public API surface (foundation, read-only)."""
from .service import NRIEFoundationService, get_nrie_service

__all__ = ["NRIEFoundationService", "get_nrie_service"]
