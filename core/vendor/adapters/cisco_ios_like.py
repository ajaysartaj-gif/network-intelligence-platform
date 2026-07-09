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

    # operations this adapter cannot express as a safe IOS show are declined
    _UNSUPPORTED_OPS = {"get_telemetry", "get_inventory"}

    def supports_operation(self, operation_name: str, profile: VendorProfile) -> bool:
        return operation_name not in self._UNSUPPORTED_OPS

    def build_command(self, operation: Operation, profile: VendorProfile) -> List[str]:
        if operation.name in self._UNSUPPORTED_OPS:
            return []                                    # never emit an invalid command
        proto = str(operation.params.get("protocol", "")).lower()
        # "all" and "" both mean "every OSPF-enabled interface" — neither
        # narrows the command, so both normalize to no suffix. A genuine
        # interface name DOES narrow the command, which also makes two
        # different `interface` params produce genuinely different command
        # text (previously they collapsed to the same command regardless,
        # defeating the engine's operation-signature dedup).
        iface = str(operation.params.get("interface", "")).strip()
        scoped = iface if iface and iface.lower() != "all" else ""
        suffix = f" {scoped}" if scoped else ""
        table = {
            (Op.GET_NEIGHBORS, "ospf"): "show ip ospf neighbor",
            (Op.GET_NEIGHBORS, "bgp"): "show ip bgp summary",
            (Op.GET_INTERFACE_DETAILS, "ospf"): f"show ip ospf interface{suffix}",
            (Op.GET_INTERFACE_DETAILS, ""): "show ip interface brief",
            (Op.GET_ROUTING_INFORMATION, "ospf"): "show ip route ospf",
            (Op.GET_ROUTING_INFORMATION, ""): "show ip route",
            (Op.GET_CONFIGURATION, "ospf"): "show running-config | section router ospf",
            (Op.GET_CONFIGURATION, ""): "show running-config",
        }
        cmd = table.get((operation.name, proto)) or table.get((operation.name, ""))
        if not cmd:
            return []
        commands = [cmd]
        # `show ip ospf interface` reports area/network-type/timers/neighbor
        # count — it does NOT report MTU (confirmed against real IOS output).
        # MTU mismatch is THE textbook cause of a neighbor stuck in ExStart
        # (see core/knowledge/compiler/failure_signatures.py's compiled
        # signature, confidence 0.85), so without this second command it was
        # structurally unreachable regardless of how many times the engine
        # asked for interface details.
        if operation.name == Op.GET_INTERFACE_DETAILS and proto == "ospf":
            commands.append(f"show interface{suffix}")
        return commands

    def parse_output(self, operation: Operation, raw: Dict[str, str],
                     profile: VendorProfile) -> List[NormalizedObject]:
        ip = profile.attributes.get("ip", "")
        out: List[NormalizedObject] = []
        for cmd, text in (raw or {}).items():
            low = cmd.lower()
            t = text or ""
            if "invalid input" in t.lower() or "% " in t[:3]:
                continue                                  # error, not evidence
            if "ospf neighbor" in low:
                nbrs = []
                for line in t.splitlines():
                    m = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+\d+\s+"
                                  r"(FULL|2WAY|EXSTART|EXCHANGE|LOADING|INIT|ATTEMPT|DOWN)",
                                  line, re.I)
                    if m:
                        nbrs.append(m.group(2).upper())
                        out.append(obj(ObjectType.NEIGHBOR, device=ip, id=m.group(1),
                                       protocol="ospf", state=m.group(2).upper()))
                # neighbor_count == 0 is THE signal that OSPF is down on this device
                out.append(obj(ObjectType.PROTOCOL, device=ip, id="ospf",
                               neighbor_count=len(nbrs),
                               adjacency=(",".join(nbrs) if nbrs else "none"),
                               state=("up" if any(n == "FULL" for n in nbrs) else "down")))
            elif "ospf interface" in low:
                for block in re.split(r"\n(?=\S)", t):
                    mi = re.match(r"(\S+) is (up|down|administratively down)", block)
                    if not mi:
                        continue
                    attrs = {"status": mi.group(2).lower()}
                    for key, pat in (("mtu", r"MTU[ :]+(\d+)"), ("area", r"Area (\S+)"),
                                     ("network_type", r"Network Type (\w+)"),
                                     ("ospf_state", r"State (\S+)"),
                                     ("hello", r"Hello (\d+)"), ("dead", r"Dead (\d+)"),
                                     ("neighbor_count", r"Neighbor Count is (\d+)")):
                        mm = re.search(pat, block)
                        if mm:
                            attrs[key] = mm.group(1)
                    out.append(obj(ObjectType.INTERFACE, device=ip, id=mi.group(1),
                                   ospf=True, **attrs))
            elif low.strip() == "show interface" or low.strip().startswith("show interface "):
                # Long-form "show interface [name]" — singular, deliberately
                # distinct from "show interfaces" (plural) below, which is a
                # different tabular format. This is the ONLY command in this
                # adapter that reports MTU (confirmed: "show ip ospf interface"
                # does not).
                for block in re.split(r"\n(?=\S)", t):
                    mi = re.match(r"(\S+) is (up|down|administratively down)", block)
                    if not mi:
                        continue
                    attrs = {"status": mi.group(2).lower()}
                    mtu_m = re.search(r"MTU (\d+) bytes", block)
                    if mtu_m:
                        attrs["mtu"] = mtu_m.group(1)
                    out.append(obj(ObjectType.INTERFACE, device=ip, id=mi.group(1), **attrs))
            elif "interface brief" in low or low.strip() == "show interfaces":
                for m in re.finditer(r"(\S+)\s+\S+\s+\w+\s+\w+\s+(up|down|administratively down)\s+(up|down)", t):
                    out.append(obj(ObjectType.INTERFACE, device=ip, id=m.group(1),
                                   status=m.group(2).lower(), line_protocol=m.group(3).lower()))
            elif "section" in low or "running-config" in low:
                cfg = [ln.strip() for ln in t.splitlines()
                       if re.search(r"router ospf|network |area |passive-interface|ip ospf",
                                    ln, re.I)]
                if cfg:
                    out.append(obj(ObjectType.CONFIGURATION, device=ip, id="ospf_config",
                                   lines="; ".join(cfg[:12])))
            elif "route" in low:
                o_routes = sum(1 for ln in t.splitlines() if re.match(r"O[ *]", ln.strip()))
                out.append(obj(ObjectType.ROUTE, device=ip, id="ospf_routes",
                               protocol="ospf", count=o_routes))
        if not out:
            out.append(obj(ObjectType.EVENT, device=ip, id="no_data",
                           note="no parseable data for this operation"))
        return out

    def supported_intents(self, profile: VendorProfile) -> List[str]:
        return ["ignore_protocol_mtu", "set_protocol_network_point_to_point",
                "configure_ospf_interface", "enable_ospf_on_interface"]

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
            "enable_ospf_on_interface": (f"interface {iface}" if iface else None,
                                         f"ip {proto or 'ospf'} {intent.params.get('process', '1')} "
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
        return intent_name in {"ignore_protocol_mtu", "set_protocol_network_point_to_point", "configure_ospf_interface", "enable_ospf_on_interface"}
