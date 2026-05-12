from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional


@dataclass
class ComplianceCheck:
    name: str
    description: str
    vendor: Optional[str]
    severity: str
    validator: Callable[[Dict[str, object]], bool]


class ComplianceEngine:
    """Compliance engine for rule validation and audit scoring."""

    def __init__(self) -> None:
        self.rules: List[ComplianceCheck] = []
        self._register_default_rules()

    def _register_default_rules(self) -> None:
        self.register_rule(
            name="password-encryption",
            description="Ensure device configuration password encryption is enabled.",
            vendor=None,
            severity="high",
            validator=lambda device: device.get("password_encryption", False) is True,
        )
        self.register_rule(
            name="ssh-only-management",
            description="Management plane must use SSH only.",
            vendor=None,
            severity="medium",
            validator=lambda device: device.get("management_protocol", "ssh").lower() == "ssh",
        )
        self.register_rule(
            name="ntp-servers",
            description="Device must be configured with at least one NTP server.",
            vendor=None,
            severity="low",
            validator=lambda device: len(device.get("ntp_servers", [])) > 0,
        )
        self.register_rule(
            name="ospf-authentication",
            description="OSPF sessions must use authentication when OSPF is enabled.",
            vendor="cisco",
            severity="medium",
            validator=lambda device: not device.get("ospf_enabled", False) or device.get("ospf_auth", False),
        )

    def register_rule(
        self,
        name: str,
        description: str,
        vendor: Optional[str],
        severity: str,
        validator: Callable[[Dict[str, object]], bool],
    ) -> None:
        self.rules.append(
            ComplianceCheck(
                name=name,
                description=description,
                vendor=vendor,
                severity=severity,
                validator=validator,
            )
        )

    def evaluate_device(self, device: Dict[str, object]) -> Dict[str, object]:
        results: List[Dict[str, object]] = []
        compliant_count = 0
        total = 0
        vendor = device.get("vendor", "").lower()

        for rule in self.rules:
            if rule.vendor and rule.vendor.lower() != vendor:
                continue
            total += 1
            passed = rule.validator(device)
            if passed:
                compliant_count += 1
            results.append(
                {
                    "rule": rule.name,
                    "description": rule.description,
                    "vendor": rule.vendor or "all",
                    "severity": rule.severity,
                    "passed": passed,
                    "evaluated_at": datetime.utcnow(),
                }
            )

        score = round((compliant_count / total) * 100, 2) if total else 100.0
        return {
            "hostname": device.get("hostname", "unknown"),
            "vendor": device.get("vendor", "unknown"),
            "compliance_score": score,
            "total_rules": total,
            "passed_rules": compliant_count,
            "rule_results": results,
        }

    def compliance_score(self, devices: List[Dict[str, object]]) -> Dict[str, object]:
        details = [self.evaluate_device(device) for device in devices]
        average_score = round(sum(item["compliance_score"] for item in details) / max(1, len(details)), 2)
        return {
            "device_count": len(details),
            "average_score": average_score,
            "details": details,
        }

    def audit_summary(self, devices: List[Dict[str, object]]) -> Dict[str, object]:
        summary = self.compliance_score(devices)
        return {
            "summary_generated_at": datetime.utcnow(),
            "device_count": summary["device_count"],
            "average_score": summary["average_score"],
            "findings": [item for item in summary["details"] if item["compliance_score"] < 100.0],
        }
