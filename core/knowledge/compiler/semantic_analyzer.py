"""
core/knowledge/compiler/semantic_analyzer.py
==============================================
Semantic Analyzer — interprets the AST (or, for already-structured formats,
a parsed dict) and extracts MEANING: protocol intent, configuration intent,
security intent, dependency intent, etc. Deterministic, regex/rule-based —
same technique core/vendor/adapters/cisco_ios_like.py already uses to parse
known show-command output, generalized here to arbitrary document/config
text instead of a fixed set of known commands.

Extractors are small, independent, registered functions — the same plugin
shape as core.intelligence.reasoning.ReasoningRegistry and
core.knowledge.vendor_router._FETCHERS. Adding a 15th extractor never
touches the other 14; a failing extractor never aborts the batch (same
resilience convention as core.knowledge.parsers.extract_text).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.knowledge.compiler.ast_builder import ASTNode
from core.knowledge.compiler.tokens import TokenType

logger_name = "NetBrain.Knowledge.Compiler.SemanticAnalyzer"


@dataclass
class SemanticFinding:
    """One extracted, still-vendor-syntax-flavored fact — the intermediate
    form between the AST and a canonical NormalizedObject. Kept distinct
    from NormalizedObject because a finding has no stable id/device/
    provenance yet; canonicalizer.py assigns those."""
    kind: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    line: int = 0
    raw_text: str = ""
    extractor: str = ""


Extractor = Callable[[ASTNode], List[SemanticFinding]]


# ── helpers shared by extractors ─────────────────────────────────────────

def _find(pattern: str, text: str, flags=re.IGNORECASE) -> Optional[re.Match]:
    return re.search(pattern, text, flags)


def _child_value(node: ASTNode, pattern: str) -> Optional[re.Match]:
    for c in node.children:
        m = _find(pattern, c.value)
        if m:
            return m
    return None


# ── 1. Interface extractor ───────────────────────────────────────────────

def interface_extractor(root: ASTNode) -> List[SemanticFinding]:
    out: List[SemanticFinding] = []
    for node in root.walk():
        m = _find(r"^interface\s+(\S+)", node.value)
        if not m:
            continue
        attrs: Dict[str, Any] = {"name": m.group(1)}

        ip_m = _child_value(node, r"ip address\s+(\d{1,3}(?:\.\d{1,3}){3})\s+"
                                   r"(\d{1,3}(?:\.\d{1,3}){3})")
        if ip_m:
            attrs["ip"], attrs["mask"] = ip_m.group(1), ip_m.group(2)

        mtu_m = _child_value(node, r"\bmtu\s+(\d+)")
        if mtu_m:
            attrs["mtu"] = int(mtu_m.group(1))

        desc_m = _child_value(node, r"description\s+(.+)$")
        if desc_m:
            attrs["description"] = desc_m.group(1).strip()

        vrf_m = _child_value(node, r"(?:ip\s+)?vrf\s+forwarding\s+(\S+)")
        if vrf_m:
            attrs["vrf"] = vrf_m.group(1)

        vlan_m = _child_value(node, r"switchport access vlan\s+(\d+)")
        if vlan_m:
            attrs["vlan"] = int(vlan_m.group(1))

        attrs["admin_state"] = "down" if _child_value(node, r"^shutdown$") else "up"

        acl_m = _child_value(node, r"ip access-group\s+(\S+)\s+(in|out)")
        if acl_m:
            attrs["acl_ref"], attrs["acl_direction"] = acl_m.group(1), acl_m.group(2)

        nat_m = _child_value(node, r"ip nat\s+(inside|outside)")
        if nat_m:
            attrs["nat_role"] = nat_m.group(1)

        svc_m = _child_value(node, r"service-policy\s+(input|output)\s+(\S+)")
        if svc_m:
            attrs["qos_policy"], attrs["qos_direction"] = svc_m.group(2), svc_m.group(1)

        out.append(SemanticFinding(kind="interface", attributes=attrs, line=node.line,
                                   raw_text=node.text_of_subtree(), extractor="interface_extractor"))
    return out


# ── 2. Protocol / neighbor / timer extractor ─────────────────────────────

_PROTOCOL_STANZA = re.compile(r"^router\s+(ospf|bgp|eigrp|isis|is-is)\s*(\S*)", re.IGNORECASE)
_NEIGHBOR_ROW = re.compile(
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s+.*?\b"
    r"(?P<state>FULL|2-WAY|EXSTART|EXCHANGE|LOADING|INIT|ATTEMPT|DOWN|"
    r"ESTABLISHED|IDLE|ACTIVE|CONNECT)\b", re.IGNORECASE)
_TIMER_LINE = re.compile(r"\b(hello-interval|dead-interval)\s+(\d+)", re.IGNORECASE)


def protocol_extractor(root: ASTNode) -> List[SemanticFinding]:
    out: List[SemanticFinding] = []
    for node in root.walk():
        stanza = _PROTOCOL_STANZA.match(node.value)
        if stanza:
            protocol, proc_id = stanza.group(1).lower(), stanza.group(2)
            networks, areas, neighbors_bgp = [], [], []
            for c in node.children:
                net_m = _find(r"network\s+(\S+)\s+(\S+)(?:\s+area\s+(\S+))?", c.value)
                if net_m:
                    networks.append(net_m.group(1))
                    if net_m.group(3):
                        areas.append(net_m.group(3))
                nbr_m = _find(r"neighbor\s+(\S+)\s+remote-as\s+(\S+)", c.value)
                if nbr_m:
                    neighbors_bgp.append({"peer": nbr_m.group(1), "remote_as": nbr_m.group(2)})
            out.append(SemanticFinding(
                kind="protocol",
                attributes={"protocol": protocol, "process_id": proc_id,
                           "networks": networks, "areas": list(dict.fromkeys(areas)),
                           "bgp_neighbors": neighbors_bgp},
                line=node.line, raw_text=node.text_of_subtree(),
                extractor="protocol_extractor"))
            continue

        nbr_row = _NEIGHBOR_ROW.search(node.value)
        if nbr_row:
            out.append(SemanticFinding(
                kind="neighbor",
                attributes={"neighbor_ip": nbr_row.group("ip"),
                           "state": nbr_row.group("state").upper()},
                line=node.line, raw_text=node.value, extractor="protocol_extractor"))

        for tm in _TIMER_LINE.finditer(node.value):
            iface_ancestor = node.parent.value if node.parent and node.parent.kind == "command" else ""
            out.append(SemanticFinding(
                kind="timer",
                attributes={"timer_type": tm.group(1).lower(), "value": int(tm.group(2)),
                           "context": iface_ancestor},
                line=node.line, raw_text=node.value, extractor="protocol_extractor"))
    return out


# ── 3. ACL extractor ──────────────────────────────────────────────────────

def acl_extractor(root: ASTNode) -> List[SemanticFinding]:
    out: List[SemanticFinding] = []
    for node in root.walk():
        m = _find(r"^access-list\s+(\d+)\s+(permit|deny)\s+(.+)$", node.value)
        if m:
            out.append(SemanticFinding(
                kind="acl_rule",
                attributes={"acl_name": m.group(1), "action": m.group(2).lower(),
                           "rule": m.group(3).strip()},
                line=node.line, raw_text=node.value, extractor="acl_extractor"))
            continue

        named_m = _find(r"^ip access-list\s+(?:extended|standard)\s+(\S+)", node.value)
        if named_m:
            acl_name = named_m.group(1)
            for c in node.children:
                rule_m = _find(r"^(permit|deny)\s+(.+)$", c.value)
                if rule_m:
                    out.append(SemanticFinding(
                        kind="acl_rule",
                        attributes={"acl_name": acl_name, "action": rule_m.group(1).lower(),
                                   "rule": rule_m.group(2).strip()},
                        line=c.line, raw_text=c.value, extractor="acl_extractor"))
    return out


# ── 4. VRF extractor ──────────────────────────────────────────────────────

def vrf_extractor(root: ASTNode) -> List[SemanticFinding]:
    out: List[SemanticFinding] = []
    for node in root.walk():
        m = _find(r"^(?:ip\s+)?vrf(?:\s+definition)?\s+(\S+)$", node.value)
        if not m:
            continue
        name = m.group(1)
        rd_m = _child_value(node, r"\brd\s+(\S+)")
        rts = []
        for c in node.children:
            rt_m = _find(r"route-target\s+(import|export|both)\s+(\S+)", c.value)
            if rt_m:
                rts.append({"type": rt_m.group(1), "value": rt_m.group(2)})
        out.append(SemanticFinding(
            kind="vrf",
            attributes={"name": name, "rd": rd_m.group(1) if rd_m else "", "route_targets": rts},
            line=node.line, raw_text=node.text_of_subtree(), extractor="vrf_extractor"))
    return out


# ── 5. VLAN extractor ─────────────────────────────────────────────────────

def vlan_extractor(root: ASTNode) -> List[SemanticFinding]:
    out: List[SemanticFinding] = []
    for node in root.walk():
        m = _find(r"^vlan\s+(\d+)$", node.value)
        if not m:
            continue
        name_m = _child_value(node, r"^name\s+(\S+)")
        out.append(SemanticFinding(
            kind="vlan",
            attributes={"id": int(m.group(1)), "name": name_m.group(1) if name_m else ""},
            line=node.line, raw_text=node.text_of_subtree(), extractor="vlan_extractor"))
    return out


# ── 6. QoS extractor ──────────────────────────────────────────────────────

def qos_extractor(root: ASTNode) -> List[SemanticFinding]:
    out: List[SemanticFinding] = []
    for node in root.walk():
        cm = _find(r"^class-map\s+(?:match-any\s+|match-all\s+)?(\S+)", node.value)
        if cm:
            out.append(SemanticFinding(
                kind="qos_class_map", attributes={"name": cm.group(1)},
                line=node.line, raw_text=node.value, extractor="qos_extractor"))
            continue
        pm = _find(r"^policy-map\s+(\S+)", node.value)
        if pm:
            classes = [c.group(1) for c in
                      (_find(r"^class\s+(\S+)", c.value) for c in node.children) if c]
            out.append(SemanticFinding(
                kind="qos_policy_map",
                attributes={"name": pm.group(1), "classes": classes},
                line=node.line, raw_text=node.text_of_subtree(), extractor="qos_extractor"))
    return out


# ── 7. NAT extractor ──────────────────────────────────────────────────────

def nat_extractor(root: ASTNode) -> List[SemanticFinding]:
    out: List[SemanticFinding] = []
    for node in root.walk():
        pool_m = _find(r"^ip nat pool\s+(\S+)\s+(\S+)\s+(\S+)", node.value)
        if pool_m:
            out.append(SemanticFinding(
                kind="nat_pool",
                attributes={"name": pool_m.group(1), "start_ip": pool_m.group(2),
                           "end_ip": pool_m.group(3)},
                line=node.line, raw_text=node.value, extractor="nat_extractor"))
            continue
        rule_m = _find(r"^ip nat inside source\s+(list|static)\s+(.+)$", node.value)
        if rule_m:
            out.append(SemanticFinding(
                kind="nat_rule",
                attributes={"kind": rule_m.group(1), "rule": rule_m.group(2).strip()},
                line=node.line, raw_text=node.value, extractor="nat_extractor"))
    return out


# ── 8. Security rule extractor ────────────────────────────────────────────

def security_rule_extractor(root: ASTNode) -> List[SemanticFinding]:
    out: List[SemanticFinding] = []
    for node in root.walk():
        m = _find(r"^ip access-group\s+(\S+)\s+(in|out)$", node.value)
        if m:
            iface = node.parent.value if node.parent and node.parent.kind == "command" else ""
            out.append(SemanticFinding(
                kind="security_rule",
                attributes={"acl_ref": m.group(1), "direction": m.group(2), "interface": iface},
                line=node.line, raw_text=node.value, extractor="security_rule_extractor"))
            continue
        zp = _find(r"^zone-pair security\s+(\S+)\s+source\s+(\S+)\s+destination\s+(\S+)", node.value)
        if zp:
            out.append(SemanticFinding(
                kind="security_rule",
                attributes={"zone_pair": zp.group(1), "source_zone": zp.group(2),
                           "dest_zone": zp.group(3)},
                line=node.line, raw_text=node.value, extractor="security_rule_extractor"))
    return out


# ── 9. State / error / warning extractor ──────────────────────────────────

_LINE_PROTOCOL = re.compile(r"line protocol is\s+(\w+)", re.IGNORECASE)


def state_error_warning_extractor(root: ASTNode) -> List[SemanticFinding]:
    out: List[SemanticFinding] = []
    for node in root.walk():
        if any(t.type == TokenType.ERROR_WORD for t in node.tokens):
            code = next(t.value for t in node.tokens if t.type == TokenType.ERROR_WORD)
            out.append(SemanticFinding(
                kind="error", attributes={"code": code, "message": node.value},
                line=node.line, raw_text=node.value, extractor="state_error_warning_extractor"))
            continue
        if any(t.type == TokenType.WARNING_WORD for t in node.tokens):
            out.append(SemanticFinding(
                kind="warning", attributes={"message": node.value},
                line=node.line, raw_text=node.value, extractor="state_error_warning_extractor"))
            continue
        lp = _LINE_PROTOCOL.search(node.value)
        if lp:
            out.append(SemanticFinding(
                kind="state", attributes={"subject": "line_protocol", "state": lp.group(1).lower()},
                line=node.line, raw_text=node.value, extractor="state_error_warning_extractor"))
    return out


# ── 10. Dependency extractor (cross-reference detection) ────────────────

_DECL_PATTERNS = {
    "acl": re.compile(r"^(?:ip access-list\s+\S+\s+(\S+)|access-list\s+(\d+))", re.IGNORECASE),
    "vrf": re.compile(r"^(?:ip\s+)?vrf(?:\s+definition)?\s+(\S+)$", re.IGNORECASE),
    "qos_policy": re.compile(r"^policy-map\s+(\S+)", re.IGNORECASE),
}


def dependency_extractor(root: ASTNode) -> List[SemanticFinding]:
    """Finds references to declared names (ACLs/VRFs/policy-maps) in other
    sections of the same document — a lightweight, deterministic stand-in
    for cross-object relationship discovery ahead of relationships.py, which
    works from already-canonicalized objects instead.

    Declarations are matched per-node (not a joined multi-line blob), and
    the declaring node itself is excluded by identity, not by re-deriving a
    second regex against its text — a broad "does this line start with
    ip/vrf/access-list" exclusion would also wrongly swallow a genuine
    reference like `ip vrf forwarding X` (which legitimately starts with
    "ip vrf" but is not the `vrf definition X` declaration)."""
    nodes = list(root.walk())
    declared: Dict[str, tuple] = {}   # name -> (kind, id(declaring_node))
    for node in nodes:
        for kind, pat in _DECL_PATTERNS.items():
            m = pat.match(node.value)
            if not m:
                continue
            name = next((g for g in m.groups() if g), None)
            if name:
                declared[name] = (kind, id(node))

    out: List[SemanticFinding] = []
    if not declared:
        return out
    for node in nodes:
        if not node.value:
            continue
        for name, (kind, decl_node_id) in declared.items():
            if id(node) == decl_node_id:
                continue
            if name in node.value:
                out.append(SemanticFinding(
                    kind="dependency",
                    attributes={"referenced_name": name, "referenced_kind": kind,
                               "referencing_text": node.value},
                    line=node.line, raw_text=node.value, extractor="dependency_extractor"))
    return out


EXTRACTORS: List[Extractor] = [
    interface_extractor,
    protocol_extractor,
    acl_extractor,
    vrf_extractor,
    vlan_extractor,
    qos_extractor,
    nat_extractor,
    security_rule_extractor,
    state_error_warning_extractor,
    dependency_extractor,
]


def analyze(root: ASTNode) -> List[SemanticFinding]:
    """Run every registered extractor over the AST. A failing extractor is
    logged and skipped — it never aborts the rest of the batch (same
    resilience convention as core.knowledge.parsers.extract_text)."""
    import logging
    logger = logging.getLogger(logger_name)
    findings: List[SemanticFinding] = []
    for extractor in EXTRACTORS:
        try:
            findings.extend(extractor(root))
        except Exception as exc:
            logger.warning(f"Extractor {extractor.__name__} failed: {exc}")
    return findings


# ── structured (JSON/YAML/XML) path — skips lexer/AST entirely ──────────

_STRUCTURED_TYPE_SIGNALS = {
    "interface": ("mtu", "ip", "address", "interface"),
    "vlan": ("vlan-id", "vlan_id", "vlan"),
    "vrf": ("rd", "route-target", "route_target", "vrf", "vrf-name"),
    "acl": ("acl", "access-list", "rules"),
}


def _guess_structured_kind(item: Dict[str, Any]) -> Optional[str]:
    keys = {k.lower() for k in item.keys()}
    for kind, signals in _STRUCTURED_TYPE_SIGNALS.items():
        if keys & set(signals):
            return kind
    return None


def analyze_structured(data: Any, source_format: str = "json") -> List[SemanticFinding]:
    """
    Semantic extraction over an already-parsed dict/list (JSON/YAML/XML),
    bypassing the lexer/AST — those formats already have a native tree.
    Heuristic: any list of homogeneous dicts is a candidate object
    collection; each item's kind is guessed from its key names, and its
    scalar fields become the finding's attributes.
    """
    findings: List[SemanticFinding] = []

    def _walk(node: Any):
        if isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, dict):
                    kind = _guess_structured_kind(item)
                    if kind:
                        attrs = {k: v for k, v in item.items()
                                if isinstance(v, (str, int, float, bool))}
                        findings.append(SemanticFinding(
                            kind=kind, attributes=attrs, line=0,
                            raw_text=str(item), extractor=f"structured:{source_format}"))
                _walk(item)

    _walk(data)
    return findings
