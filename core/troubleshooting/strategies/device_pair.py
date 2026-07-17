"""
Single source of truth for the "between A and B" root-cause-statement
convention run_mismatch_investigation() (mismatch_bridge.py) produces for
every cross-device Finding. Both engine.py (fix targeting) and
copilot_engine.py (post-fix verification scoping) need to recover the same
two device IPs from that same text — defined once here so the two can
never silently drift out of sync, and so engine.py (which must never import
anything from copilot_engine.py, a streamlit-dependent UI module) has a
clean, UI-free place to import it from.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

BETWEEN_DEVICES_RE = re.compile(
    r"between\s+(\d{1,3}(?:\.\d{1,3}){3})\s+and\s+(\d{1,3}(?:\.\d{1,3}){3})")


def extract_between_devices(statement: str) -> Optional[Tuple[str, str]]:
    m = BETWEEN_DEVICES_RE.search(statement or "")
    return (m.group(1), m.group(2)) if m else None
