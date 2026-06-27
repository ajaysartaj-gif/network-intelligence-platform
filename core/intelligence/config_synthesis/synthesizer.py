"""
core/intelligence/config_synthesis/synthesizer.py
==================================================
Intent → canonical configuration, deterministically and consistently.

parse_intent() extracts structured intent from natural language with rules (the
LLM is not trusted to author syntax; at most it fills slots, validated here).
synthesize() compiles that intent through the authoritative templates into a
ConfigPlan per device — and because every device runs the SAME templates with
the SAME validated values, the canonical commands are identical across devices.
The consistency report proves it with a shared signature, so "R1 and R3 got
different configs" becomes structurally impossible.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.intelligence.config_synthesis.base import (
    Vendor, ConfigIntent, ConfigPlan, canonical_timezone, is_valid_ipv4,
)
from core.intelligence.config_synthesis.templates import (
    TemplateRegistry, canonical_signature,
)

_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_HOSTNAME_NTP = re.compile(r"\b(?:[\w-]+\.)*pool\.ntp\.org\b", re.I)
_TZ_WORDS = re.compile(r"\b(IST|UTC|GMT|PST|PDT|EST|EDT|CST|CET|JST|SGT|AEST)\b", re.I)


def parse_intent(text: str) -> ConfigIntent:
    t = (text or "").lower()
    intent = ConfigIntent(raw_text=text or "")

    # DNS
    if "dns" in t or "name-server" in t or "name server" in t or "resolver" in t:
        intent.features.append("dns")
        ips = [ip for ip in _IPV4.findall(text or "") if is_valid_ipv4(ip)]
        # if user said "free dns" / "google dns" / no explicit IPs → canonical
        if "free" in t or "public" in t or "google" in t or not ips:
            intent.params["dns_free"] = True
        if ips:
            intent.params["dns_servers"] = ips

    # NTP / clock server
    if "ntp" in t or "clock server" in t or "time server" in t or "time sync" in t:
        intent.features.append("ntp")
        ntp_hosts = _HOSTNAME_NTP.findall(text or "")
        ntp_ips = [ip for ip in _IPV4.findall(text or "") if is_valid_ipv4(ip)]
        if "free" in t or "public" in t or not (ntp_hosts or ntp_ips):
            intent.params["ntp_free"] = True
        servers = ntp_ips + ntp_hosts
        if servers:
            intent.params["ntp_servers"] = servers

    # timezone
    if "timezone" in t or "time zone" in t or "zone" in t or _TZ_WORDS.search(text or ""):
        m = _TZ_WORDS.search(text or "")
        zone = (m.group(1).upper() if m else None)
        if zone and canonical_timezone(zone):
            intent.features.append("clock_timezone")
            intent.params["timezone"] = zone

    return intent


@dataclass
class SynthesisResult:
    intent: ConfigIntent
    plans: Dict[str, ConfigPlan] = field(default_factory=dict)   # device -> plan
    consistent: bool = True
    consistency_detail: str = ""
    warnings: List[str] = field(default_factory=list)
    unsupported_features: List[str] = field(default_factory=list)

    def all_commands(self, device: str) -> List[str]:
        p = self.plans.get(device)
        return p.apply_commands if p else []


class ConfigSynthesizer:
    def __init__(self):
        self.templates = TemplateRegistry()

    def synthesize(self, intent_text: str, devices: List[str], *,
                   vendor: str = Vendor.CISCO_IOS.value,
                   current_configs: Optional[Dict[str, str]] = None,
                   environment: Optional[Dict[str, Any]] = None,
                   intent: Optional[ConfigIntent] = None) -> SynthesisResult:
        intent = intent or parse_intent(intent_text)
        current_configs = current_configs or {}
        result = SynthesisResult(intent=intent)

        templates = self.templates.for_intent(intent, vendor)
        covered = {t.feature for t in templates}
        result.unsupported_features = [f for f in intent.features if f not in covered]

        signatures: Dict[str, str] = {}
        for device in devices:
            plan = ConfigPlan(device=device, vendor=vendor,
                              features=sorted(covered))
            canon_all: List[str] = []
            cur = current_configs.get(device, "")
            for t in templates:
                frag = t.synthesize(intent, vendor, device,
                                    current_config=cur, environment=environment)
                plan.apply_commands += frag["commands"]
                plan.checks += frag["checks"]
                plan.warnings += frag["warnings"]
                plan.provenance += frag["provenance"]
                canon_all += frag["canonical"]
            plan.canonical_signature = canonical_signature(canon_all)
            signatures[device] = plan.canonical_signature
            result.plans[device] = plan
            result.warnings += [f"{device}: {w}" for w in plan.warnings]

        # consistency proof: every device's canonical commands must match.
        uniq = set(signatures.values())
        if len(uniq) <= 1:
            result.consistent = True
            result.consistency_detail = (
                f"all {len(devices)} device(s) share one canonical configuration "
                f"(signature {next(iter(uniq), '—')})")
        else:
            result.consistent = False
            groups: Dict[str, List[str]] = {}
            for d, s in signatures.items():
                groups.setdefault(s, []).append(d)
            result.consistency_detail = (
                "INCONSISTENT canonical configs across devices: " +
                "; ".join(f"{sig[:8]}→{ds}" for sig, ds in groups.items()))
        return result
