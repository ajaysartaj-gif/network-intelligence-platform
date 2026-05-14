import json
import os
from typing import Any, Dict, List, Optional


def _load_env_device(idx: int) -> Optional[Dict[str, Any]]:
    host = os.getenv(f"NETBRAIN_DEVICE_{idx}_HOST")
    if not host:
        return None

    return {
        "host": host,
        "hostname": os.getenv(f"NETBRAIN_DEVICE_{idx}_NAME", host),
        "device_type": os.getenv(f"NETBRAIN_DEVICE_{idx}_TYPE", "cisco_ios"),
        "username": os.getenv(f"NETBRAIN_DEVICE_{idx}_USERNAME", "admin"),
        "password": os.getenv(f"NETBRAIN_DEVICE_{idx}_PASSWORD", "admin"),
        "secret": os.getenv(f"NETBRAIN_DEVICE_{idx}_SECRET", ""),
        "port": int(os.getenv(f"NETBRAIN_DEVICE_{idx}_PORT", "22")),
        "timeout": int(os.getenv(f"NETBRAIN_DEVICE_{idx}_TIMEOUT", "60")),
        "fast_cli": False,
        "vendor": os.getenv(f"NETBRAIN_DEVICE_{idx}_VENDOR", "Cisco"),
        "site": os.getenv(f"NETBRAIN_DEVICE_{idx}_SITE", "unknown"),
    }


def load_device_catalog() -> List[Dict[str, Any]]:
    """Load a list of live router devices from environment variables."""
    catalog: List[Dict[str, Any]] = []

    raw_catalog = os.getenv("NETBRAIN_DEVICE_CATALOG")
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
