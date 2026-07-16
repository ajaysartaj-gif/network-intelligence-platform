"""
core/legacy_compat.py
======================
The platform was renamed from "NetBrain" to "AI Net Studio". This module is
the ONE place that bridges old, already-deployed configuration (env var
names, on-disk data file names) to their new equivalents, so existing
secrets/data survive the rename untouched.

Delete this module (and its two call patterns) once every real deployment's
secrets/env have been migrated to the new names and no on-disk legacy file
remains.
"""
from __future__ import annotations

import os


def env(new_name: str, old_name: str, default: str = "") -> str:
    """Read `new_name` from the environment; fall back to the legacy
    `old_name` (pre-rename) if `new_name` isn't set. Never raises."""
    val = os.environ.get(new_name)
    if val is not None:
        return val
    return os.environ.get(old_name, default)


def migrate_path(old_path: str, new_path: str) -> str:
    """One-time rename of a legacy-named data file/dir to its new name.
    No-op if `new_path` already exists or `old_path` doesn't — safe to call
    on every startup. Returns `new_path` for the caller to use either way."""
    if old_path != new_path and not os.path.exists(new_path) and os.path.exists(old_path):
        try:
            os.rename(old_path, new_path)
        except OSError:
            pass
    return new_path


def env_path(new_env: str, old_env: str, old_default: str, new_default: str) -> str:
    """Resolve a configurable data-file path. If the caller explicitly set
    `new_env` or the legacy `old_env`, that wins verbatim (no migration —
    an explicit path is the caller's own responsibility). Otherwise resolve
    to `new_default`, migrating any file/dir still sitting at `old_default`
    into place first."""
    explicit = os.environ.get(new_env) or os.environ.get(old_env)
    if explicit:
        return explicit
    return migrate_path(old_default, new_default)
