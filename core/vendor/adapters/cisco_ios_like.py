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
            (Op.GET_INTERFACE_DETAILS, "lacp"): "show etherchannel summary",
            (Op.GET_INTERFACE_DETAILS, "hsrp"): "show standby brief",
            (Op.GET_INTERFACE_DETAILS, "vrrp"): "show vrrp brief",
            (Op.GET_INTERFACE_DETAILS, "stp"): "show spanning-tree",
            (Op.GET_INTERFACE_DETAILS, ""): "show ip interface brief",
            (Op.GET_ROUTING_INFORMATION, "ospf"): "show ip route ospf",
            (Op.GET_ROUTING_INFORMATION, ""): "show ip route",
            (Op.GET_CONFIGURATION, "ospf"): "show running-config | section router ospf",
            (Op.GET_CONFIGURATION, "acl"): "show access-lists",
            (Op.GET_CONFIGURATION, "nat"): "show ip nat statistics",
            (Op.GET_CONFIGURATION, ""): "show running-config",
            (Op.COLLECT_EVIDENCE, "vlan"): "show logging | include NATIVE_VLAN",
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
            elif "bgp summary" in low:
                # Real "show ip bgp summary" rows end in EITHER a digit (the
                # PfxRcd count -> the session IS Established) OR a literal
                # state name (Idle/Connect/Active/OpenSent/OpenConfirm) when
                # NOT yet established — this column-meaning ambiguity is the
                # one genuinely new parsing wrinkle vs. OSPF's neighbor table
                # (which always prints a literal state) and must be handled
                # explicitly, not assumed away.
                nbrs = []
                for line in t.splitlines():
                    m = re.search(
                        r"(\d{1,3}(?:\.\d{1,3}){3})\s+\d+\s+(\d+)\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+\S+\s+(\S+)",
                        line)
                    if not m:
                        continue
                    neighbor_ip, remote_as, tail = m.group(1), m.group(2), m.group(3)
                    state = "ESTABLISHED" if tail.isdigit() else tail.upper()
                    nbrs.append(state)
                    out.append(obj(ObjectType.NEIGHBOR, device=ip, id=neighbor_ip,
                                   protocol="bgp", state=state, remote_as=remote_as))
                out.append(obj(ObjectType.PROTOCOL, device=ip, id="bgp",
                               neighbor_count=len(nbrs),
                               adjacency=(",".join(nbrs) if nbrs else "none"),
                               state=("up" if any(n == "ESTABLISHED" for n in nbrs) else "down")))
            elif "etherchannel summary" in low:
                # Real "show etherchannel summary" rows: a Port-channel entry
                # ("Po1(SU)") followed by its MEMBER ports ("Gi0/1(P)"). Only
                # single-letter flags on a NON-"Po*" name are per-member
                # bundling states — the Port-channel's own flags (e.g. "SU")
                # are container-level (Layer2/in-use), a DIFFERENT vocabulary
                # entirely, and must not be misread as a member's state.
                # Uses ObjectType.NEIGHBOR (not INTERFACE) even though a LACP
                # member port isn't a remote "neighbor" in the OSPF/BGP sense
                # — it's the same granular, per-entity stuck-state shape
                # (Down/Individual/Suspended/Bundled) that the evidence-
                # binding pipeline already knows how to read from a
                # "neighbor.*" subject (engine.py's _gateway_object_facts);
                # ObjectType.INTERFACE's fact-extraction only surfaces
                # mtu/ip_mtu, so the granular bundling state would otherwise
                # be invisible to compiled-signature matching entirely.
                _FLAG_STATE = {"P": "BUNDLED", "I": "INDIVIDUAL", "s": "SUSPENDED", "D": "DOWN"}
                members = []
                for line in t.splitlines():
                    if not re.match(r"\s*\d+\s+Po", line):
                        continue
                    for name, flags in re.findall(r"(\S+?)\((\w+)\)", line):
                        if name.lower().startswith("po"):
                            continue                       # the channel container itself
                        if len(flags) != 1 or flags not in _FLAG_STATE:
                            continue                       # unmodeled flag (H/w/u/...) — don't guess
                        state = _FLAG_STATE[flags]
                        members.append(state)
                        out.append(obj(ObjectType.NEIGHBOR, device=ip, id=name,
                                       protocol="lacp", state=state))
                out.append(obj(ObjectType.PROTOCOL, device=ip, id="lacp",
                               neighbor_count=len(members),
                               adjacency=(",".join(members) if members else "none"),
                               state=("up" if any(m == "BUNDLED" for m in members) else "down")))
            elif "standby brief" in low:
                # Real "show standby brief" rows: interface, group, priority,
                # an OPTIONAL literal "P" column (present only if preempt is
                # configured — absent, not a placeholder character, so column
                # alignment shifts row-to-row), then the state name. Anchoring
                # on the state-name alternation (rather than counting a fixed
                # number of whitespace-separated columns) sidesteps that
                # shift entirely, the same lesson learned from LACP's flags.
                # Group id keys as "iface:group" (":" never appears in a
                # Cisco interface name) so build_fix can recover the group
                # number needed for "standby <group> preempt" syntax.
                _HSRP_ROW = re.compile(
                    r"^(?P<iface>\S+)\s+(?P<grp>\d+)\s+(?P<prio>\d+)\s+(?P<preempt>P)?\s*"
                    r"(?P<state>Init|Learn|Listen|Speak|Standby|Active)\b", re.I)
                members = []
                for line in t.splitlines():
                    m = _HSRP_ROW.match(line.strip())
                    if not m:
                        continue
                    state = m.group("state").upper()
                    members.append(state)
                    out.append(obj(ObjectType.NEIGHBOR, device=ip,
                                   id=f"{m.group('iface')}:{m.group('grp')}",
                                   protocol="hsrp", state=state,
                                   preempt_configured=("true" if m.group("preempt") else "false")))
                out.append(obj(ObjectType.PROTOCOL, device=ip, id="hsrp",
                               neighbor_count=len(members),
                               adjacency=(",".join(members) if members else "none"),
                               state=("up" if any(m == "ACTIVE" for m in members) else "down")))
            elif "vrrp brief" in low:
                # Real "show vrrp brief" rows: interface, group, priority,
                # a timer value, then two single-letter Y/N columns (Own,
                # Pre[empt]) before the state name — anchored the same way
                # as HSRP, on the state-name alternation, not fixed columns.
                _VRRP_ROW = re.compile(
                    r"^(?P<iface>\S+)\s+(?P<grp>\d+)\s+(?P<prio>\d+)\s+\S+\s+"
                    r"(?P<own>[YN])\s+(?P<pre>[YN])\s+"
                    r"(?P<state>Initialize|Backup|Master)\b", re.I)
                members = []
                for line in t.splitlines():
                    m = _VRRP_ROW.match(line.strip())
                    if not m:
                        continue
                    state = m.group("state").upper()
                    members.append(state)
                    out.append(obj(ObjectType.NEIGHBOR, device=ip,
                                   id=f"{m.group('iface')}:{m.group('grp')}",
                                   protocol="vrrp", state=state,
                                   preempt_enabled=("true" if m.group("pre").upper() == "Y" else "false")))
                out.append(obj(ObjectType.PROTOCOL, device=ip, id="vrrp",
                               neighbor_count=len(members),
                               adjacency=(",".join(members) if members else "none"),
                               state=("up" if any(m == "MASTER" for m in members) else "down")))
            elif "spanning-tree" in low:
                # Real "show spanning-tree" per-VLAN interface table: role
                # (Root/Desg/Altn/Back) then the abbreviated status (FWD/
                # BLK/LRN/LIS) — mapped back to the compiled STP model's own
                # full state names so _bind_compiled_signature_evidence's
                # state-name match works identically to every other
                # protocol above.
                _STP_STS = {"FWD": "FORWARDING", "BLK": "BLOCKING",
                           "LRN": "LEARNING", "LIS": "LISTENING"}
                members = []
                for line in t.splitlines():
                    m = re.match(r"(\S+)\s+(Root|Desg|Altn|Back)\s+(FWD|BLK|LRN|LIS)\s",
                                line.strip())
                    if not m:
                        continue
                    state = _STP_STS[m.group(3)]
                    members.append(state)
                    out.append(obj(ObjectType.NEIGHBOR, device=ip, id=m.group(1),
                                   protocol="stp", state=state, role=m.group(2)))
                out.append(obj(ObjectType.PROTOCOL, device=ip, id="stp",
                               neighbor_count=len(members),
                               adjacency=(",".join(members) if members else "none"),
                               state=("up" if any(m == "FORWARDING" for m in members) else "down")))
            elif "interfaces status" in low:
                # BPDU Guard's err-disable action never appears in "show
                # spanning-tree" (the port simply vanishes from that table)
                # — this is the ONLY command that surfaces it, as a literal
                # "err-disabled" status string. Tagged protocol="stp" since
                # BPDU Guard is an STP feature, using the SAME "neighbor.*"
                # evidence shape every other per-port/per-peer state uses.
                for line in t.splitlines():
                    m = re.match(r"(\S+)\s+.*?\berr-disabled\b", line.strip(), re.I)
                    if not m:
                        continue
                    out.append(obj(ObjectType.NEIGHBOR, device=ip, id=m.group(1),
                                   protocol="stp", state="ERRDISABLED"))
            elif "access-lists" in low:
                # Real "show access-lists" text: a header line naming the
                # ACL ("Standard/Extended IP access list <name>") followed
                # by its numbered rule lines, each optionally suffixed with
                # a "(N matches)" hit counter. Each rule becomes its own
                # ObjectType.ACL object — compile_acl_deny_signature() (core.
                # knowledge.compiler.failure_signatures) reads these
                # DIRECTLY: a deny rule IS the failure signature, not an
                # inference from a state machine, so there's no "state"
                # vocabulary to map here the way every FSM protocol above
                # needs.
                acl_name = None
                for line in t.splitlines():
                    hm = re.match(r"(?:Standard|Extended) IP access list (\S+)", line.strip())
                    if hm:
                        acl_name = hm.group(1)
                        continue
                    rm = re.match(r"(\d+)\s+(permit|deny)\s+(.*?)(?:\s*\(\d+ matches?\))?\s*$",
                                 line.strip(), re.I)
                    if rm and acl_name:
                        # Standard ACL rule text legitimately contains a literal
                        # comma ("192.168.1.0, wildcard bits 0.0.0.255") — but
                        # this object round-trips through NormalizedObject.
                        # summary()'s ", "-joined key=value text and back (see
                        # engine.py's _bind_acl_deny_evidence), which would
                        # otherwise silently truncate the rule at that comma.
                        rule_text = rm.group(3).strip().replace(",", ";")
                        out.append(obj(ObjectType.ACL, device=ip, id=f"{acl_name}-{rm.group(1)}",
                                       acl_name=acl_name, action=rm.group(2).lower(),
                                       rule=rule_text))
            elif "nat statistics" in low:
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
            elif "native_vlan" in low:
                # Real Cisco syslog line, verbatim:
                #   %CDP-4-NATIVE_VLAN_MISMATCH: Native VLAN mismatch
                #   discovered on GigabitEthernet0/1 (1), with Switch2
                #   GigabitEthernet0/1 (10).
                # CDP already did the cross-device comparison — this reads
                # its conclusion directly, not an inference of our own.
                for m in re.finditer(
                        r"NATIVE_VLAN_MISMATCH:\s*Native VLAN mismatch discovered on "
                        r"(\S+)\s*\((\d+)\),\s*with\s+(\S+)\s+(\S+)\s*\((\d+)\)", t):
                    local_if, local_vlan, remote_dev, remote_if, remote_vlan = m.groups()
                    out.append(obj("vlan_native_mismatch", device=ip,
                                   id=f"{local_if}-{remote_dev}",
                                   local_interface=local_if, local_vlan=local_vlan,
                                   remote_device=remote_dev, remote_interface=remote_if,
                                   remote_vlan=remote_vlan))
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
        return ["ignore_protocol_mtu", "set_protocol_network_point_to_point",
                "configure_ospf_interface", "enable_ospf_on_interface",
                "remove_bgp_neighbor_shutdown", "add_bgp_ebgp_multihop",
                "set_lacp_mode_active", "add_hsrp_preempt", "enable_vrrp_preempt"]

    def build_fix(self, intent: RemediationIntent, profile: VendorProfile) -> List[str]:
        proto = str(intent.params.get("protocol", "")).lower()
        iface = intent.params.get("interface", "")
        neighbor_ip = intent.params.get("neighbor_ip", "")
        # HSRP/VRRP's "neighbor" id is "iface:group" (parse_output()'s own
        # encoding, since both the interface AND the group number are
        # needed for "standby/vrrp <group> preempt" syntax) — split it back
        # apart here rather than threading a second id shape through engine.py.
        fhrp_iface, _, fhrp_group = neighbor_ip.partition(":")
        fhrp_group = fhrp_group or intent.params.get("group", "1")
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
            # BGP fixes operate under "router bgp <asn>" config mode, not an
            # interface context — local_as is optional (falls through if
            # unknown, same "context line is optional" pattern as OSPF above).
            "remove_bgp_neighbor_shutdown": (
                f"router bgp {intent.params.get('local_as', '')}"
                if intent.params.get("local_as") else None,
                f"no neighbor {neighbor_ip} shutdown"),
            "add_bgp_ebgp_multihop": (
                f"router bgp {intent.params.get('local_as', '')}"
                if intent.params.get("local_as") else None,
                f"neighbor {neighbor_ip} ebgp-multihop {intent.params.get('hops', '2')}"),
            # LACP's "neighbor" IS the member port itself (parse_output()
            # emits the port name as the NEIGHBOR subject, same shape OSPF/
            # BGP use for their own peers) — so neighbor_ip here holds the
            # interface name (e.g. "Gi0/1"), not a peer IP. Only "Individual"
            # (mode mismatch) gets an intent: "Suspended" has too many
            # possible mismatched parameters (VLAN/trunk/STP) to safely
            # auto-fix, and "Down" is a physical-layer issue outside LACP's
            # own control — same honest partial-coverage scoping OSPF/BGP use.
            "set_lacp_mode_active": (
                f"interface {neighbor_ip}" if neighbor_ip else None,
                f"channel-group {intent.params.get('channel_group', '1')} mode active"),
            # HSRP defaults preempt OFF — "won't fail over" is fixed by
            # explicitly turning it on for this group.
            "add_hsrp_preempt": (
                f"interface {fhrp_iface}" if fhrp_iface else None,
                f"standby {fhrp_group} preempt"),
            # VRRP defaults preempt ON, so a router stuck in Backup despite
            # higher priority almost always means it was explicitly disabled
            # ("no vrrp <group> preempt") — re-asserting it is the fix,
            # idempotent-safe whether or not it was actually the cause.
            "enable_vrrp_preempt": (
                f"interface {fhrp_iface}" if fhrp_iface else None,
                f"vrrp {fhrp_group} preempt"),
        }
        recipe = recipes.get(intent.name)
        if not recipe:
            return []
        return [c for c in recipe if c]

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
        if proto == "ospf":
            return ["show ip ospf neighbor"]
        if proto == "bgp":
            return ["show ip bgp summary"]
        if proto == "lacp":
            return ["show etherchannel summary"]
        if proto == "hsrp":
            return ["show standby brief"]
        if proto == "vrrp":
            return ["show vrrp brief"]
        if proto == "stp":
            return ["show spanning-tree", "show interfaces status"]
        if proto == "acl":
            return ["show access-lists"]
        if proto == "nat":
            return ["show ip nat statistics"]
        if proto == "vlan":
            return ["show logging | include NATIVE_VLAN", "show interfaces trunk"]
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
        return intent_name in {"ignore_protocol_mtu", "set_protocol_network_point_to_point",
                               "configure_ospf_interface", "enable_ospf_on_interface",
                               "remove_bgp_neighbor_shutdown", "add_bgp_ebgp_multihop",
                               "set_lacp_mode_active", "add_hsrp_preempt", "enable_vrrp_preempt"}
