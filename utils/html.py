"""HTML safety helpers for Streamlit components."""

from __future__ import annotations

from html import escape as _escape
from typing import Any


def html_escape(value: Any) -> str:
    """Return a safe string for interpolation into unsafe_allow_html blocks."""
    return _escape("" if value is None else str(value), quote=True)


def clamp_percent(value: Any, default: int = 0) -> int:
    """Coerce a value to an integer percentage bounded to 0..100."""
    try:
        score = int(value)
    except (TypeError, ValueError):
        score = default
    return max(0, min(100, score))
