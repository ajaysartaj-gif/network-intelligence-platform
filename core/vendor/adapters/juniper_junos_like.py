"""Junos-like adapter for a JUNOS CLI family.

Real production depth for OSPF/BGP/LACP/VRRP/STP, built the same way as
IosLikeAdapter: parsing regexes and remediation commands grounded in
verified real Junos documentation and command output (see each
JUNOS_ADAPTER_SPECS entry in protocol_registry.py for the specific
sources/reasoning behind every regex and command).

Proves core/knowledge/compiler/protocol_registry.py's ProtocolSpec/
AdapterSpec split is real, not cosmetic: this adapter shares the EXACT
same vendor-neutral protocol knowledge (state models, failure
signatures, remediation policy) as cisco_ios_like.py — only the parsing
regexes and command syntax below differ.

Deliberately does NOT support HSRP (Cisco-proprietary, no Juniper
equivalent) or ACL/NAT/VLAN-native-mismatch (real, verified architectural
differences — see protocol_registry.py's JUNOS_ADAPTER_SPECS docstring
for why each was intentionally left unbuilt rather than guessed at).
"""
from __future__ import annotations

import re
from typing import Dict, List

from core.knowledge.compiler.protocol_registry import (
    JUNOS_ADAPTER_SPECS, parse_headered_rows, parse_log_lines, parse_table_rows,
    render_remediation_fix,
)

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
        return ["routing.ospf", "routing.bgp", "switching", "cli"]

    def capabilities(self, profile: VendorProfile) -> List[str]:
        return self._caps()

    def build_command(self, operation: Operation, profile: VendorProfile) -> List[str]:
        proto = str(operation.params.get("protocol", "")).lower()
        iface = str(operation.params.get("interface", "")).strip()
        scoped = iface if iface and iface.lower() != "all" else ""
        suffix = f" {scoped}" if scoped else ""
        generic = {
            (Op.GET_INTERFACE_DETAILS, ""): "show interfaces extensive",
            (Op.GET_ROUTING_INFORMATION, ""): "show route",
            (Op.GET_CONFIGURATION, ""): "show configuration",
        }
        spec = JUNOS_ADAPTER_SPECS.get(proto)
        cmd = None
        if spec and operation.name in spec.commands:
            cmd = spec.commands[operation.name].format(suffix=suffix)
        if not cmd:
            cmd = generic.get((operation.name, ""))
        return [cmd] if cmd else []

    @staticmethod
    def _dispatch_registry_parser(low: str, t: str, ip: str, out: List[NormalizedObject]) -> bool:
        for spec in JUNOS_ADAPTER_SPECS.values():
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
            if "syntax error" in t.lower() or "unknown command" in t.lower():
                continue                                  # error, not evidence
            if self._dispatch_registry_parser(low, t, ip, out):
                continue
            out.append(obj(ObjectType.CONFIGURATION, device=ip, id=cmd, raw=t[:500]))
        if not out:
            out.append(obj(ObjectType.EVENT, device=ip, id="no_data",
                           note="no parseable data for this operation"))
        return out

    def supported_intents(self, profile: VendorProfile) -> List[str]:
        return [r.intent_name for spec in JUNOS_ADAPTER_SPECS.values() for r in spec.recipes]

    def build_fix(self, intent: RemediationIntent, profile: VendorProfile) -> List[str]:
        proto = str(intent.params.get("protocol", "")).lower()
        spec = JUNOS_ADAPTER_SPECS.get(proto)
        if not spec:
            return []
        rspec = next((r for r in spec.recipes if r.intent_name == intent.name), None)
        if not rspec:
            return []
        return render_remediation_fix(rspec, proto, intent.params)

    def build_rollback(self, intent: RemediationIntent, profile: VendorProfile) -> List[str]:
        # "set"/"activate" -> "delete"/"deactivate" is Junos's own general
        # config-hierarchy mechanism (works for ANY statement, not
        # protocol-specific) — the real rollback for anything this
        # adapter's build_fix can produce.
        fix = self.build_fix(intent, profile)
        rollback = []
        for c in fix:
            if c.startswith("set "):
                rollback.append("delete " + c[len("set "):])
            elif c.startswith("activate "):
                rollback.append("deactivate " + c[len("activate "):])
            else:
                rollback.append(f"delete {c}")
        return rollback

    def build_verification(self, intent: RemediationIntent, profile: VendorProfile) -> List[str]:
        proto = str(intent.params.get("protocol", "")).lower()
        spec = JUNOS_ADAPTER_SPECS.get(proto)
        return list(spec.verify_commands) if spec else []

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
        return intent_name in self.supported_intents(profile)
