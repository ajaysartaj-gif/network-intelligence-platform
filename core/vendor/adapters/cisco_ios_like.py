"""ILLUSTRATIVE reference adapter for an IOS-like CLI family.

Everything vendor-specific (detection tokens, command syntax, config syntax,
error strings) lives HERE — never in the engine or framework core.
"""
from __future__ import annotations

import re
from typing import Dict, List

from ..models import (ErrorClass, NormalizedError, NormalizedObject, ObjectType,
                      ValidationResult, VendorProfile, obj)
from ..operations import Op, Operation, RemediationIntent
from ..registry import register
from ..sdk import DeviceProbe, VendorAdapter

_SIGNATURE = re.compile(r"\b(ios|catalyst|c\d{4}|cisco)\b", re.I)


@register
class IosLikeAdapter(VendorAdapter):
    name = "ios-like"
    priority = 80

    def detect(self, probe: DeviceProbe) -> VendorProfile:
        blob = " ".join(str(v) for v in probe.hints.values())
        blob = re.sub(r"[^a-zA-Z0-9]+", " ", blob)   # cisco_ios -> "cisco ios"
        m = _SIGNATURE.search(blob)
        conf = 0.9 if m else 0.0
        ver = ""
        mv = re.search(r"version\s+([0-9][\w.()]+)", blob, re.I)
        if mv:
            ver = mv.group(1)
        return VendorProfile(vendor="ios-like", os="ios-like", version=ver,
                             confidence=conf, capabilities=self._caps(),
                             attributes={"ip": getattr(probe.device, "ip", "")})

    def _caps(self) -> List[str]:
        return ["routing.ospf", "routing.bgp", "switching", "acl", "cli"]

    def capabilities(self, profile: VendorProfile) -> List[str]:
        return self._caps()

    def build_command(self, operation: Operation, profile: VendorProfile) -> List[str]:
        proto = str(operation.params.get("protocol", "")).lower()
        table = {
            (Op.GET_NEIGHBORS, "ospf"): "show ip ospf neighbor",
            (Op.GET_NEIGHBORS, "bgp"): "show ip bgp summary",
            (Op.GET_INTERFACE_DETAILS, ""): "show interfaces",
            (Op.GET_ROUTING_INFORMATION, ""): "show ip route",
            (Op.GET_CONFIGURATION, ""): "show running-config",
        }
        cmd = table.get((operation.name, proto)) or table.get((operation.name, "")) \
            or f"show {operation.name.replace('_', ' ')}"
        return [cmd]

    def parse_output(self, operation: Operation, raw: Dict[str, str],
                     profile: VendorProfile) -> List[NormalizedObject]:
        ip = profile.attributes.get("ip", "")
        out: List[NormalizedObject] = []
        if operation.name == Op.GET_NEIGHBORS:
            for text in raw.values():
                for line in text.splitlines():
                    m = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+\d+\s+(\w+)", line)
                    if m:
                        out.append(obj(ObjectType.NEIGHBOR, device=ip, id=m.group(1),
                                       protocol=operation.params.get("protocol", ""),
                                       state=m.group(2)))
        elif operation.name == Op.GET_INTERFACE_DETAILS:
            for text in raw.values():
                for m in re.finditer(r"(\S+)\s+is\s+(up|down).*?MTU\s+(\d+)", text, re.I | re.S):
                    out.append(obj(ObjectType.INTERFACE, device=ip, id=m.group(1),
                                   status=m.group(2).lower(), mtu=int(m.group(3))))
        if not out:  # always surface something so evidence is never silently lost
            for cmd, text in raw.items():
                out.append(obj(ObjectType.CONFIGURATION, device=ip, id=cmd,
                               raw=text[:500]))
        return out

    def build_fix(self, intent: RemediationIntent, profile: VendorProfile) -> List[str]:
        proto = str(intent.params.get("protocol", "")).lower()
        iface = intent.params.get("interface", "")
        recipes = {
            "ignore_protocol_mtu": (f"interface {iface}" if iface else None,
                                    f"ip {proto} mtu-ignore"),
            "set_protocol_network_point_to_point": (f"interface {iface}" if iface else None,
                                                    f"ip {proto} network point-to-point"),
            "configure_ospf_interface": (f"interface {iface}" if iface else None,
                                         f"ip {proto} {intent.params.get('process', '1')} "
                                         f"area {intent.params.get('area', '0')}"),
        }
        recipe = recipes.get(intent.name)
        if not recipe:
            return []
        return [c for c in recipe if c]

    def build_rollback(self, intent: RemediationIntent, profile: VendorProfile) -> List[str]:
        fix = self.build_fix(intent, profile)
        # rollback = negate the last config line, keep the interface context
        if not fix:
            return []
        rb = list(fix[:-1]) + [f"no {fix[-1]}"]
        return rb

    def build_verification(self, intent: RemediationIntent, profile: VendorProfile) -> List[str]:
        proto = str(intent.params.get("protocol", "")).lower()
        if proto == "ospf":
            return ["show ip ospf neighbor"]
        return []

    def validate(self, commands: List[str], profile: VendorProfile) -> ValidationResult:
        blocked = [c for c in commands if re.search(r"\b(reload|erase|delete|debug)\b", c, re.I)]
        return ValidationResult(ok=not blocked, blocked=blocked)

    def translate_error(self, raw_error: str) -> NormalizedError:
        low = (raw_error or "").lower()
        if "% invalid input" in low or "% incomplete" in low:
            return NormalizedError(ErrorClass.CLI, raw_error, source=self.name)
        if "% permission" in low or "denied" in low:
            return NormalizedError(ErrorClass.PERMISSION, raw_error, source=self.name)
        if "authentication" in low:
            return NormalizedError(ErrorClass.AUTH, raw_error, source=self.name)
        return NormalizedError(ErrorClass.UNKNOWN, raw_error, raw=raw_error, source=self.name)

    def supports_intent(self, intent_name: str, profile: VendorProfile) -> bool:
        return intent_name in {"ignore_protocol_mtu", "set_protocol_network_point_to_point", "configure_ospf_interface"}
