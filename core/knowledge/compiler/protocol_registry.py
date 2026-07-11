"""
core/knowledge/compiler/protocol_registry.py
================================================
Single declarative source of truth for every protocol/technology this
platform supports. Before this module existed, adding one protocol meant
hand-editing 7 files: protocol_models.py, failure_signatures.py, four
separate methods in cisco_ios_like.py (build_command/parse_output/
build_fix/build_verification), four separate module-level dicts in
reasoning_artifact_compiler.py, and three INDEPENDENTLY maintained
keyword lists (engine.py._detect_protocol, intent_engine.py.
_detect_scenario, hypotheses.py._STOP) that had already drifted out of
sync for real once (STP was missing from intent_engine.py's list for the
entire time its compiled signatures existed, silently making them
unreachable in production).

Now, adding a protocol means adding ONE ProtocolSpec entry to
PROTOCOL_SPECS below — no new Python control flow anywhere else.
protocol_models.py and failure_signatures.py are now thin, backward-
compatible re-export shims over this module (every existing public
function — build_protocol_model(), compile_failure_signatures(), etc. —
keeps its exact signature and behavior; nothing downstream changes).

This is a LEAF module by design (only core.knowledge.compiler.artifacts
and core.vendor.models, themselves leaves) — protocol_models.py and
failure_signatures.py import FROM here, never the reverse, so there is
no circular import between the three.

Two generic, reusable parser shapes cover every FSM protocol built so
far (OSPF/BGP/LACP/HSRP/VRRP/STP all reduce to "match a row, derive an
id and a canonical state, emit a NEIGHBOR object, optionally emit a
trailing PROTOCOL summary"):

  - TableRowParserSpec + parse_table_rows(): one row -> one NEIGHBOR
    object. multi_match=True handles LACP's shape (several
    "Gi0/1(P)" pairs on one physical line via re.finditer instead of
    one match via re.match).
  - HeaderedRowParserSpec + parse_headered_rows(): a header line
    establishes context (e.g. an ACL name), followed by numbered rows
    that inherit it. Covers ACL.
  - LogLineParserSpec + parse_log_lines(): one regex applied via
    finditer across the whole text, for a syslog-style detection.
    Covers VLAN native-mismatch.

NAT's "show ip nat statistics" section-list format (Inside/Outside
interface blocks, each an indented list until the next unindented line)
is DELIBERATELY NOT generalized into a fourth parser shape here — it has
exactly one consumer, and inventing a generic abstraction for a single
caller is the over-abstraction this registry exists to avoid. It stays
a small, dedicated function in cisco_ios_like.py. Same principle as this
package's own "don't fabricate what isn't real" discipline elsewhere:
generalize the repeated 80%, leave the genuinely protocol-specific 20%
as protocol-specific code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.knowledge.compiler.artifacts import FailureSignature, VerificationTemplate
from core.vendor.models import NormalizedObject, ObjectType, obj


# ── protocol state model (moved here from protocol_models.py; that module
# now re-exports these two names for backward compatibility) ───────────────

@dataclass
class ProtocolTransition:
    from_state: str
    to_state: str
    trigger: str


@dataclass
class ProtocolStateModel:
    protocol: str
    states: List[str] = field(default_factory=list)
    transitions: List[ProtocolTransition] = field(default_factory=list)

    def next_states(self, current: str) -> List[str]:
        current_norm = (current or "").strip().lower()
        return [t.to_state for t in self.transitions if t.from_state.lower() == current_norm]

    def is_valid_transition(self, from_state: str, to_state: str) -> bool:
        f, t = (from_state or "").lower(), (to_state or "").lower()
        return any(tr.from_state.lower() == f and tr.to_state.lower() == t for tr in self.transitions)


# ── generic parser spec #1: table rows (the shape every FSM protocol shares) ─

@dataclass
class TableRowParserSpec:
    protocol: str
    command_key: str                                   # substring match against the lowercased command
    row_pattern: str                                    # must use NAMED groups
    multi_match: bool = False                           # True: re.finditer per line (LACP); False: re.match per stripped line
    line_prefilter: Optional[str] = None                # a line must ALSO match this before row_pattern is tried
    id_template: str = "{id}"
    state_group: str = "state"
    state_map: Optional[Dict[str, str]] = None          # raw captured token -> canonical state; missing key = skip
    state_transform: Optional[Callable[[Any], Optional[str]]] = None  # wins over state_map; return None to skip
    skip_if: Optional[Callable[[Any], bool]] = None
    extra_attrs: Optional[Dict[str, Callable[[Any], Any]]] = None
    success_state: str = ""                             # canonical state meaning "up", for the PROTOCOL summary
    emit_summary: bool = True                            # STP's err-disable table has none (matches original behavior)


def parse_table_rows(spec: TableRowParserSpec, text: str, ip: str) -> List[NormalizedObject]:
    out: List[NormalizedObject] = []
    members: List[str] = []
    for line in (text or "").splitlines():
        if spec.line_prefilter and not re.match(spec.line_prefilter, line):
            continue
        if spec.multi_match:
            matches = list(re.finditer(spec.row_pattern, line))
        else:
            m = re.match(spec.row_pattern, line.strip(), re.I)
            matches = [m] if m else []
        for m in matches:
            if spec.skip_if and spec.skip_if(m):
                continue
            if spec.state_transform:
                state = spec.state_transform(m)
            elif spec.state_map is not None:
                state = spec.state_map.get(m.group(spec.state_group))
            else:
                state = m.group(spec.state_group).upper()
            if state is None:
                continue
            obj_id = spec.id_template.format(**m.groupdict())
            attrs: Dict[str, Any] = {"protocol": spec.protocol, "state": state}
            if spec.extra_attrs:
                for key, fn in spec.extra_attrs.items():
                    attrs[key] = fn(m)
            members.append(state)
            out.append(obj(ObjectType.NEIGHBOR, device=ip, id=obj_id, **attrs))
    if spec.emit_summary:
        out.append(obj(ObjectType.PROTOCOL, device=ip, id=spec.protocol,
                       neighbor_count=len(members),
                       adjacency=(",".join(members) if members else "none"),
                       state=("up" if any(m == spec.success_state for m in members) else "down")))
    return out


# ── generic parser spec #2: header + numbered rows (ACL's shape) ────────────

@dataclass
class HeaderedRowParserSpec:
    object_type: str                                    # custom NormalizedObject.type string, e.g. "acl"
    command_key: str
    header_pattern: str                                 # captures the context value, e.g. an ACL name
    header_group: str
    row_pattern: str
    id_template: str
    attrs: Dict[str, Callable[[Any, str], Any]]          # attr_name -> fn(row_match, header_value) -> value


def parse_headered_rows(spec: HeaderedRowParserSpec, text: str, ip: str) -> List[NormalizedObject]:
    out: List[NormalizedObject] = []
    header_val: Optional[str] = None
    for line in (text or "").splitlines():
        stripped = line.strip()
        hm = re.match(spec.header_pattern, stripped)
        if hm:
            header_val = hm.group(spec.header_group)
            continue
        rm = re.match(spec.row_pattern, stripped, re.I)
        if rm and header_val:
            gd = dict(rm.groupdict())
            gd[spec.header_group] = header_val
            obj_id = spec.id_template.format(**gd)
            attrs = {k: fn(rm, header_val) for k, fn in spec.attrs.items()}
            out.append(obj(spec.object_type, device=ip, id=obj_id, **attrs))
    return out


# ── generic parser spec #3: a single log line, anywhere in the text ────────

@dataclass
class LogLineParserSpec:
    object_type: str
    command_key: str
    pattern: str                                        # applied via re.finditer over the WHOLE text
    id_template: str
    attrs: Dict[str, str]                                # attr_name -> named group to copy verbatim


def parse_log_lines(spec: LogLineParserSpec, text: str, ip: str) -> List[NormalizedObject]:
    out: List[NormalizedObject] = []
    for m in re.finditer(spec.pattern, text or ""):
        gd = m.groupdict()
        obj_id = spec.id_template.format(**gd)
        attrs = {k: gd[v] for k, v in spec.attrs.items()}
        out.append(obj(spec.object_type, device=ip, id=obj_id, **attrs))
    return out


# ── remediation: one generic renderer replaces a hand-written recipe per intent ─

@dataclass
class RemediationSpec:
    intent_name: str
    trigger_state: Optional[str]           # FailureSignature.stuck_state this remediates (reasoning_artifact_compiler)
    context_template: Optional[str]        # e.g. "interface {iface}" — OPTIONAL, rendered only if context_param is truthy
    command_template: str                  # e.g. "standby {fhrp_group} preempt"
    context_param: str = "iface"           # which rendered ctx key gates the optional context line
    risk_level: str = "medium"
    defaults: Dict[str, str] = field(default_factory=dict)


def render_remediation_fix(spec: RemediationSpec, protocol: str, params: Dict[str, str]) -> List[str]:
    """Replaces cisco_ios_like.py's old per-intent `recipes` dict literal.
    Every current remediation intent (OSPF/BGP/LACP/HSRP/VRRP, 9 total)
    reduces to this one substitution: an optional context line (rendered
    only if its governing param is present — the same "context is
    optional" rule OSPF's own intents established first) plus one
    templated command line."""
    iface = str(params.get("interface", ""))
    neighbor_ip = str(params.get("neighbor_ip", ""))
    # HSRP/VRRP encode "iface:group" as their neighbor id (parse_output's
    # own choice, since both are needed for "standby/vrrp <group>
    # preempt" syntax) — split it back apart here rather than threading
    # a second id shape through engine.py.
    fhrp_iface, _, fhrp_group = neighbor_ip.partition(":")
    fhrp_group = fhrp_group or params.get("group", "1")
    ctx: Dict[str, str] = dict(spec.defaults)
    ctx.update(params)
    ctx.update(proto=protocol, iface=iface, neighbor_ip=neighbor_ip,
              fhrp_iface=fhrp_iface, fhrp_group=fhrp_group,
              local_as=params.get("local_as", ""))
    context_line = None
    if spec.context_template and ctx.get(spec.context_param):
        context_line = spec.context_template.format(**ctx)
    command_line = spec.command_template.format(**ctx)
    return [c for c in (context_line, command_line) if c]


# ── reactive (non-FSM) signature compilers — moved here from
# failure_signatures.py, which now re-exports them for backward
# compatibility. See each ProtocolSpec's reactive_compile_fn below for
# how they plug into engine.py's single _bind_reactive_evidence. ──────────

def compile_acl_deny_signature(acl_objects: List[NormalizedObject]) -> List[FailureSignature]:
    """One signature per distinct denying ACL rule, read directly from
    the compiled `acl` NormalizedObjects — a deny rule IS the signature,
    not an inference, so confidence is high."""
    signatures: List[FailureSignature] = []
    for o in acl_objects:
        if o.type != "acl" or o.get("action") != "deny":
            continue
        acl_name = o.get("acl_name", "")
        rule = o.get("rule", "")
        signatures.append(FailureSignature(
            protocol="acl", stuck_state="deny_hit",
            likely_cause=f"Traffic denied by ACL '{acl_name}' rule: {rule}",
            evidence_fields=["action", "rule"], confidence=0.9))
    return signatures


def compile_nat_role_signature(nat_objects: List[NormalizedObject]) -> List[FailureSignature]:
    """A missing 'ip nat inside' or 'ip nat outside' interface role IS the
    signature, not an inference: NAT cannot translate anything without at
    least one interface of each role configured. Deliberately has NO
    mapped remediation intent: auto-assigning a role to a GUESSED
    interface risks getting the direction backwards."""
    signatures: List[FailureSignature] = []
    for o in nat_objects:
        if o.type != "nat":
            continue
        if int(o.get("inside_count", 0) or 0) == 0:
            signatures.append(FailureSignature(
                protocol="nat", stuck_state="no_inside_interface",
                likely_cause="No interface is configured as 'ip nat inside' — NAT has "
                            "no interface to translate traffic FROM, so nothing gets "
                            "translated regardless of any other configuration",
                evidence_fields=["inside_count"], confidence=0.85))
        if int(o.get("outside_count", 0) or 0) == 0:
            signatures.append(FailureSignature(
                protocol="nat", stuck_state="no_outside_interface",
                likely_cause="No interface is configured as 'ip nat outside' — NAT has "
                            "no interface to translate traffic TO, so nothing gets "
                            "translated regardless of any other configuration",
                evidence_fields=["outside_count"], confidence=0.85))
    return signatures


def compile_vlan_native_mismatch_signature(vlan_objects: List[NormalizedObject]) -> List[FailureSignature]:
    """CDP itself already did the cross-device comparison and told us the
    two sides disagree — reads that conclusion directly, the highest
    confidence of any reactive signature since it isn't even our own
    inference. See this module's docstring for why this reads a direct
    CDP log line instead of going through the cross-device Mismatch
    Investigation machinery (core.troubleshooting.strategies.
    mismatch_bridge/gateway_adapter.py), which fundamentally requires a
    protocol-neighbor table to pair devices — a physical trunk link has
    no such concept, only a CDP/LLDP topology edge."""
    signatures: List[FailureSignature] = []
    for o in vlan_objects:
        if o.type != "vlan_native_mismatch":
            continue
        local_if, local_vlan = o.get("local_interface", "?"), o.get("local_vlan", "?")
        remote_dev, remote_if = o.get("remote_device", "?"), o.get("remote_interface", "?")
        remote_vlan = o.get("remote_vlan", "?")
        signatures.append(FailureSignature(
            protocol="vlan", stuck_state="native_vlan_mismatch",
            likely_cause=f"CDP detected a native VLAN mismatch on {local_if} (VLAN "
                        f"{local_vlan}) with {remote_dev} {remote_if} (VLAN {remote_vlan}) "
                        f"— the trunk's native VLAN must match on both ends or untagged "
                        f"traffic leaks between VLANs and STP may see it as a loop",
            evidence_fields=["local_vlan", "remote_vlan"], confidence=0.95))
    return signatures


# ── the protocol spec itself ────────────────────────────────────────────────

@dataclass
class ProtocolSpec:
    name: str
    keywords: List[str]
    state_model: Optional[ProtocolStateModel] = None
    signatures: List[FailureSignature] = field(default_factory=list)
    table_parsers: List[TableRowParserSpec] = field(default_factory=list)
    headered_parser: Optional[HeaderedRowParserSpec] = None
    log_parser: Optional[LogLineParserSpec] = None
    remediations: List[RemediationSpec] = field(default_factory=list)
    verification: Optional[VerificationTemplate] = None
    regression_states: List[str] = field(default_factory=list)
    # Op name string (e.g. "get_neighbors") -> command template, rendered
    # via str.format(suffix=...) — replaces cisco_ios_like.py's old
    # shared `table` dict's per-protocol entries.
    commands: Dict[str, str] = field(default_factory=dict)
    # The (usually shorter/simpler) command list IosLikeAdapter.
    # build_verification() returns for a DEPLOYED fix — deliberately a
    # separate field from `verification.commands` above, which is the
    # richer knowledge-artifact template (they differ for OSPF: this one
    # is just ["show ip ospf neighbor"], that one also includes the
    # interface/MTU-detail commands).
    verify_commands: List[str] = field(default_factory=list)
    # For reactive (non-FSM) protocols: a compile_fn that takes the
    # matching NormalizedObjects and returns FailureSignatures, reactively
    # bound the moment they're observed (engine.py._bind_reactive_evidence)
    # instead of seeded as a prior beforehand. None for FSM protocols.
    reactive_object_type: Optional[str] = None
    reactive_compile_fn: Optional[Callable[[List[NormalizedObject]], List[FailureSignature]]] = None
    reactive_evidence_weight: float = 0.9
    # Text used by engine.py's single generic _bind_reactive_evidence,
    # replacing what used to be 3 separately hand-written methods whose
    # only real difference was these strings.
    reactive_note_label: str = ""        # e.g. "ACL deny" -> "compiled ACL deny signature: ..."
    reactive_rationale_label: str = ""   # usually same as note_label; VLAN's differs ("VLAN native-mismatch")
    reactive_rationale_reason: str = ""  # e.g. "reads the deny rule directly, not an inference."
    reactive_evidence_reason: str = ""


# ═════════════════════════════════════════════════════════════════════════
# ── OSPF ─────────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════

_OSPF_STATE_MODEL = ProtocolStateModel(
    protocol="ospf",
    states=["Down", "Attempt", "Init", "2-Way", "ExStart", "Exchange", "Loading", "Full"],
    transitions=[
        ProtocolTransition("Down", "Attempt", "unicast hello sent (NBMA)"),
        ProtocolTransition("Down", "Init", "hello received"),
        ProtocolTransition("Attempt", "Init", "hello received"),
        ProtocolTransition("Init", "2-Way", "hello received with own router ID (bidirectional)"),
        ProtocolTransition("2-Way", "ExStart", "elected DR/BDR or point-to-point, adjacency begins"),
        ProtocolTransition("ExStart", "Exchange", "master/slave and initial sequence number negotiated"),
        ProtocolTransition("Exchange", "Loading", "DBD exchange complete, LSRs outstanding"),
        ProtocolTransition("Loading", "Full", "all LSRs satisfied"),
        ProtocolTransition("Exchange", "Full", "no LSRs needed"),
        ProtocolTransition("Full", "Down", "dead-interval expired / interface down"),
        ProtocolTransition("2-Way", "Down", "dead-interval expired"),
    ],
)

_OSPF_SIGNATURES = [
    FailureSignature(protocol="ospf", stuck_state="Down",
                     likely_cause="No hello packets exchanged — Layer 1/2 connectivity issue, "
                                 "OSPF not enabled on the interface, or an ACL blocking IP protocol 89",
                     evidence_fields=["admin_state"], confidence=0.55),
    FailureSignature(protocol="ospf", stuck_state="Attempt",
                     likely_cause="Statically configured NBMA neighbor not responding to unicast hellos",
                     evidence_fields=[], confidence=0.5),
    FailureSignature(protocol="ospf", stuck_state="Init",
                     likely_cause="Hello/dead interval or area ID mismatch between neighbors",
                     evidence_fields=["timer_type", "areas"], confidence=0.75),
    # 2-Way is often a NORMAL stable state between two DROTHERs on a
    # broadcast network (no adjacency required) — flagged only because a
    # point-to-point/point-to-multipoint network type expecting full
    # adjacency is a real, fixable misconfiguration.
    FailureSignature(protocol="ospf", stuck_state="2-Way",
                     likely_cause="Often a NORMAL stable state between two DROTHERs on a broadcast "
                                 "network (no adjacency required) — only a concern if full adjacency "
                                 "with the DR/BDR was expected and isn't forming",
                     evidence_fields=[], confidence=0.4),
    FailureSignature(protocol="ospf", stuck_state="ExStart",
                     likely_cause="MTU mismatch between OSPF neighbors prevents DBD packet exchange",
                     evidence_fields=["mtu"], confidence=0.85),
    FailureSignature(protocol="ospf", stuck_state="Exchange",
                     likely_cause="DBD sequence number mismatch or packet loss during database exchange",
                     evidence_fields=[], confidence=0.5),
    FailureSignature(protocol="ospf", stuck_state="Loading",
                     likely_cause="LSA retransmission — link congestion or packet loss (LSR/LSU unacknowledged)",
                     evidence_fields=[], confidence=0.5),
]

_OSPF_NEIGHBOR_PARSER = TableRowParserSpec(
    protocol="ospf", command_key="ospf neighbor",
    row_pattern=r"(?P<id>\d+\.\d+\.\d+\.\d+)\s+\d+\s+(?P<state>FULL|2WAY|EXSTART|EXCHANGE|LOADING|INIT|ATTEMPT|DOWN)",
    success_state="FULL",
)

_OSPF_REMEDIATIONS = [
    RemediationSpec(intent_name="ignore_protocol_mtu", trigger_state="ExStart",
                    context_template="interface {iface}", command_template="ip {proto} mtu-ignore",
                    risk_level="medium"),
    RemediationSpec(intent_name="set_protocol_network_point_to_point", trigger_state="2-Way",
                    context_template="interface {iface}",
                    command_template="ip {proto} network point-to-point", risk_level="medium"),
    RemediationSpec(intent_name="configure_ospf_interface", trigger_state="Init",
                    context_template="interface {iface}",
                    command_template="ip {proto} {process} area {area}",
                    defaults={"process": "1", "area": "0"}, risk_level="medium"),
    RemediationSpec(intent_name="enable_ospf_on_interface", trigger_state="Down",
                    context_template="interface {iface}",
                    command_template="ip ospf {process} area {area}",
                    defaults={"process": "1", "area": "0"}, risk_level="low"),
]

_OSPF_VERIFICATION = VerificationTemplate(
    protocol="ospf",
    commands=["show ip ospf neighbor", "show ip ospf interface <interface>", "show interface <interface>"],
    success_criteria="Neighbor state is Full (or 2-Way if no adjacency is required on this network type)",
    failure_indicators=["neighbor stuck below Full for longer than the dead interval",
                        "%OSPF-5-ADJCHG log messages repeating without reaching Full"],
    alternative_checks=["show ip ospf database"])


# ═════════════════════════════════════════════════════════════════════════
# ── STP ──────────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════

_STP_STATE_MODEL = ProtocolStateModel(
    protocol="stp",
    states=["Disabled", "Blocking", "Listening", "Learning", "Forwarding"],
    transitions=[
        ProtocolTransition("Disabled", "Blocking", "port enabled"),
        ProtocolTransition("Blocking", "Listening", "forward delay timer / selected as root or designated"),
        ProtocolTransition("Listening", "Learning", "forward delay timer expires"),
        ProtocolTransition("Learning", "Forwarding", "forward delay timer expires"),
        ProtocolTransition("Forwarding", "Blocking", "superior BPDU received (topology change)"),
        ProtocolTransition("Listening", "Blocking", "superior BPDU received"),
        ProtocolTransition("Learning", "Blocking", "superior BPDU received"),
    ],
)

_STP_SIGNATURES = [
    FailureSignature(protocol="stp", stuck_state="Blocking",
                     likely_cause="Superior BPDU received from another switch (legitimate redundant-"
                                 "path block, or a root-guard/BPDU-guard candidate if unexpected)",
                     evidence_fields=[], confidence=0.6),
    # "ErrDisabled" isn't one of 802.1D's own 5 FSM states (it's a Cisco
    # port-administrative action BPDU Guard takes, layered ON TOP of STP)
    # — but it's DIRECTLY observed, not inferred, so it earns a high
    # confidence the same way ACL's deny-hit signature does. Deliberately
    # has NO mapped remediation intent: blindly clearing an err-disabled
    # BPDU-Guard port could reintroduce a real bridging loop if a
    # switch/hub really was plugged into an access port — a human
    # decision, not an automatic fix.
    FailureSignature(protocol="stp", stuck_state="ErrDisabled",
                     likely_cause="Port was administratively disabled by BPDU Guard after receiving "
                                 "a BPDU on a PortFast-enabled edge port — almost always means "
                                 "either PortFast is misconfigured on a port that's actually "
                                 "connected to another switch/hub, or an unintended switch/hub "
                                 "was plugged into this access port",
                     evidence_fields=["portfast", "bpduguard"], confidence=0.8),
]

_STP_SPANNING_TREE_PARSER = TableRowParserSpec(
    protocol="stp", command_key="spanning-tree",
    row_pattern=r"(?P<id>\S+)\s+(?P<role>Root|Desg|Altn|Back)\s+(?P<state>FWD|BLK|LRN|LIS)\s",
    state_map={"FWD": "FORWARDING", "BLK": "BLOCKING", "LRN": "LEARNING", "LIS": "LISTENING"},
    extra_attrs={"role": lambda m: m.group("role")},
    success_state="FORWARDING",
)

_STP_ERRDISABLE_PARSER = TableRowParserSpec(
    protocol="stp", command_key="interfaces status",
    row_pattern=r"(?P<id>\S+)\s+.*?\berr-disabled\b",
    state_transform=lambda m: "ERRDISABLED",
    emit_summary=False,   # matches original behavior — no PROTOCOL summary from this table
)

_STP_VERIFICATION = VerificationTemplate(
    protocol="stp",
    commands=["show spanning-tree", "show interfaces status"],
    success_criteria="Port state is Forwarding for the expected root/designated role, and not err-disabled",
    failure_indicators=["port stuck in Blocking on a link expected to forward",
                        "port shows 'err-disabled' in show interfaces status (BPDU Guard triggered)"],
    alternative_checks=["show spanning-tree detail", "show errdisable recovery"])


# ═════════════════════════════════════════════════════════════════════════
# ── BGP ──────────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════

_BGP_STATE_MODEL = ProtocolStateModel(
    protocol="bgp",
    states=["Idle", "Connect", "Active", "OpenSent", "OpenConfirm", "Established"],
    transitions=[
        ProtocolTransition("Idle", "Connect", "TCP connection initiated"),
        ProtocolTransition("Connect", "Active", "TCP connection failed, retrying"),
        ProtocolTransition("Connect", "OpenSent", "TCP connection succeeded, OPEN sent"),
        ProtocolTransition("Active", "Connect", "TCP retry timer, reattempting connection"),
        ProtocolTransition("Active", "OpenSent", "TCP connection finally succeeded, OPEN sent"),
        ProtocolTransition("OpenSent", "OpenConfirm", "valid OPEN received, KEEPALIVE sent"),
        ProtocolTransition("OpenSent", "Active", "OPEN error or connection collapse"),
        ProtocolTransition("OpenConfirm", "Established", "KEEPALIVE received"),
        ProtocolTransition("OpenConfirm", "Idle", "hold timer expired / NOTIFICATION received"),
        ProtocolTransition("Established", "Idle", "hold timer expired / session reset"),
    ],
)

# Confidence grounded in real-world frequency: Active (repeated TCP
# failures — wrong neighbor IP/no route/ACL) is by far the most commonly
# reported stuck state, so it gets the highest confidence; OpenSent
# (AS/version mismatch) is comparatively rare/short-lived.
_BGP_SIGNATURES = [
    FailureSignature(protocol="bgp", stuck_state="Idle",
                     likely_cause="Neighbor administratively shut down, or no route exists to the "
                                 "peer address — BGP never even attempts to connect",
                     evidence_fields=["admin_state", "route_to_peer"], confidence=0.5),
    FailureSignature(protocol="bgp", stuck_state="Connect",
                     likely_cause="TCP port 179 appears reachable but the peer isn't completing the "
                                 "handshake — an ACL or firewall along the path is the most common cause",
                     evidence_fields=["acl"], confidence=0.6),
    FailureSignature(protocol="bgp", stuck_state="Active",
                     likely_cause="Repeated TCP connection failures to the peer address — wrong "
                                 "neighbor IP, no route to the peer, or an ACL/firewall blocking "
                                 "TCP port 179",
                     evidence_fields=["neighbor_ip", "route_to_peer", "acl"], confidence=0.7),
    FailureSignature(protocol="bgp", stuck_state="OpenSent",
                     likely_cause="Local OPEN message sent but the peer's OPEN was rejected — "
                                 "commonly a remote-AS mismatch or a BGP version mismatch",
                     evidence_fields=["remote_as"], confidence=0.55),
    FailureSignature(protocol="bgp", stuck_state="OpenConfirm",
                     likely_cause="OPEN messages exchanged but KEEPALIVE never confirmed — commonly "
                                 "an MD5 authentication mismatch or an MTU mismatch preventing "
                                 "larger BGP messages",
                     evidence_fields=["auth", "mtu"], confidence=0.6),
]

_BGP_SUMMARY_PARSER = TableRowParserSpec(
    protocol="bgp", command_key="bgp summary",
    # Real "show ip bgp summary" rows end in EITHER a digit (the PfxRcd
    # count -> the session IS Established) OR a literal state name (Idle/
    # Connect/Active/OpenSent/OpenConfirm) when NOT yet established — this
    # column-meaning ambiguity is the one genuinely new parsing wrinkle vs
    # OSPF's neighbor table (which always prints a literal state).
    row_pattern=(r"(?P<id>\d{1,3}(?:\.\d{1,3}){3})\s+\d+\s+(?P<remote_as>\d+)\s+\d+\s+\d+\s+\d+\s+"
                r"\d+\s+\d+\s+\S+\s+(?P<tail>\S+)"),
    state_transform=lambda m: "ESTABLISHED" if m.group("tail").isdigit() else m.group("tail").upper(),
    extra_attrs={"remote_as": lambda m: m.group("remote_as")},
    success_state="ESTABLISHED",
)

_BGP_REMEDIATIONS = [
    # BGP fixes operate under "router bgp <asn>" config mode, not an
    # interface context — local_as is optional (falls through if unknown,
    # same "context line is optional" pattern as OSPF's interface context).
    RemediationSpec(intent_name="remove_bgp_neighbor_shutdown", trigger_state="Idle",
                    context_template="router bgp {local_as}", context_param="local_as",
                    command_template="no neighbor {neighbor_ip} shutdown", risk_level="low"),
    RemediationSpec(intent_name="add_bgp_ebgp_multihop", trigger_state="Active",
                    context_template="router bgp {local_as}", context_param="local_as",
                    command_template="neighbor {neighbor_ip} ebgp-multihop {hops}",
                    defaults={"hops": "2"}, risk_level="medium"),
]

_BGP_VERIFICATION = VerificationTemplate(
    protocol="bgp",
    commands=["show ip bgp summary"],
    success_criteria="Neighbor state is Established",
    failure_indicators=["neighbor stuck below Established past the hold timer",
                        "%BGP-5-ADJCHANGE log messages repeating without reaching Established"],
    alternative_checks=["show ip bgp neighbors <neighbor_ip>"])


# ═════════════════════════════════════════════════════════════════════════
# ── LACP ─────────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════

_LACP_STATE_MODEL = ProtocolStateModel(
    protocol="lacp",
    states=["Down", "Individual", "Suspended", "Bundled"],
    transitions=[
        ProtocolTransition("Down", "Individual", "link up, LACP negotiation starts but partner not yet agreeing"),
        ProtocolTransition("Down", "Bundled", "link up, LACP negotiation succeeds immediately"),
        ProtocolTransition("Individual", "Bundled", "partner starts responding correctly / mode corrected"),
        ProtocolTransition("Suspended", "Bundled", "parameter mismatch on this member resolved"),
        ProtocolTransition("Bundled", "Suspended", "parameter mismatch develops (VLAN/trunk/STP inconsistency)"),
        ProtocolTransition("Bundled", "Down", "member link goes down"),
        ProtocolTransition("Individual", "Down", "member link goes down"),
    ],
)

# Individual is by far the most commonly reported LACP problem
# (community/vendor consensus: neighbor not sending LACPDUs, active/
# PAgP/passive mode mismatch, or both ends passive). Suspended is real
# but less frequently the first symptom. Down is generic.
_LACP_SIGNATURES = [
    FailureSignature(protocol="lacp", stuck_state="Individual",
                     likely_cause="Neighbor not sending LACPDUs, an LACP mode mismatch (one side "
                                 "static/PAgP while the other is LACP), or both ends configured "
                                 "passive so neither side initiates negotiation",
                     evidence_fields=["lacp_mode", "channel_protocol"], confidence=0.75),
    FailureSignature(protocol="lacp", stuck_state="Suspended",
                     likely_cause="Parameter mismatch on this member link (allowed VLANs, native "
                                 "VLAN, trunk mode, or STP-related) — the switch suspends the port "
                                 "to protect the channel rather than bundling a mismatched link",
                     evidence_fields=["allowed_vlans", "native_vlan", "trunk_mode"], confidence=0.65),
    FailureSignature(protocol="lacp", stuck_state="Down",
                     likely_cause="Member link is physically down or administratively disabled — "
                                 "Layer 1/2 issue upstream of LACP negotiation entirely",
                     evidence_fields=["admin_state"], confidence=0.4),
]

_LACP_ETHERCHANNEL_PARSER = TableRowParserSpec(
    protocol="lacp", command_key="etherchannel summary",
    # Real "show etherchannel summary" rows: a Port-channel entry
    # ("Po1(SU)") followed by its MEMBER ports ("Gi0/1(P)"). Only single-
    # letter flags on a NON-"Po*" name are per-member bundling states —
    # the Port-channel's own flags (e.g. "SU") are container-level
    # (Layer2/in-use), a DIFFERENT vocabulary, and must not be misread as
    # a member's state.
    row_pattern=r"(?P<id>\S+?)\((?P<state>\w+)\)",
    multi_match=True,
    line_prefilter=r"\s*\d+\s+Po",
    skip_if=lambda m: m.group("id").lower().startswith("po"),
    state_transform=lambda m: (
        {"P": "BUNDLED", "I": "INDIVIDUAL", "s": "SUSPENDED", "D": "DOWN"}.get(m.group("state"))
        if len(m.group("state")) == 1 else None),   # unmodeled multi-letter flag (H/w/u/...) — don't guess
    success_state="BUNDLED",
)

_LACP_REMEDIATIONS = [
    # LACP's "neighbor" IS the member port itself (parse_output emits the
    # port name as the NEIGHBOR subject) — neighbor_ip here holds the
    # interface name, not a peer IP. Only "Individual" (mode mismatch)
    # gets an intent: "Suspended" has too many possible mismatched
    # parameters to safely auto-fix, "Down" is a physical-layer issue.
    RemediationSpec(intent_name="set_lacp_mode_active", trigger_state="Individual",
                    context_template="interface {neighbor_ip}", context_param="neighbor_ip",
                    command_template="channel-group {channel_group} mode active",
                    defaults={"channel_group": "1"}, risk_level="medium"),
]

_LACP_VERIFICATION = VerificationTemplate(
    protocol="lacp",
    commands=["show etherchannel summary"],
    success_criteria="Member port flag is 'P' (Bundled) in the Port-channel",
    failure_indicators=["member port stuck at 'I' (Individual) or 's' (Suspended)"],
    alternative_checks=["show lacp neighbor"])


# ═════════════════════════════════════════════════════════════════════════
# ── HSRP ─────────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════

_HSRP_STATE_MODEL = ProtocolStateModel(
    protocol="hsrp",
    states=["Init", "Learn", "Listen", "Speak", "Standby", "Active"],
    transitions=[
        ProtocolTransition("Init", "Learn", "interface up, virtual IP not yet known"),
        ProtocolTransition("Init", "Listen", "interface up, virtual IP already configured"),
        ProtocolTransition("Learn", "Listen", "virtual IP learned from an Active router's hello"),
        ProtocolTransition("Listen", "Speak", "active/standby timer expires, no hello heard from a peer"),
        ProtocolTransition("Speak", "Standby", "lost the priority election to a peer"),
        ProtocolTransition("Speak", "Active", "won the priority election (highest priority/IP)"),
        ProtocolTransition("Standby", "Active", "Active router's hold timer expires (stops hearing hellos)"),
        ProtocolTransition("Active", "Init", "interface down / HSRP disabled"),
        ProtocolTransition("Standby", "Init", "interface down / HSRP disabled"),
    ],
)

_HSRP_SIGNATURES = [
    FailureSignature(protocol="hsrp", stuck_state="Init",
                     likely_cause="HSRP not enabled on the interface, interface administratively "
                                 "down, or the interface has no usable IP address — the FSM "
                                 "never starts",
                     evidence_fields=["admin_state"], confidence=0.45),
    FailureSignature(protocol="hsrp", stuck_state="Listen",
                     likely_cause="No HSRP hellos heard from any Active/Standby peer — commonly "
                                 "a VLAN or trunk native-VLAN misconfiguration, or an ACL "
                                 "blocking the HSRP multicast hello (UDP 1985 to 224.0.0.2) "
                                 "between the routers",
                     evidence_fields=["vlan", "acl"], confidence=0.65),
    FailureSignature(protocol="hsrp", stuck_state="Speak",
                     likely_cause="Announcing itself as a candidate but the election with a "
                                 "peer isn't completing — most often a priority tie or an "
                                 "authentication-string mismatch between the HSRP group members",
                     evidence_fields=["priority", "auth"], confidence=0.55),
    # HSRP's preempt is OFF by default — this is the single most commonly
    # reported HSRP failover complaint ("won't take over even though the
    # peer is down"), well-documented enough to earn BGP-Active-tier
    # confidence despite Standby normally being a healthy state.
    FailureSignature(protocol="hsrp", stuck_state="Standby",
                     likely_cause="Correctly Standby, but will NOT take over if the Active "
                                 "router fails, because 'standby preempt' is not configured — "
                                 "HSRP's preempt is OFF by default, so this is the single most "
                                 "commonly reported HSRP failover complaint",
                     evidence_fields=["preempt_configured"], confidence=0.7),
]

_HSRP_STANDBY_PARSER = TableRowParserSpec(
    protocol="hsrp", command_key="standby brief",
    # Real "show standby brief" rows: interface, group, priority, an
    # OPTIONAL literal "P" column (present only if preempt is configured
    # — absent, not a placeholder character, so column alignment shifts
    # row-to-row), then the state name. Anchoring on the state-name
    # alternation (not counting a fixed number of columns) sidesteps that.
    row_pattern=(r"^(?P<iface>\S+)\s+(?P<grp>\d+)\s+(?P<prio>\d+)\s+(?P<preempt>P)?\s*"
                r"(?P<state>Init|Learn|Listen|Speak|Standby|Active)\b"),
    id_template="{iface}:{grp}",
    extra_attrs={"preempt_configured": lambda m: "true" if m.group("preempt") else "false"},
    success_state="ACTIVE",
)

_HSRP_REMEDIATIONS = [
    # HSRP defaults preempt OFF — "won't fail over" is fixed by
    # explicitly turning it on for this group.
    RemediationSpec(intent_name="add_hsrp_preempt", trigger_state="Standby",
                    context_template="interface {fhrp_iface}", context_param="fhrp_iface",
                    command_template="standby {fhrp_group} preempt", risk_level="low"),
]

_HSRP_VERIFICATION = VerificationTemplate(
    protocol="hsrp",
    commands=["show standby brief"],
    success_criteria="This router shows Active, or Standby with 'preempt' configured "
                     "so it will take over if the Active router fails",
    failure_indicators=["stuck in Listen or Speak past the hold timer",
                        "Standby with no 'P' (preempt) flag when failover is expected"],
    alternative_checks=["show standby"])


# ═════════════════════════════════════════════════════════════════════════
# ── VRRP ─────────────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════

_VRRP_STATE_MODEL = ProtocolStateModel(
    protocol="vrrp",
    states=["Initialize", "Backup", "Master"],
    transitions=[
        ProtocolTransition("Initialize", "Master", "is the IP address owner, or priority 255, or no Master seen"),
        ProtocolTransition("Initialize", "Backup", "not the address owner and a Master is already present"),
        ProtocolTransition("Backup", "Master", "Master_Down_Timer expires (Master stops advertising)"),
        ProtocolTransition("Master", "Backup", "higher-priority advertisement received AND preempt is enabled"),
        ProtocolTransition("Master", "Initialize", "interface down / VRRP disabled"),
        ProtocolTransition("Backup", "Initialize", "interface down / VRRP disabled"),
    ],
)

_VRRP_SIGNATURES = [
    FailureSignature(protocol="vrrp", stuck_state="Initialize",
                     likely_cause="VRRP not enabled on the interface, interface administratively "
                                 "down, or the interface has no usable IP address — the FSM "
                                 "never starts",
                     evidence_fields=["admin_state"], confidence=0.45),
    # VRRP enables preemption BY DEFAULT (unlike HSRP) — a higher-priority
    # router stuck in Backup behind a lower-priority Master almost always
    # means preemption was explicitly disabled.
    FailureSignature(protocol="vrrp", stuck_state="Backup",
                     likely_cause="This router has a higher configured priority but remains "
                                 "Backup behind a lower-priority Master — since VRRP enables "
                                 "preemption by default, this almost always means preemption "
                                 "was explicitly disabled ('no vrrp <group> preempt') on this "
                                 "router",
                     evidence_fields=["preempt_enabled", "priority"], confidence=0.7),
]

_VRRP_BRIEF_PARSER = TableRowParserSpec(
    protocol="vrrp", command_key="vrrp brief",
    # Real "show vrrp brief" rows: interface, group, priority, a timer
    # value, then two single-letter Y/N columns (Own, Pre[empt]) before
    # the state name — anchored the same way as HSRP.
    row_pattern=(r"^(?P<iface>\S+)\s+(?P<grp>\d+)\s+(?P<prio>\d+)\s+\S+\s+"
                r"(?P<own>[YN])\s+(?P<pre>[YN])\s+(?P<state>Initialize|Backup|Master)\b"),
    id_template="{iface}:{grp}",
    extra_attrs={"preempt_enabled": lambda m: "true" if m.group("pre").upper() == "Y" else "false"},
    success_state="MASTER",
)

_VRRP_REMEDIATIONS = [
    # VRRP defaults preempt ON, so re-asserting it is idempotent-safe
    # whether or not it was actually the cause.
    RemediationSpec(intent_name="enable_vrrp_preempt", trigger_state="Backup",
                    context_template="interface {fhrp_iface}", context_param="fhrp_iface",
                    command_template="vrrp {fhrp_group} preempt", risk_level="low"),
]

_VRRP_VERIFICATION = VerificationTemplate(
    protocol="vrrp",
    commands=["show vrrp brief"],
    success_criteria="This router shows Master, or Backup with 'Pre'=Y so it will "
                     "take over if the Master fails",
    failure_indicators=["stuck in Initialize past the startup timer",
                        "Backup with 'Pre'=N despite a higher configured priority"],
    alternative_checks=["show vrrp"])


# ═════════════════════════════════════════════════════════════════════════
# ── ACL (reactive, no FSM) ──────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════

_ACL_PARSER = HeaderedRowParserSpec(
    object_type="acl", command_key="access-lists",
    header_pattern=r"(?:Standard|Extended) IP access list (?P<acl_name>\S+)",
    header_group="acl_name",
    row_pattern=r"(?P<seq>\d+)\s+(?P<action>permit|deny)\s+(?P<rule>.*?)(?:\s*\(\d+ matches?\))?\s*$",
    id_template="{acl_name}-{seq}",
    attrs={
        "acl_name": lambda m, hv: hv,
        "action": lambda m, hv: m.group("action").lower(),
        # Standard ACL rule text legitimately contains a literal comma
        # ("192.168.1.0, wildcard bits 0.0.0.255") — but this object
        # round-trips through NormalizedObject.summary()'s ", "-joined
        # key=value text and back (engine.py's _bind_reactive_evidence),
        # which would otherwise silently truncate the rule at that comma.
        "rule": lambda m, hv: m.group("rule").strip().replace(",", ";"),
    },
)


# ═════════════════════════════════════════════════════════════════════════
# ── VLAN native-mismatch (reactive, no FSM) ────────────────────────────
# ═════════════════════════════════════════════════════════════════════════

_VLAN_MISMATCH_PARSER = LogLineParserSpec(
    object_type="vlan_native_mismatch", command_key="native_vlan",
    # Real Cisco syslog line, verbatim:
    #   %CDP-4-NATIVE_VLAN_MISMATCH: Native VLAN mismatch discovered on
    #   GigabitEthernet0/1 (1), with Switch2 GigabitEthernet0/1 (10).
    # CDP already did the cross-device comparison — this reads its
    # conclusion directly, not an inference of our own.
    pattern=(r"NATIVE_VLAN_MISMATCH:\s*Native VLAN mismatch discovered on "
            r"(?P<local_if>\S+)\s*\((?P<local_vlan>\d+)\),\s*with\s+"
            r"(?P<remote_dev>\S+)\s+(?P<remote_if>\S+)\s*\((?P<remote_vlan>\d+)\)"),
    id_template="{local_if}-{remote_dev}",
    attrs={"local_interface": "local_if", "local_vlan": "local_vlan",
          "remote_device": "remote_dev", "remote_interface": "remote_if", "remote_vlan": "remote_vlan"},
)


# ═════════════════════════════════════════════════════════════════════════
# ── the registry ─────────────────────────────────────────────────────────
# ═════════════════════════════════════════════════════════════════════════

PROTOCOL_SPECS: Dict[str, ProtocolSpec] = {
    "ospf": ProtocolSpec(
        name="ospf", keywords=["ospf"], state_model=_OSPF_STATE_MODEL,
        signatures=_OSPF_SIGNATURES, table_parsers=[_OSPF_NEIGHBOR_PARSER],
        remediations=_OSPF_REMEDIATIONS, verification=_OSPF_VERIFICATION,
        regression_states=["Down"],
        commands={"get_neighbors": "show ip ospf neighbor",
                 "get_interface_details": "show ip ospf interface{suffix}",
                 "get_routing_information": "show ip route ospf",
                 "get_configuration": "show running-config | section router ospf"},
        verify_commands=["show ip ospf neighbor"]),
    "stp": ProtocolSpec(
        name="stp", keywords=["stp"], state_model=_STP_STATE_MODEL,
        signatures=_STP_SIGNATURES,
        table_parsers=[_STP_SPANNING_TREE_PARSER, _STP_ERRDISABLE_PARSER],
        remediations=[],   # no matching vendor-adapter intent exists yet, by design (see ErrDisabled's docstring)
        verification=_STP_VERIFICATION, regression_states=["Blocking", "Disabled"],
        commands={"get_interface_details": "show spanning-tree"},
        verify_commands=["show spanning-tree", "show interfaces status"]),
    "bgp": ProtocolSpec(
        name="bgp", keywords=["bgp"], state_model=_BGP_STATE_MODEL,
        signatures=_BGP_SIGNATURES, table_parsers=[_BGP_SUMMARY_PARSER],
        remediations=_BGP_REMEDIATIONS, verification=_BGP_VERIFICATION,
        regression_states=["Idle"],
        commands={"get_neighbors": "show ip bgp summary"},
        verify_commands=["show ip bgp summary"]),
    "lacp": ProtocolSpec(
        name="lacp", keywords=["lacp"], state_model=_LACP_STATE_MODEL,
        signatures=_LACP_SIGNATURES, table_parsers=[_LACP_ETHERCHANNEL_PARSER],
        remediations=_LACP_REMEDIATIONS, verification=_LACP_VERIFICATION,
        regression_states=["Down"],
        commands={"get_interface_details": "show etherchannel summary"},
        verify_commands=["show etherchannel summary"]),
    "hsrp": ProtocolSpec(
        name="hsrp", keywords=["hsrp"], state_model=_HSRP_STATE_MODEL,
        signatures=_HSRP_SIGNATURES, table_parsers=[_HSRP_STANDBY_PARSER],
        remediations=_HSRP_REMEDIATIONS, verification=_HSRP_VERIFICATION,
        regression_states=["Init"],
        commands={"get_interface_details": "show standby brief"},
        verify_commands=["show standby brief"]),
    "vrrp": ProtocolSpec(
        name="vrrp", keywords=["vrrp"], state_model=_VRRP_STATE_MODEL,
        signatures=_VRRP_SIGNATURES, table_parsers=[_VRRP_BRIEF_PARSER],
        remediations=_VRRP_REMEDIATIONS, verification=_VRRP_VERIFICATION,
        regression_states=["Initialize"],
        commands={"get_interface_details": "show vrrp brief"},
        verify_commands=["show vrrp brief"]),
    "acl": ProtocolSpec(
        name="acl", keywords=["acl"], headered_parser=_ACL_PARSER,
        reactive_object_type="acl", reactive_compile_fn=compile_acl_deny_signature,
        reactive_evidence_weight=0.9,
        reactive_note_label="ACL deny", reactive_rationale_label="ACL deny-hit",
        reactive_rationale_reason="reads the deny rule directly, not an inference.",
        reactive_evidence_reason="deny rule directly observed in ACL config — "
                                 "not an inference from a state machine",
        commands={"get_configuration": "show access-lists"},
        verify_commands=["show access-lists"]),
    # "vlan" is declared BEFORE "nat" deliberately: all_keywords() below
    # preserves dict insertion order for the plain-substring keyword scan
    # in engine.py._detect_protocol/intent_engine.py._detect_scenario, and
    # "nat" is a literal substring of "native" — a query about a "native
    # VLAN mismatch" (this exact feature's own standard terminology) would
    # falsely match "nat" first if it came before "vlan" in this dict.
    "vlan": ProtocolSpec(
        name="vlan", keywords=["vlan"], log_parser=_VLAN_MISMATCH_PARSER,
        reactive_object_type="vlan_native_mismatch", reactive_compile_fn=compile_vlan_native_mismatch_signature,
        reactive_evidence_weight=0.95,
        reactive_note_label="VLAN", reactive_rationale_label="VLAN native-mismatch",
        reactive_rationale_reason="reads CDP's own mismatch detection directly, not our own inference.",
        reactive_evidence_reason="CDP's own native-VLAN-mismatch detection, "
                                 "directly observed — not an inference",
        commands={"collect_evidence": "show logging | include NATIVE_VLAN"},
        verify_commands=["show logging | include NATIVE_VLAN", "show interfaces trunk"]),
    "nat": ProtocolSpec(
        name="nat", keywords=["nat"],
        # No parser spec here — "show ip nat statistics"'s section-list
        # format stays a dedicated function in cisco_ios_like.py (see
        # this module's docstring for why).
        reactive_object_type="nat", reactive_compile_fn=compile_nat_role_signature,
        reactive_evidence_weight=0.9,
        reactive_note_label="NAT role", reactive_rationale_label="NAT role",
        reactive_rationale_reason="reads the missing interface role directly, not an inference.",
        reactive_evidence_reason="missing interface role directly observed in "
                                 "NAT statistics — not an inference",
        commands={"get_configuration": "show ip nat statistics"},
        verify_commands=["show ip nat statistics"]),
}


def all_keywords() -> List[str]:
    """Single source of truth for protocol-detection keywords — imported
    by engine.py._detect_protocol, intent_engine.py._detect_scenario, and
    hypotheses.py's near-duplicate stopword set, replacing three
    independently-maintained lists that had already drifted out of sync
    for real once (STP was missing from one of them)."""
    kws: List[str] = []
    for spec in PROTOCOL_SPECS.values():
        kws.extend(spec.keywords)
    return kws


def get_spec(protocol: str) -> Optional[ProtocolSpec]:
    return PROTOCOL_SPECS.get((protocol or "").strip().lower())


def reactive_specs() -> List[ProtocolSpec]:
    return [s for s in PROTOCOL_SPECS.values() if s.reactive_compile_fn is not None]
