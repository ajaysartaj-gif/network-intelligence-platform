"""
core/intelligence/config_synthesis/templates.py
================================================
The vendor-authoritative template library — the source of truth.

Each template owns the canonical, idempotent syntax for one feature on one
platform, the verification commands, and — crucially — the CLASSIFICATION of each
check as applied / persisted / operational. This is the knowledge that, validated
where possible against the OEM's own documentation, replaces free generation:
the same intent compiles to the same commands every time, on every device.

Templates are parameterised only by validated values (and by the device's
already-present config for idempotency); they never let the model choose syntax.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from core.intelligence.config_synthesis.base import (
    Vendor, CheckKind, StateCheck, ConfigIntent, ConfigPlan,
    canonical_timezone, normalize_dns_servers, is_valid_ipv4,
    CANONICAL_PUBLIC_DNS, CANONICAL_PUBLIC_NTP,
)


def _present(line: str, current_config: str) -> bool:
    return bool(current_config) and line.strip().lower() in current_config.lower()


class Template:
    feature: str = ""
    vendors = (Vendor.CISCO_IOS.value,)

    def applies(self, intent: ConfigIntent, vendor: str) -> bool:
        return intent.wants(self.feature) and vendor in self.vendors

    def synthesize(self, intent: ConfigIntent, vendor: str,
                   device: str, current_config: str = "",
                   environment: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise NotImplementedError


# ── DNS ──────────────────────────────────────────────────────────────────────
class CiscoIOS_DNS(Template):
    feature = "dns"

    def synthesize(self, intent, vendor, device, current_config="", environment=None):
        env = environment or {}
        requested = intent.params.get("dns_servers") or []
        if not requested or intent.params.get("dns_free"):
            requested = list(env.get("dns_servers") or CANONICAL_PUBLIC_DNS)
        servers, warnings = normalize_dns_servers(requested)
        cmds, checks = [], []
        # enable resolution (idempotent)
        if not _present("ip domain-lookup", current_config):
            cmds.append("ip domain-lookup")
        for s in servers:
            line = f"ip name-server {s}"
            if not _present(line, current_config):
                cmds.append(line)
        for s in servers:
            checks.append(StateCheck(
                f"DNS server {s} present", "show running-config | include name-server",
                expect_present=[s], kind=CheckKind.APPLIED))
            checks.append(StateCheck(
                f"DNS server {s} persisted", "show startup-config | include name-server",
                expect_present=[s], kind=CheckKind.PERSISTED))
        # actual name resolution is reachability-dependent (won't work isolated)
        checks.append(StateCheck(
            "DNS resolution operational", "show hosts summary",
            kind=CheckKind.OPERATIONAL, reachability_dependent=True))
        return {"commands": cmds, "checks": checks, "warnings": warnings,
                "canonical": [f"ip name-server {s}" for s in servers],
                "provenance": ["template:cisco_ios/dns"]}


# ── NTP ──────────────────────────────────────────────────────────────────────
class CiscoIOS_NTP(Template):
    feature = "ntp"

    def synthesize(self, intent, vendor, device, current_config="", environment=None):
        env = environment or {}
        requested = intent.params.get("ntp_servers") or []
        warnings: List[str] = []
        # Prefer a reachable NTP server. In an isolated lab, a public hostname
        # like pool.ntp.org can NEVER associate (no DNS, no internet); using an
        # IP NTP peer also avoids a DNS dependency. If the environment provides a
        # reachable server, use it; otherwise keep the requested one but be
        # honest that association is reachability-dependent.
        isolated = bool(env.get("isolated"))
        env_ntp = env.get("ntp_server") or env.get("ntp_servers")
        if not requested or intent.params.get("ntp_free"):
            requested = ([env_ntp] if isinstance(env_ntp, str) else list(env_ntp or [])) \
                or list(CANONICAL_PUBLIC_NTP)
        if isolated and env_ntp:
            if not (isinstance(requested[0], str) and is_valid_ipv4(requested[0])):
                warnings.append(
                    f"isolated environment: using reachable NTP '{env_ntp}' "
                    f"instead of unreachable '{requested[0]}'")
                requested = [env_ntp] if isinstance(env_ntp, str) else list(env_ntp)
        elif isolated:
            warnings.append(
                "isolated environment: NTP server is not reachable; configuration "
                "will apply but association/sync cannot complete here")
        cmds, checks = [], []
        for i, s in enumerate(requested):
            line = f"ntp server {s}" + (" prefer" if i == 0 and len(requested) > 1 else "")
            if not _present(f"ntp server {s}", current_config):
                cmds.append(line)
        for s in requested:
            checks.append(StateCheck(
                f"NTP server {s} present", "show running-config | include ntp",
                expect_present=[str(s)], kind=CheckKind.APPLIED))
            checks.append(StateCheck(
                f"NTP server {s} persisted", "show startup-config | include ntp",
                expect_present=[str(s)], kind=CheckKind.PERSISTED))
        # association + sync depend on reachability and time → operational only.
        checks.append(StateCheck(
            "NTP association formed", "show ntp associations",
            kind=CheckKind.OPERATIONAL, reachability_dependent=True))
        checks.append(StateCheck(
            "NTP clock synchronised", "show ntp status",
            expect_present=["synchronized"], kind=CheckKind.OPERATIONAL,
            reachability_dependent=True))
        return {"commands": cmds, "checks": checks, "warnings": warnings,
                "canonical": [f"ntp server {s}" for s in requested],
                "provenance": ["template:cisco_ios/ntp"]}


# ── clock timezone ───────────────────────────────────────────────────────────
class CiscoIOS_ClockTimezone(Template):
    feature = "clock_timezone"

    def synthesize(self, intent, vendor, device, current_config="", environment=None):
        zone = intent.params.get("timezone") or "UTC"
        canon = canonical_timezone(zone)
        warnings = []
        if not canon:
            warnings.append(f"unknown timezone '{zone}', defaulting to UTC 0 0")
            canon = ("UTC", 0, 0)
        name, hh, mm = canon
        line = f"clock timezone {name} {hh} {mm}"
        cmds = [] if _present(line, current_config) else [line]
        checks = [
            StateCheck(f"timezone {name} {hh} {mm} present",
                       "show running-config | include clock timezone",
                       expect_present=[f"clock timezone {name} {hh} {mm}"],
                       kind=CheckKind.APPLIED),
            StateCheck(f"timezone {name} {hh} {mm} persisted",
                       "show startup-config | include clock timezone",
                       expect_present=[f"clock timezone {name} {hh} {mm}"],
                       kind=CheckKind.PERSISTED),
            StateCheck("clock reflects timezone", "show clock",
                       expect_present=[name], kind=CheckKind.APPLIED),
        ]
        return {"commands": cmds, "checks": checks, "warnings": warnings,
                "canonical": [line], "provenance": ["template:cisco_ios/clock_timezone"]}


class TemplateRegistry:
    def __init__(self):
        self._t: List[Template] = [
            CiscoIOS_DNS(), CiscoIOS_NTP(), CiscoIOS_ClockTimezone(),
        ]

    def register(self, t: Template) -> None:
        self._t.append(t)

    def for_intent(self, intent: ConfigIntent, vendor: str) -> List[Template]:
        return [t for t in self._t if t.applies(intent, vendor)]

    def features(self) -> List[str]:
        return sorted({t.feature for t in self._t})


def canonical_signature(canonical_lines: List[str]) -> str:
    raw = "\n".join(sorted(c.strip().lower() for c in canonical_lines))
    return hashlib.sha1(raw.encode()).hexdigest()[:16]
