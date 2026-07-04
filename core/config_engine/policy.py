"""
AI Configuration Engine — deterministic validators
==================================================
Policy Engine, Standards Validator, Conflict Detector, Configuration Validator and
Risk scoring implemented deterministically (not left to the LLM) so results are
repeatable and auditable. Vendor-neutral; operates on normalized intent only.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Dict, List

from .models import (Check, Conflict, ConfigIntent, ImpactAssessment, RiskAssessment,
                     RiskLevel, Severity)


# ── Policy Engine (org policies) ────────────────────────────────────────────────
class PolicyEngine:
    """Validates organizational policies. Rules are data-driven and overridable."""

    def __init__(self, naming_regex: str = r"^[A-Za-z][\w\-]{1,62}$",
                 require_auth_for: List[str] = None) -> None:
        self.naming_regex = re.compile(naming_regex)
        self.require_auth_for = require_auth_for or ["routing"]

    def check(self, intents: List[ConfigIntent], category: str) -> List[Check]:
        out: List[Check] = []
        for i in intents:
            name = str(i.params.get("name", "")) or i.name
            if name and not self.naming_regex.match(name.replace("_", "-")):
                out.append(Check(name="naming_standard", severity=Severity.WARN, passed=False,
                                 detail=f"'{name}' does not meet naming standard"))
        if any(c in (category or "").lower() for c in self.require_auth_for):
            if not any("auth" in str(k).lower() for i in intents for k in i.params):
                out.append(Check(name="security_policy", severity=Severity.WARN, passed=False,
                                 detail="authentication recommended for this technology but not specified"))
        if not out:
            out.append(Check(name="organizational_policy", passed=True, detail="no policy violations detected"))
        return out


# ── Standards Validator (RFC / enterprise) ──────────────────────────────────────
class StandardsValidator:
    def check(self, intents: List[ConfigIntent]) -> List[Check]:
        out: List[Check] = []
        for i in intents:
            ip = i.params.get("ip_address") or i.params.get("address")
            if ip:
                try:
                    ipaddress.ip_interface(str(ip))
                except ValueError:
                    out.append(Check(name="address_format", severity=Severity.CRITICAL,
                                     passed=False, detail=f"invalid address '{ip}'"))
        if not out:
            out.append(Check(name="standards", passed=True, detail="addressing/format checks passed"))
        return out


# ── Conflict Detector ───────────────────────────────────────────────────────────
class ConflictDetector:
    def detect(self, intents: List[ConfigIntent]) -> List[Conflict]:
        conflicts: List[Conflict] = []
        # duplicate normalized objects (same name+device)
        seen = {}
        for i in intents:
            key = (i.name, tuple(sorted(i.target_devices)),
                   str(i.params.get("name", "")) or str(i.params.get("interface", "")))
            if key in seen and key[2]:
                conflicts.append(Conflict(kind="duplicate_object",
                                          detail=f"{i.name} on {i.target_devices} duplicated",
                                          severity=Severity.WARN))
            seen[key] = True
        # address overlap
        nets = []
        for i in intents:
            ip = i.params.get("ip_address") or i.params.get("address")
            if not ip:
                continue
            try:
                net = ipaddress.ip_interface(str(ip)).network
                for prev_ip, prev_net in nets:
                    if net.overlaps(prev_net) and net != prev_net:
                        conflicts.append(Conflict(kind="address_overlap",
                                                  detail=f"{ip} overlaps {prev_ip}",
                                                  severity=Severity.CRITICAL))
                nets.append((ip, net))
            except ValueError:
                continue
        return conflicts


# ── Configuration Validator (final aggregate) ───────────────────────────────────
class ConfigurationValidator:
    def validate(self, intents: List[ConfigIntent], deps_ok: bool,
                 policy: List[Check], standards: List[Check]) -> List[Check]:
        out: List[Check] = []
        out.append(Check(name="syntax_neutral", passed=bool(intents),
                         detail="normalized intent present" if intents else "no intent generated",
                         severity=Severity.CRITICAL if not intents else Severity.INFO))
        out.append(Check(name="dependency_validation", passed=deps_ok,
                         severity=Severity.WARN if not deps_ok else Severity.INFO,
                         detail="dependencies satisfied" if deps_ok else "unsatisfied dependencies"))
        out.append(Check(name="policy_validation",
                         passed=all(c.passed for c in policy),
                         detail="policy checks aggregated"))
        out.append(Check(name="standards_validation",
                         passed=all(c.passed for c in standards),
                         detail="standards checks aggregated"))
        return out


# ── Risk scoring (deterministic) ────────────────────────────────────────────────
class RiskScorer:
    IMPACT_WEIGHTS = {
        "protocol_reset": 0.35, "downtime": 0.4, "service_impact": 0.3,
        "traffic_impact": 0.2, "performance_changes": 0.15, "resource_consumption": 0.1,
    }

    def score(self, impact: ImpactAssessment, conflicts: List[Conflict],
              scope_size: int, unresolved_missing: int, confidence: float) -> RiskAssessment:
        drivers: List[str] = []
        s = 0.0
        for f in (impact.factors if impact else []):
            w = self.IMPACT_WEIGHTS.get(f, 0.1)
            s += w
            drivers.append(f)
        crit_conflicts = [c for c in conflicts if c.severity == Severity.CRITICAL]
        if crit_conflicts:
            s += 0.4
            drivers.append(f"{len(crit_conflicts)} critical conflict(s)")
        if impact and impact.downtime_expected:
            s += 0.2
            drivers.append("expected downtime")
        if scope_size > 1:
            s += min(0.2, 0.03 * scope_size)
            drivers.append(f"multi-device scope ({scope_size})")
        if unresolved_missing:
            s += 0.25
            drivers.append("unresolved required inputs")
        s = max(0.0, min(1.0, s))
        level = (RiskLevel.CRITICAL if s >= 0.75 else RiskLevel.HIGH if s >= 0.5
                 else RiskLevel.MEDIUM if s >= 0.25 else RiskLevel.LOW)
        return RiskAssessment(level=level, score=round(s, 3), drivers=drivers,
                              confidence=round(confidence, 3))
