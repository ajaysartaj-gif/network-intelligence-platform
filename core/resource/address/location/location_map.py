"""
NRIE · Location · Geographic Resolver
=====================================
Resolves a place name into Region > Country > State > City. Deterministic
knowledge for common locations; AI fallback (reused Groq) for anything unknown.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..ai.assistant import parse_json

# city -> (state, country, region)
_CITIES = {
    "mumbai": ("Maharashtra", "India", "APAC"),
    "pune": ("Maharashtra", "India", "APAC"),
    "nagpur": ("Maharashtra", "India", "APAC"),
    "bengaluru": ("Karnataka", "India", "APAC"),
    "bangalore": ("Karnataka", "India", "APAC"),
    "chennai": ("Tamil Nadu", "India", "APAC"),
    "hyderabad": ("Telangana", "India", "APAC"),
    "delhi": ("Delhi", "India", "APAC"),
    "new delhi": ("Delhi", "India", "APAC"),
    "noida": ("Uttar Pradesh", "India", "APAC"),
    "greater noida": ("Uttar Pradesh", "India", "APAC"),
    "gurugram": ("Haryana", "India", "APAC"),
    "kolkata": ("West Bengal", "India", "APAC"),
    "ahmedabad": ("Gujarat", "India", "APAC"),
    "singapore": ("Singapore", "Singapore", "APAC"),
    "london": ("England", "United Kingdom", "EMEA"),
    "dubai": ("Dubai", "United Arab Emirates", "EMEA"),
    "frankfurt": ("Hesse", "Germany", "EMEA"),
    "new york": ("New York", "United States", "AMER"),
    "san francisco": ("California", "United States", "AMER"),
    "dallas": ("Texas", "United States", "AMER"),
}


@dataclass
class LocationChain:
    city: str = ""
    state: str = ""
    country: str = ""
    region: str = ""
    source: str = "fallback"

    def is_resolved(self) -> bool:
        return bool(self.city and self.country and self.region)


def resolve(location: str) -> LocationChain:
    name = (location or "").strip()
    if not name:
        return LocationChain()
    hit = _CITIES.get(name.lower())
    if hit:
        state, country, region = hit
        return LocationChain(city=name.title(), state=state, country=country,
                             region=region, source="map")
    ai = parse_json(
        f"For the place '{name}', return its city, state/province, country, and "
        f"world region (one of APAC, EMEA, AMER).")
    if ai and ai.get("country"):
        return LocationChain(
            city=str(ai.get("city") or name).title(),
            state=str(ai.get("state") or "").title(),
            country=str(ai.get("country") or "").title(),
            region=str(ai.get("region") or "APAC").upper(), source="ai")
    # last-resort: keep the city, leave the rest generic
    return LocationChain(city=name.title(), state="", country="Unknown",
                         region="APAC", source="fallback")
