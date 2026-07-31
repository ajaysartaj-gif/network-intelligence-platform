"""
Automated completeness checker for compiled protocol knowledge.

Codifies, as an executable check, the exact 3-question audit worked out by
hand for OSPF: that session found a FailureSignature mis-tagged to the
wrong FSM state, an evidence_fields entry naming a nonexistent attribute
("areas" vs the adapter's real "area"), and 2 of 8 Mismatch Investigation
parameters declared but structurally unreadable or unfixable. Re-doing that
research by hand for every protocol doesn't scale — this runs the same
three checks in seconds against everything already compiled, and against
whatever a future protocol's auto-drafted knowledge produces.

    1. state-tag correctness — every FailureSignature.stuck_state is a real
       FSM state for its protocol; no two signatures share verbatim
       likely_cause text; evidence_fields entries line up with the
       protocol's own READ_INTENT_ATTR values where one exists.
    2. readability — every corpus PARAM's read_intent has a
       READ_INTENT_ATTR entry, and that attribute is actually emitted by
       the Cisco adapter (checked structurally: a TableRowParserSpec named
       group/extra_attr, or found in the adapter module's own source text).
    3. fixability — every corpus PARAM name has an _INTENT_FOR_PARAM entry,
       and that intent_name is a real RemediationRecipe for the protocol.
"""
from __future__ import annotations

import inspect
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from core.knowledge.compiler.protocol_registry import CISCO_ADAPTER_SPECS, JUNOS_ADAPTER_SPECS, PROTOCOL_SPECS

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_CORPUS_DIR = os.path.join(_REPO_ROOT, "corpus")


@dataclass
class Gap:
    subject: str            # protocol name or relationship_type
    check: str               # "state_tag" | "readability" | "fixability"
    detail: str
    severity: str = "error"  # "error" blocks; "warning" is flagged for review


@dataclass
class Report:
    subject: str
    gaps: List[Gap] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not any(g.severity == "error" for g in self.gaps)


def _parse_corpus_params(path: str) -> List[Dict[str, str]]:
    """Same PARAM: line schema as knowledge/rag_engine.py's StubExtractor,
    read directly off disk — no retriever/embedding machinery needed for a
    structural completeness check."""
    params: List[Dict[str, str]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("PARAM:"):
                continue
            fields = [x.strip() for x in line[len("PARAM:"):].split("|")]
            if len(fields) < 4:
                continue
            params.append({"name": fields[0], "relation": fields[1],
                           "fatal": fields[2], "read_intent": fields[3]})
    return params


def _adapter_emitted_attrs(protocol: str) -> Tuple[Set[str], str]:
    """Attribute names structurally known to be emitted for this protocol:
    TableRowParserSpec extra_attrs keys + row_pattern named groups (from the
    vendor-neutral registry), plus the raw source text of the Cisco adapter
    module as a fallback for attributes parsed by inline per-protocol
    functions (e.g. OSPF's `show ip ospf interface` parsing) that aren't
    represented as a TableRowParserSpec at all."""
    attrs: Set[str] = set()
    spec = CISCO_ADAPTER_SPECS.get(protocol)
    if spec:
        for tp in getattr(spec, "table_parsers", None) or []:
            attrs.update((getattr(tp, "extra_attrs", None) or {}).keys())
            attrs.update(re.findall(r"\(\?P<(\w+)>", getattr(tp, "row_pattern", "") or ""))
    try:
        from core.vendor.adapters import cisco_ios_like
        full_src = inspect.getsource(cisco_ios_like)
    except Exception:
        full_src = ""
    # Scope the free-text fallback to only the elif branch(es) that mention
    # this protocol's name — searching the WHOLE module lets one protocol's
    # genuinely-emitted attribute (e.g. HSRP's "auth") make an unrelated
    # protocol's attribute of the identical name (OSPF's "auth", which
    # OSPF's own parser never actually emits) look falsely reachable too.
    # parse_output's branches are one long if/elif chain, so splitting on
    # "elif " boundaries and keeping only protocol-mentioning chunks is a
    # reasonable proxy for "this protocol's parsing branch" without a full
    # AST walk.
    chunks = re.split(r"\n(?=\s*elif )", full_src)
    src = "\n".join(c for c in chunks if protocol in c.lower())
    return attrs, src


def _attr_reachable(attr: str, attrs: Set[str], src: str) -> bool:
    if attr in attrs:
        return True
    # Heuristic fallback: attribute name appears either as a quoted
    # dict/tuple key (`("area", r"...")`) or a dict-subscript assignment
    # (`attrs["virtual_ip"] = ...`) anywhere in the adapter's own source —
    # the two real emission styles this adapter uses. Exactly how the OSPF
    # ospf_auth/ospf_network_mask gap was found by hand (they never appear
    # either way in cisco_ios_like.py).
    needle = re.escape(attr)
    return bool(re.search(rf'["\']{needle}["\']\s*[:,\]]', src))


def _recipe_intent_names(protocol: str) -> Set[str]:
    names: Set[str] = set()
    for specs in (CISCO_ADAPTER_SPECS, JUNOS_ADAPTER_SPECS):
        spec = specs.get(protocol)
        if spec:
            names.update(r.intent_name for r in getattr(spec, "recipes", None) or [])
    return names


def check_protocol_signatures(protocol: str) -> Report:
    """Check 1: state-tag correctness for one compiled protocol's
    FailureSignatures. Protocols with no state_model (the reactive ones —
    acl/vlan/nat) have no FSM state to mis-tag, but that's not the same as
    nothing to check: this used to return a silent "clean" report
    regardless of whether the protocol could ever produce a fix at all — a
    real blind spot (ACL and NAT can both DETECT their failure for real,
    but neither has ever had a remediation path, and that gap was
    invisible here until asked for directly)."""
    report = Report(subject=protocol)
    spec = PROTOCOL_SPECS.get(protocol)
    if spec is None:
        return report
    if spec.state_model is None:
        if spec.reactive_compile_fn and not spec.remediation_policies:
            report.gaps.append(Gap(
                protocol, "fixability",
                f"{protocol!r} is a reactive (non-FSM) protocol with zero "
                f"RemediationPolicy entries — confirm this is a deliberate safety "
                f"decision (ACL/NAT's own precedent: guessing which rule/interface to "
                f"auto-fix risks getting it backwards or opening a security hole, "
                f"worse than no fix) rather than an oversight",
                severity="warning"))
        return report
    if not spec.signatures:
        return report
    states = set(spec.state_model.states)

    from core.troubleshooting.strategies.gateway_adapter import READ_INTENT_ATTR, RELATIONSHIP_PROTOCOL
    # Only meaningful for protocols the Mismatch Investigation actually
    # covers today (RELATIONSHIP_PROTOCOL's value set) — for every other
    # protocol, READ_INTENT_ATTR has nothing to do with it at all, so
    # cross-checking evidence_fields against it would just warn on every
    # single signature of every uncovered protocol (pure noise, not a
    # real finding). Not prefix-filtered by protocol name either: some
    # read_intents are shared across protocols by design (e.g.
    # "interface_mtu" -> "mtu" applies to OSPF, LACP, any interface-scoped
    # protocol) and wouldn't start with this protocol's own name.
    read_attrs = set(READ_INTENT_ATTR.values()) if protocol in set(RELATIONSHIP_PROTOCOL.values()) else set()

    seen_causes: Dict[str, int] = {}
    for sig in spec.signatures:
        if sig.stuck_state not in states:
            # Not always a bug: STP's ErrDisabled/ErrDisabledLinkIntegrity
            # are deliberate Cisco pseudo-states layered on top of 802.1D's
            # own 5-state FSM for a directly-observed condition (see that
            # signature's own comment in protocol_registry.py) — flagged
            # for human/architectural review, not auto-rejected, since a
            # mis-tagged state (the real OSPF "Init" bug this check is
            # modeled on) looks identical to a deliberate extension here.
            report.gaps.append(Gap(
                protocol, "state_tag",
                f"FailureSignature.stuck_state {sig.stuck_state!r} is not a real state in "
                f"{protocol}'s ProtocolStateModel {sorted(states)} — either a mis-tagged "
                f"signature or a deliberate vendor-specific pseudo-state; needs review",
                severity="warning"))
        seen_causes[sig.likely_cause] = seen_causes.get(sig.likely_cause, 0) + 1
        if read_attrs:
            for ev in sig.evidence_fields:
                if ev not in read_attrs and ev not in states:
                    report.gaps.append(Gap(
                        protocol, "state_tag",
                        f"evidence_fields entry {ev!r} on the {sig.stuck_state!r} signature "
                        f"doesn't match any READ_INTENT_ATTR value declared for {protocol} "
                        f"({sorted(read_attrs)}) — possible naming mismatch",
                        severity="warning"))
    for cause, count in seen_causes.items():
        if count > 1:
            report.gaps.append(Gap(
                protocol, "state_tag",
                f"likely_cause text {cause!r} appears on {count} separate FailureSignature "
                f"entries — likely accidental duplication"))
    return report


def check_corpus_completeness(relationship_type: str) -> Report:
    """Checks 2 (readability) and 3 (fixability) for one Mismatch
    Investigation corpus file."""
    from core.troubleshooting.strategies.gateway_adapter import (
        READ_INTENT_ATTR, RELATIONSHIP_PROTOCOL, _INTENT_FOR_PARAM,
    )
    report = Report(subject=relationship_type)
    protocol = RELATIONSHIP_PROTOCOL.get(relationship_type, relationship_type)
    path = os.path.join(_CORPUS_DIR, f"{relationship_type}.txt")
    if not os.path.exists(path):
        report.gaps.append(Gap(relationship_type, "readability", f"no corpus file at {path}"))
        return report

    params = _parse_corpus_params(path)
    attrs, src = _adapter_emitted_attrs(protocol)
    recipe_names = _recipe_intent_names(protocol)

    for p in params:
        attr = READ_INTENT_ATTR.get(p["read_intent"])
        if attr is None:
            report.gaps.append(Gap(
                relationship_type, "readability",
                f"param {p['name']!r} (read_intent={p['read_intent']!r}) has no "
                f"READ_INTENT_ATTR entry — unreadable regardless of adapter support"))
        elif not _attr_reachable(attr, attrs, src):
            report.gaps.append(Gap(
                relationship_type, "readability",
                f"param {p['name']!r}'s attribute {attr!r} is declared but not emitted "
                f"anywhere in the Cisco adapter for {protocol!r} — likely unreadable",
                severity="warning"))

        intent_name = _INTENT_FOR_PARAM.get(p["name"])
        if intent_name is None:
            # Not always a bug: some parameters are readable but
            # deliberately left without an automated fix on safety
            # grounds — e.g. ospf_auth's target value is just a type
            # ("md5"/"simple"), not the actual shared secret, so
            # auto-enabling authentication without a real key would
            # actively break the interface rather than fix it; STP's
            # ErrDisabled (BPDU Guard) is the same pattern for a
            # different reason (auto-clearing risks reintroducing a real
            # bridging loop). Flagged for review, not auto-rejected.
            report.gaps.append(Gap(
                relationship_type, "fixability",
                f"param {p['name']!r} has no _INTENT_FOR_PARAM entry — a detected "
                f"violation can never produce a proposed fix (may be deliberate; needs review)",
                severity="warning"))
        elif intent_name not in recipe_names:
            report.gaps.append(Gap(
                relationship_type, "fixability",
                f"param {p['name']!r} maps to intent {intent_name!r}, but no "
                f"RemediationRecipe with that name exists for protocol {protocol!r}"))
    return report


def run_full_audit() -> List[Report]:
    """Every currently-compiled protocol's signatures, plus every
    structured Mismatch Investigation corpus file (the top-level
    corpus/*.txt files with PARAM: tags — corpus/general/*.txt is prose-only
    RAG grounding with no structured parameters to check yet)."""
    reports = [check_protocol_signatures(p) for p in PROTOCOL_SPECS]
    corpus_files = sorted(
        f[:-4] for f in os.listdir(_CORPUS_DIR)
        if f.endswith(".txt") and os.path.isfile(os.path.join(_CORPUS_DIR, f)))
    reports.extend(check_corpus_completeness(rel) for rel in corpus_files)
    return reports


def format_report(reports: List[Report]) -> str:
    lines = []
    for r in reports:
        if not r.gaps:
            lines.append(f"[clean] {r.subject}")
            continue
        status = "OK (warnings only)" if r.clean else "GAPS FOUND"
        lines.append(f"[{status}] {r.subject}")
        for g in r.gaps:
            lines.append(f"    {g.severity:7s} {g.check:12s} {g.detail}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    reports = run_full_audit()
    if len(sys.argv) > 1:
        reports = [r for r in reports if r.subject == sys.argv[1]]
    print(format_report(reports))
    sys.exit(0 if all(r.clean for r in reports) else 1)
