"""Generic fallback adapter — used when no vendor-specific adapter matches.

Returns a low, non-zero detection confidence so unknown devices still resolve to
*something*. It makes best-effort generic requests and never claims certainty.
"""
from __future__ import annotations

import re
from typing import Dict, List

from ..models import (ErrorClass, NormalizedError, NormalizedObject, ObjectType,
                      VendorProfile, obj)
from ..operations import Op, Operation, RemediationIntent
from ..registry import register
from ..sdk import DeviceProbe, VendorAdapter


@register
class GenericCliAdapter(VendorAdapter):
    name = "generic-cli"
    priority = 1  # lowest — only wins when nothing else matches

    def detect(self, probe: DeviceProbe) -> VendorProfile:
        return VendorProfile(vendor="generic", os="unknown", confidence=0.05,
                             capabilities=["cli"])

    def capabilities(self, profile: VendorProfile) -> List[str]:
        return ["cli"]

    def build_command(self, operation: Operation, profile: VendorProfile) -> List[str]:
        proto = str(operation.params.get("protocol", "")).strip()
        mapping = {
            Op.GET_NEIGHBORS: f"show {proto} neighbor".strip(),
            Op.GET_INTERFACE_DETAILS: "show interfaces",
            Op.GET_ROUTING_INFORMATION: "show route",
            Op.GET_CONFIGURATION: "show configuration",
        }
        return [mapping.get(operation.name, f"show {operation.name.replace('_', ' ')}")]

    def parse_output(self, operation, raw: Dict[str, str], profile) -> List[NormalizedObject]:
        out: List[NormalizedObject] = []
        for cmd, text in (raw or {}).items():
            for line in (text or "").splitlines():
                line = line.strip()
                if line:
                    out.append(obj(ObjectType.EVENT, id=cmd,
                                   device=profile.attributes.get("ip", ""), line=line))
        return out

    def build_fix(self, intent: RemediationIntent, profile) -> List[str]:
        # Generic adapter cannot safely synthesize vendor config; it declines.
        return []

    def build_rollback(self, intent: RemediationIntent, profile) -> List[str]:
        return []

    def translate_error(self, raw_error: str) -> NormalizedError:
        low = (raw_error or "").lower()
        cls = ErrorClass.UNKNOWN
        if "permission" in low or "denied" in low:
            cls = ErrorClass.PERMISSION
        elif "timeout" in low or "timed out" in low:
            cls = ErrorClass.TIMEOUT
        elif "auth" in low:
            cls = ErrorClass.AUTH
        return NormalizedError(error_class=cls, message=raw_error, raw=raw_error,
                               source=self.name)

    def supports_intent(self, intent_name: str, profile: VendorProfile) -> bool:
        return False  # generic never fabricates remediation
