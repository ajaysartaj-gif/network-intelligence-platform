"""
Universal Vendor Adapter Framework — registry & discovery
=========================================================
Adapters register themselves via @register and are auto-discovered by scanning
the adapters package. There is NO hardcoded list of vendors anywhere here.

Detection picks the highest-confidence adapter for a device. A generic fallback
adapter returns a low but non-zero confidence so unknown devices still resolve.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Dict, List, Optional, Tuple, Type

from .sdk import DeviceProbe, VendorAdapter
from .models import VendorProfile

logger = logging.getLogger(__name__)

_REGISTRY: Dict[str, VendorAdapter] = {}
_DISCOVERED = False


def register(adapter_cls: Type[VendorAdapter]) -> Type[VendorAdapter]:
    """Class decorator: instantiate and register an adapter by its `name`."""
    inst = adapter_cls()
    if not getattr(inst, "name", None) or inst.name == "unnamed":
        raise ValueError(f"{adapter_cls.__name__} must define a unique 'name'")
    _REGISTRY[inst.name] = inst
    logger.debug("Registered vendor adapter: %s", inst.name)
    return adapter_cls


def all_adapters() -> List[VendorAdapter]:
    return list(_REGISTRY.values())


def get_adapter(name: str) -> Optional[VendorAdapter]:
    return _REGISTRY.get(name)


def discover_adapters(package: str = "core.vendor.adapters", force: bool = False) -> int:
    """Import every module in the adapters package so decorators run.

    Adding a new adapter file is enough to make it available — no registration
    list to edit, no engine change.
    """
    global _DISCOVERED
    if _DISCOVERED and not force:
        return len(_REGISTRY)
    try:
        pkg = importlib.import_module(package)
    except Exception as exc:  # pragma: no cover
        logger.warning("Adapter package %s not importable: %s", package, exc)
        _DISCOVERED = True
        return len(_REGISTRY)
    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"{package}.{mod.name}")
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to import adapter %s: %s", mod.name, exc)
    _DISCOVERED = True
    return len(_REGISTRY)


def detect_adapter(probe: DeviceProbe) -> Tuple[Optional[VendorAdapter], Optional[VendorProfile]]:
    """Return the best (adapter, profile) for a device by detection confidence."""
    discover_adapters()
    best_adapter: Optional[VendorAdapter] = None
    best_profile: Optional[VendorProfile] = None
    best_key = (-1.0, -1)
    for adapter in all_adapters():
        try:
            profile = adapter.detect(probe)
        except Exception as exc:
            logger.debug("detect() failed for %s: %s", adapter.name, exc)
            continue
        if not profile or profile.confidence <= 0:
            continue
        profile.adapter = adapter.name
        key = (profile.confidence, getattr(adapter, "priority", 50))
        if key > best_key:
            best_key, best_adapter, best_profile = key, adapter, profile
    return best_adapter, best_profile
