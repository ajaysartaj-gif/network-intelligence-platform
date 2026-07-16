import json
import os
from typing import Any, Dict, List, Optional

from core.legacy_compat import env as _legacy_env


def _dev_env(idx: int, suffix: str, default: str = "") -> str:
    return _legacy_env(f"AI_NET_STUDIO_DEVICE_{idx}_{suffix}", f"NETBRAIN_DEVICE_{idx}_{suffix}", default)


def _load_env_device(idx: int) -> Optional[Dict[str, Any]]:
    host = _dev_env(idx, "HOST")
    if not host:
        return None

    return {
        "host": host,
        "hostname": _dev_env(idx, "NAME", host),
        "device_type": _dev_env(idx, "TYPE", "cisco_ios"),
        "username": _dev_env(idx, "USERNAME", "admin"),
        "password": _dev_env(idx, "PASSWORD", "admin"),
        "secret": _dev_env(idx, "SECRET", ""),
        "port": int(_dev_env(idx, "PORT", "22")),
        "timeout": int(_dev_env(idx, "TIMEOUT", "60")),
        "fast_cli": False,
        "vendor": _dev_env(idx, "VENDOR", "Cisco"),
        "site": _dev_env(idx, "SITE", "unknown"),
    }


def load_device_catalog() -> List[Dict[str, Any]]:
    """Load a list of live router devices from environment variables."""
    catalog: List[Dict[str, Any]] = []

    raw_catalog = _legacy_env("AI_NET_STUDIO_DEVICE_CATALOG", "NETBRAIN_DEVICE_CATALOG", "")
    if raw_catalog:
        try:
            parsed = json.loads(raw_catalog)
            if isinstance(parsed, list):
                catalog.extend(parsed)
        except Exception:
            pass

    for idx in range(1, 6):
        entry = _load_env_device(idx)
        if entry:
            catalog.append(entry)

    return [item for item in catalog if item.get("host")]
