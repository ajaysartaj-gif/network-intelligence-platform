"""ILLUSTRATIVE reference adapter for a JUNOS-like CLI family.

Demonstrates that the SAME normalized Operation/Intent maps to DIFFERENT vendor
syntax — proving the engine never needs to know vendor commands.
"""
from __future__ import annotations

import re
from typing import Dict, List

from ..models import (ErrorClass, NormalizedError, NormalizedObject, ObjectType,
                      ValidationResult, VendorProfile, obj)
from ..operations import Op, Operation, RemediationIntent
from ..registry import register
from ..sdk import DeviceProbe, VendorAdapter

_SIGNATURE = re.compile(r"\b(junos|juniper|mx\d+|srx\d+|ex\d+)\b", re.I)


@register
class JunosLikeAdapter(VendorAdapter):
    name = "junos-like"
    priority = 80

    def detect(self, probe: DeviceProbe) -> VendorProfile:
        blob = " ".join(str(v) for v in probe.hints.values())
        blob = re.sub(r"[^a-zA-Z0-9]+", " ", blob)   # juniper_junos -> "juniper junos"
        conf = 0.9 if _SIGNATURE.search(blob) else 0.0
        return VendorProfile(vendor="junos-like", os="junos-like", confidence=conf,
                             capabilities=self._caps(),
                             attributes={"ip": getattr(probe.device, "ip", "")})

    def _caps(self) -> List[str]:
        return ["routing.ospf", "routing.bgp", "mpls", "cli"]

    def capabilities(self, profile: VendorProfile) -> List[str]:
        return self._caps()

    def build_command(self, operation: Operation, profile: VendorProfile) -> List[str]:
        proto = str(operation.params.get("protocol", "")).lower()
        table = {
            (Op.GET_NEIGHBORS, "ospf"): "show ospf neighbor",
            (Op.GET_NEIGHBORS, "bgp"): "show bgp summary",
            (Op.GET_INTERFACE_DETAILS, ""): "show interfaces extensive",
            (Op.GET_ROUTING_INFORMATION, ""): "show route",
            (Op.GET_CONFIGURATION, ""): "show configuration",
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
                    m = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+\S+\s+(\w+)", line)
                    if m:
                        out.append(obj(ObjectType.NEIGHBOR, device=ip, id=m.group(1),
                                       protocol=operation.params.get("protocol", ""),
                                       state=m.group(2)))
        if not out:
            for cmd, text in raw.items():
                out.append(obj(ObjectType.CONFIGURATION, device=ip, id=cmd, raw=text[:500]))
        return out

    def build_fix(self, intent: RemediationIntent, profile: VendorProfile) -> List[str]:
        proto = str(intent.params.get("protocol", "")).lower()
        iface = intent.params.get("interface", "<interface>")
        # JUNOS-style set syntax — deliberately different from the ios-like adapter
        recipes = {
            "ignore_protocol_mtu": [f"set protocols {proto} area 0 interface {iface} no-check-mtu"] if proto else [],
            "set_protocol_network_point_to_point": [
                f"set protocols {proto} area 0 interface {iface} interface-type p2p"],
            "configure_ospf_interface": [
                f"set protocols {proto} area {intent.params.get('area', '0')} interface {iface}"],
        }
        return recipes.get(intent.name, [])

    def build_rollback(self, intent: RemediationIntent, profile: VendorProfile) -> List[str]:
        return [c.replace("set ", "delete ", 1) for c in self.build_fix(intent, profile)]

    def build_verification(self, intent: RemediationIntent, profile: VendorProfile) -> List[str]:
        proto = str(intent.params.get("protocol", "")).lower()
        return [f"show {proto} neighbor"] if proto else []

    def validate(self, commands: List[str], profile: VendorProfile) -> ValidationResult:
        blocked = [c for c in commands if re.search(r"\b(request system reboot|delete all)\b", c, re.I)]
        return ValidationResult(ok=not blocked, blocked=blocked)

    def translate_error(self, raw_error: str) -> NormalizedError:
        low = (raw_error or "").lower()
        if "syntax error" in low or "unknown command" in low:
            return NormalizedError(ErrorClass.CLI, raw_error, source=self.name)
        if "permission denied" in low:
            return NormalizedError(ErrorClass.PERMISSION, raw_error, source=self.name)
        return NormalizedError(ErrorClass.UNKNOWN, raw_error, raw=raw_error, source=self.name)

    def supports_intent(self, intent_name: str, profile: VendorProfile) -> bool:
        return intent_name in {"ignore_protocol_mtu", "set_protocol_network_point_to_point", "configure_ospf_interface"}
