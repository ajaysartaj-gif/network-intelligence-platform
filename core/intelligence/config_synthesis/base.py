"""
core/intelligence/config_synthesis/base.py
===========================================
The substrate for CONFIGURATION INTELLIGENCE — turning intent into configuration
the way an authoritative document would, not the way a language model guesses.

The failure this fixes is concrete and important: the same intent ("configure
DNS + NTP, clock in IST") produced *different* command sets on different routers
— `8.4.4.4` instead of `8.8.4.4` on one, `pool.ntp.org` on one and
`1.pool.ntp.org`/`2.pool.ntp.org` on another — because the commands were being
freely generated per device. Free generation is non-deterministic by nature, so
it cannot be a source of truth.

The principle here: a configuration is COMPILED from intent, not invented. The
LLM may PARSE intent and FILL slots, but it never authors device syntax. Syntax
comes from a vendor-authoritative template (validated, where possible, against
the OEM's own documentation via RAG). The same intent on the same platform
therefore yields the SAME canonical commands every time, on every device — and
every value is validated, so `8.4.4.4` is caught before it ever reaches a router.

A StateCheck additionally records WHAT KIND of truth it asserts: whether the
intent is merely *applied* (present in running-config), *persisted* (saved to
startup-config), or *operational* (actually synchronised/reachable). That
distinction is what stops a perfectly-correct config from being reported as a
failure just because a lab has no path to public NTP.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── vendors / platforms ──────────────────────────────────────────────────────
class Vendor(str, Enum):
    CISCO_IOS = "cisco_ios"
    CISCO_NXOS = "cisco_nxos"
    ARISTA_EOS = "arista_eos"
    JUNIPER_JUNOS = "juniper_junos"
    GENERIC = "generic"


# ── the kind of truth a check asserts ────────────────────────────────────────
class CheckKind(str, Enum):
    APPLIED = "applied"        # present in running-config (intent took effect)
    PERSISTED = "persisted"    # present in startup-config (survives reload)
    OPERATIONAL = "operational"  # actually working (synced/resolved/reachable)


@dataclass
class StateCheck:
    description: str
    verify_command: str
    expect_present: List[str] = field(default_factory=list)  # substrings that must appear
    expect_absent: List[str] = field(default_factory=list)
    kind: CheckKind = CheckKind.APPLIED
    # operational checks that depend on external reachability are not hard
    # failures in an isolated environment — they degrade to 'pending'.
    reachability_dependent: bool = False


@dataclass
class ConfigIntent:
    """A normalised, structured statement of what the operator wants."""
    raw_text: str
    features: List[str] = field(default_factory=list)   # dns | ntp | clock_timezone | ...
    params: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)

    def wants(self, feature: str) -> bool:
        return feature in self.features


@dataclass
class ConfigPlan:
    """The compiled, deterministic plan for ONE device and ONE feature set."""
    device: str
    vendor: str
    features: List[str]
    apply_commands: List[str] = field(default_factory=list)
    save_required: bool = True
    checks: List[StateCheck] = field(default_factory=list)
    provenance: List[str] = field(default_factory=list)   # where each part came from
    warnings: List[str] = field(default_factory=list)
    # a stable fingerprint of the *canonical* commands (device-independent part),
    # used to prove cross-device consistency.
    canonical_signature: str = ""

    def is_empty(self) -> bool:
        return not self.apply_commands


# ── validation helpers (the guard that catches 8.4.4.4) ──────────────────────
def is_valid_ipv4(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
        return ip.version == 4
    except Exception:
        return False


def looks_like_typo_ip(addr: str) -> bool:
    """Heuristic: a 3-octet 'IP' or an address with an octet >255 — i.e. the
    kind of malformed value free-generation produces (8.4.4.4 is valid IPv4 but
    is a well-known *wrong* value; that's caught by canonical constants, not
    here). This catches structurally invalid values."""
    parts = addr.split(".")
    if len(parts) != 4:
        return True
    for p in parts:
        if not p.isdigit() or not (0 <= int(p) <= 255):
            return True
    return False


_TIMEZONE_OFFSETS = {
    # canonical (name, hours, minutes) — the single source of truth for zones.
    "ist": ("IST", 5, 30), "utc": ("UTC", 0, 0), "gmt": ("GMT", 0, 0),
    "pst": ("PST", -8, 0), "pdt": ("PDT", -7, 0), "est": ("EST", -5, 0),
    "edt": ("EDT", -4, 0), "cst": ("CST", -6, 0), " cet": ("CET", 1, 0),
    "jst": ("JST", 9, 0), "sgt": ("SGT", 8, 0), "aest": ("AEST", 10, 0),
}


def canonical_timezone(name: str) -> Optional[tuple]:
    return _TIMEZONE_OFFSETS.get((name or "").strip().lower())


# canonical public resolvers/servers — authoritative values, so a free-text
# "free DNS" never becomes a typo like 8.4.4.4.
CANONICAL_PUBLIC_DNS = ["8.8.8.8", "8.8.4.4"]            # Google public DNS
CANONICAL_PUBLIC_DNS_ALT = ["1.1.1.1", "1.0.0.1"]       # Cloudflare
CANONICAL_PUBLIC_NTP = ["pool.ntp.org"]


def normalize_dns_servers(requested: List[str]) -> tuple:
    """Return (validated_servers, warnings). Corrects/repairs obvious bad values
    against canonical constants; drops structurally invalid ones."""
    out, warnings = [], []
    for s in requested or []:
        s = s.strip()
        if not s:
            continue
        if looks_like_typo_ip(s):
            warnings.append(f"dropped malformed DNS value '{s}'")
            continue
        # repair the classic 8.4.4.4 → 8.8.4.4 fat-finger of Google secondary.
        if s == "8.4.4.4":
            warnings.append("corrected '8.4.4.4' → '8.8.4.4' (Google DNS secondary)")
            s = "8.8.4.4"
        out.append(s)
    # de-dup, preserve order
    seen, dedup = set(), []
    for s in out:
        if s not in seen:
            seen.add(s); dedup.append(s)
    return dedup, warnings
