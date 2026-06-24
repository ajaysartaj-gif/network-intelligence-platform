"""
core/topology/credentials.py
=============================
Per-device credential resolution.

The platform historically used ONE global SSH credential set
(GNS3_SSH_USER / GNS3_SSH_PASS) for every device. Real networks -- and
even this lab -- have devices under different credentials, so a single
global login can't poll them all (the device simply fails discovery with
an auth error, and never appears correctly in the topology).

This module resolves credentials per device IP:

  1. A per-IP override, if one is configured.
  2. Otherwise the global default (GNS3_SSH_USER / GNS3_SSH_PASS /
     GNS3_SSH_SECRET).

Per-IP overrides are kept OUT of any committed file. They live in
.streamlit/secrets.toml (gitignored), as a nested table:

    GNS3_SSH_USER = "admin"          # global default
    GNS3_SSH_PASS = "cisco123"
    GNS3_SSH_SECRET = ""

    [device_credentials."192.168.96.136"]
    username = "admin"
    password = "otherpass"
    secret   = ""                    # optional enable secret

    [device_credentials."192.168.96.140"]
    username = "netops"
    password = "netops_pw"

At app startup the secrets→env bridge serializes the device_credentials
table into the GNS3_DEVICE_CREDENTIALS_JSON environment variable, because
discovery runs in worker threads that must not depend on Streamlit's
context. For standalone use (diagnostics, CLI), this module also reads
.streamlit/secrets.toml directly when that env var is absent.
"""
from __future__ import annotations

import os
import json
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_ENV_JSON_KEY = "GNS3_DEVICE_CREDENTIALS_JSON"
_SECRETS_PATH = os.path.join(".streamlit", "secrets.toml")

# Cache the parsed per-IP map so we don't re-read the file on every device.
_cached_map: Optional[Dict[str, Dict[str, str]]] = None


def _load_override_map() -> Dict[str, Dict[str, str]]:
    """
    Return {ip: {"username":..., "password":..., "secret":...}}.

    Source priority:
      1. GNS3_DEVICE_CREDENTIALS_JSON env var (set by the app's bridge).
      2. .streamlit/secrets.toml [device_credentials] table (standalone).
    """
    global _cached_map
    if _cached_map is not None:
        return _cached_map

    # 1. From the bridged env var (normal app path).
    raw = os.environ.get(_ENV_JSON_KEY, "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            _cached_map = {str(k): dict(v) for k, v in parsed.items()}
            return _cached_map
        except Exception as exc:
            logger.warning(f"Could not parse {_ENV_JSON_KEY}: {exc}")

    # 2. From secrets.toml directly (standalone / diagnostic path).
    if os.path.exists(_SECRETS_PATH):
        try:
            try:
                import tomllib
                with open(_SECRETS_PATH, "rb") as f:
                    data = tomllib.load(f)
            except ImportError:
                import toml
                data = toml.load(_SECRETS_PATH)
            table = data.get("device_credentials", {}) or {}
            _cached_map = {str(ip): dict(vals) for ip, vals in table.items()}
            return _cached_map
        except Exception as exc:
            logger.warning(f"Could not read device_credentials from {_SECRETS_PATH}: {exc}")

    _cached_map = {}
    return _cached_map


def clear_cache() -> None:
    """Force a re-read of the override map (e.g. after editing secrets)."""
    global _cached_map
    _cached_map = None


def resolve_device_credentials(ip: str) -> Tuple[str, str, str]:
    """
    Return (username, password, secret) for a device IP.

    A per-IP override wins; any field the override omits falls back to the
    corresponding global default, so an override can specify just a password
    while inheriting the global username, etc.
    """
    g_user = os.environ.get("GNS3_SSH_USER", "admin")
    g_pass = os.environ.get("GNS3_SSH_PASS", "admin")
    g_secret = os.environ.get("GNS3_SSH_SECRET", "")

    override = _load_override_map().get(ip)
    if not override:
        return g_user, g_pass, g_secret

    user = str(override.get("username") or g_user)
    password = str(override.get("password") or g_pass)
    secret = str(override.get("secret") if override.get("secret") is not None else g_secret)
    return user, password, secret


def has_override(ip: str) -> bool:
    """True if a per-IP credential override exists for this device."""
    return ip in _load_override_map()
