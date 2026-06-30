"""
NRIE · Intent · Natural-language Site Intent Parser
===================================================
Turns operator language ("deploy a 20 users site in Mumbai") into a structured
SiteIntent and a derived set of address demands. AI-assisted (reuses the Groq
client) with a robust deterministic regex fallback so it always works.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from ..allocation.allocator import AddressDemand
from ..ai.assistant import parse_json

_SITE_TYPES = ("branch", "campus", "manufacturing", "warehouse", "retail",
               "datacenter", "office")


@dataclass
class SiteIntent:
    raw: str
    users: int = 0
    location: str = ""
    site_type: str = "branch"
    source: str = "fallback"          # "ai" | "fallback"

    def is_valid(self) -> bool:
        return self.users > 0 or bool(self.location)


def parse(text: str) -> SiteIntent:
    text = (text or "").strip()
    ai = parse_json(
        "Extract a site deployment intent from this request: "
        f"\"{text}\". Fields: users (int), location (city/place string), "
        f"site_type (one of {list(_SITE_TYPES)}).")
    if ai and (ai.get("users") or ai.get("location")):
        try:
            users = int(ai.get("users") or 0)
        except (TypeError, ValueError):
            users = 0
        st = str(ai.get("site_type") or "branch").lower()
        return SiteIntent(raw=text, users=users,
                          location=str(ai.get("location") or "").strip(),
                          site_type=st if st in _SITE_TYPES else "branch", source="ai")
    return _fallback(text)


def _fallback(text: str) -> SiteIntent:
    low = text.lower()
    m = re.search(r"(\d+)\s*(?:users?|seats?|people|staff|employees?)", low)
    users = int(m.group(1)) if m else (
        int(re.search(r"\b(\d+)\b", low).group(1)) if re.search(r"\b(\d+)\b", low) else 0)
    loc = ""
    lm = re.search(r"\b(?:in|at|for)\s+([a-z][a-z .'-]+)$", low) or \
        re.search(r"\b(?:in|at|for)\s+([a-z][a-z .'-]+?)(?:\s+(?:site|office|branch|campus))", low)
    if lm:
        loc = lm.group(1).strip().title()
    st = next((t for t in _SITE_TYPES if t in low), "branch")
    return SiteIntent(raw=text, users=users, location=loc, site_type=st, source="fallback")


# per-user planning ratios → address demands (knowledge, not config)
def derive_demands(intent: SiteIntent) -> List[AddressDemand]:
    u = max(1, intent.users)
    profile = {
        "branch":        {"user_lan": u, "voice": u, "guest": max(10, u // 2), "mgmt": 8, "iot": max(5, u // 5)},
        "office":        {"user_lan": u, "voice": u, "guest": max(20, u), "mgmt": 12, "iot": max(10, u // 4)},
        "manufacturing": {"user_lan": u, "voice": max(10, u // 2), "ot": max(32, u * 2), "cctv": max(16, u), "mgmt": 16},
        "warehouse":     {"user_lan": u, "iot": max(20, u * 2), "cctv": max(16, u), "mgmt": 8},
        "retail":        {"user_lan": u, "voice": u, "guest": max(25, u * 2), "cctv": max(8, u // 2), "mgmt": 6},
        "campus":        {"user_lan": u, "voice": u, "guest": max(50, u), "iot": max(20, u // 3), "mgmt": 16},
        "datacenter":    {"user_lan": max(8, u // 4), "mgmt": max(24, u), "ot": 0},
    }.get(intent.site_type, {"user_lan": u, "voice": u, "guest": max(10, u // 2), "mgmt": 8})
    return [AddressDemand(purpose=p, host_count=h) for p, h in profile.items() if h > 0]
