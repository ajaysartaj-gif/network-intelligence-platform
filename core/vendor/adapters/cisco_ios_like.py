"""ILLUSTRATIVE reference adapter for an IOS-like CLI family.

Everything vendor-specific (detection tokens, command syntax, config syntax,
error strings) lives HERE — never in the engine or framework core.
"""
from __future__ import annotations

import re
from typing import Dict, List

from core.knowledge.compiler.protocol_registry import (
    CISCO_ADAPTER_SPECS, parse_headered_rows, parse_log_lines, parse_table_rows,
    render_remediation_fix,
)

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
        # Non-protocol-specific fallbacks — every protocol's own command
        # template lives in its ProtocolSpec.commands (protocol_registry.py)
        # instead of a shared table; adding a protocol never touches this.
        generic = {
            (Op.GET_INTERFACE_DETAILS, ""): "show ip interface brief",
            (Op.GET_ROUTING_INFORMATION, ""): "show ip route",
            (Op.GET_CONFIGURATION, ""): "show running-config",
        }
        spec = CISCO_ADAPTER_SPECS.get(proto)
        cmd = None
        if spec and operation.name in spec.commands:
            cmd = spec.commands[operation.name].format(suffix=suffix)
        if not cmd:
            cmd = generic.get((operation.name, ""))
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
            # `show interface`'s "MTU 1500 bytes" line is the interface's
            # underlying L2/hardware MTU — it does NOT reflect an `ip mtu`
            # override, which is the value OSPF's DBD exchange actually
            # checks for the classic ExStart MTU-mismatch signature. Without
            # this command, a real `ip mtu` override is invisible to the
            # adapter entirely, and only the (possibly identical-on-both-
            # sides) hardware MTU is ever compared — silently missing the
            # real mismatch or reporting a false one.
            commands.append(f"show running-config interface {scoped}" if scoped
                            else "show running-config | section ^interface")
        # BPDU Guard's err-disable action is NOT visible in "show spanning-
        # tree" at all (the port simply disappears from that output once
        # it's down) — it only shows up in "show interfaces status"'s
        # dedicated status column. Without this second command, the single
        # most commonly reported real STP complaint (an access port BPDU-
        # Guard shut down) would be structurally invisible to this adapter,
        # the same class of gap MTU was for OSPF's ExStart above.
        if operation.name == Op.GET_INTERFACE_DETAILS and proto == "stp":
            commands.append("show interfaces status")
            # The PLAIN "show interfaces status" above only ever shows a
            # Vlan NUMBER after "err-disabled", never a reason — Cisco puts
            # the actual cause (udld, bpduguard, link-flap, ...) in a
            # SEPARATE, filtered command's own Reason column. Without this,
            # every err-disabled port looks identical regardless of cause,
            # and the safe-to-auto-recover ones (UDLD/link-flap/PAgP-DTP
            # flap) can never be told apart from the ones that deliberately
            # stay fix-less (BPDU Guard, port-security violation).
            commands.append("show interfaces status err-disabled")
        return commands

    @staticmethod
    def _dispatch_registry_parser(low: str, t: str, ip: str, out: List[NormalizedObject]) -> bool:
        """Tries every ProtocolSpec's parser(s) against this command,
        stopping at the first match (same mutual-exclusivity the old
        hand-written elif chain had) — extends `out` in place, returns
        True if something matched so parse_output can skip its remaining
        bespoke branches for this command."""
        for spec in CISCO_ADAPTER_SPECS.values():
            hit = False
            for parser in spec.table_parsers:
                if parser.command_key in low:
                    out.extend(parse_table_rows(parser, t, ip))
                    hit = True
            if spec.headered_parser and spec.headered_parser.command_key in low:
                out.extend(parse_headered_rows(spec.headered_parser, t, ip))
                hit = True
            if spec.log_parser and spec.log_parser.command_key in low:
                out.extend(parse_log_lines(spec.log_parser, t, ip))
                hit = True
            if hit:
                return True
        return False

    def parse_output(self, operation: Operation, raw: Dict[str, str],
                     profile: VendorProfile) -> List[NormalizedObject]:
        ip = profile.attributes.get("ip", "")
        out: List[NormalizedObject] = []
        for cmd, text in (raw or {}).items():
            low = cmd.lower()
            t = text or ""
            if "invalid input" in t.lower() or "% " in t[:3]:
                continue                                  # error, not evidence
            # Every FSM protocol (OSPF/BGP/LACP/HSRP/VRRP/STP) plus ACL and
            # VLAN native-mismatch reduce to one of protocol_registry.py's
            # three generic parser shapes — declared once per protocol
            # there, dispatched here by command_key instead of a hand-
            # written elif branch per protocol. Adding a new protocol of
            # this shape never touches this method again.
            if self._dispatch_registry_parser(low, t, ip, out):
                continue
            if "nat statistics" in low:
                # Real "show ip nat statistics" text: an "Inside interfaces:"
                # section and an "Outside interfaces:" section, each
                # followed by indented interface-name lines (zero or more)
                # until the next unindented line. An EMPTY section here is
                # a direct, unambiguous signal — not an inference — that
                # NAT has no interface of that role at all, so nothing can
                # ever be translated regardless of any other configuration.
                inside_ifaces: List[str] = []
                outside_ifaces: List[str] = []
                section = None
                hits, misses = "0", "0"
                for line in t.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("Inside interfaces"):
                        section = "inside"
                        continue
                    if stripped.startswith("Outside interfaces"):
                        section = "outside"
                        continue
                    hm = re.match(r"Hits:\s*(\d+)\s+Misses:\s*(\d+)", stripped)
                    if hm:
                        hits, misses = hm.group(1), hm.group(2)
                        section = None
                        continue
                    if section and line[:1].isspace() and stripped:
                        (inside_ifaces if section == "inside" else outside_ifaces).append(stripped)
                    elif section and not line[:1].isspace():
                        section = None
                out.append(obj("nat", device=ip, id="nat",
                               inside_count=len(inside_ifaces), outside_count=len(outside_ifaces),
                               hits=hits, misses=misses))
            elif "ospf interface" in low:
                for block in re.split(r"\n(?=\S)", t):
                    mi = re.match(r"(\S+) is (up|down|administratively down)", block)
                    if not mi:
                        continue
                    attrs = {"status": mi.group(2).lower()}
                    for key, pat in (("mtu", r"MTU[ :]+(\d+)"), ("area", r"Area ([^\s,]+)"),
                                     ("network_type", r"Network Type (\w+)"),
                                     ("ospf_state", r"State (\S+)"),
                                     ("hello", r"Hello (\d+)"), ("dead", r"Dead (\d+)"),
                                     ("neighbor_count", r"Neighbor Count is (\d+)"),
                                     # Without this, gateway_adapter.py's
                                     # _router_id_to_device_ip() (which maps a
                                     # neighbor's OSPF router-id back to its
                                     # real management IP) always builds an
                                     # EMPTY map, since "show ip ospf neighbor"
                                     # always identifies the far end by
                                     # router-id, never by management IP —
                                     # every neighbor was silently skipped as
                                     # "not an approved device."
                                     ("router_id", r"Router ID (\d+\.\d+\.\d+\.\d+)")):
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
            elif "running-config interface" in low or ("section" in low and "interface" in low):
                # Per-interface config stanzas — extract the explicit
                # `ip mtu <n>` override. Absence here means no override is
                # configured, so the effective ip mtu equals the hardware
                # MTU (Cisco IOS's own default rule) — the caller (e.g.
                # gateway_adapter.read_parameter) is responsible for that
                # fallback, not this parser.
                for m in re.finditer(r"(?im)^interface\s+(\S+)(.*?)(?=^interface\s+\S+|\Z)", t, re.S):
                    ifname = m.group(1)
                    # Anchored to the start of a config line (after
                    # indentation) so a "description" line merely MENTIONING
                    # "ip mtu 9999" in free text — or a negated "no ip mtu
                    # 9999" line — is never misread as a real override; only
                    # an actual "ip mtu <n>" config command matches.
                    mtu_m = re.search(r"^\s*ip mtu\s+(\d+)", m.group(2), re.I | re.M)
                    if mtu_m:
                        out.append(obj(ObjectType.INTERFACE, device=ip, id=ifname,
                                       ip_mtu=mtu_m.group(1)))
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
        return [r.intent_name for spec in CISCO_ADAPTER_SPECS.values() for r in spec.recipes]

    def build_fix(self, intent: RemediationIntent, profile: VendorProfile) -> List[str]:
        proto = str(intent.params.get("protocol", "")).lower()
        spec = CISCO_ADAPTER_SPECS.get(proto)
        if not spec:
            return []
        rspec = next((r for r in spec.recipes if r.intent_name == intent.name), None)
        if not rspec:
            return []
        return render_remediation_fix(rspec, proto, intent.params)

    def build_rollback(self, intent: RemediationIntent, profile: VendorProfile) -> List[str]:
        fix = self.build_fix(intent, profile)
        if not fix:
            return []
        last = fix[-1]
        # If the fix line ITSELF negates something ("no neighbor X shutdown"),
        # the rollback must re-assert it, not prepend a second "no" ("no no
        # neighbor X shutdown" isn't valid syntax) — every prior intent's fix
        # was a positive command, so this case was previously unreachable.
        if re.match(r"^\s*no\s+", last, re.I):
            undo = re.sub(r"^\s*no\s+", "", last, count=1, flags=re.I)
        else:
            undo = f"no {last}"
        return list(fix[:-1]) + [undo]

    def build_verification(self, intent: RemediationIntent, profile: VendorProfile) -> List[str]:
        proto = str(intent.params.get("protocol", "")).lower()
        spec = CISCO_ADAPTER_SPECS.get(proto)
        return list(spec.verify_commands) if spec else []

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
        return intent_name in self.supported_intents(profile)
