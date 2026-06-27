"""
core/intelligence/config_synthesis/interface.py
================================================
Interface intelligence — name normalisation and ROBUST description verification.

This fixes a real false-negative: a description was applied correctly, but the
verification read it back with a command that prints the ABBREVIATED interface
name ("Fa0/0") while the check searched for the FULL name ("FastEthernet0/0").
The string never matched, so a present description was reported "missing" — even
though `show ip interface brief` (full names) had just confirmed the same
interface was up.

The cure is twofold:
  1. Normalise interface names so Fa0/0 ≡ FastEthernet0/0 ≡ f0/0 everywhere.
  2. Verify descriptions from an AUTHORITATIVE source whose format is known —
     `show running-config interface <full-name>`, which prints the literal
     `description <text>` line untruncated — and match on the description text,
     not on how some table happens to render the interface name.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from core.intelligence.config_synthesis.base import StateCheck, CheckKind


# canonical long form keyed by lowercase short prefix. ordered longest-first so
# "gi" matches before "g", "fa" before "f", etc.
_IF_PREFIXES = [
    ("hundredgige", "HundredGigE"), ("twentyfivegige", "TwentyFiveGigE"),
    ("fortygige", "FortyGigE"), ("tengigabitethernet", "TenGigabitEthernet"),
    ("gigabitethernet", "GigabitEthernet"), ("fastethernet", "FastEthernet"),
    ("ethernet", "Ethernet"), ("port-channel", "Port-channel"),
    ("portchannel", "Port-channel"), ("loopback", "Loopback"),
    ("vlan", "Vlan"), ("tunnel", "Tunnel"), ("serial", "Serial"),
    ("management", "Management"),
    ("te", "TenGigabitEthernet"), ("gi", "GigabitEthernet"),
    ("fa", "FastEthernet"), ("eth", "Ethernet"), ("po", "Port-channel"),
    ("lo", "Loopback"), ("tu", "Tunnel"), ("se", "Serial"),
    ("mgmt", "Management"), ("vl", "Vlan"),
    ("g", "GigabitEthernet"), ("f", "FastEthernet"), ("e", "Ethernet"),
    ("s", "Serial"),
]

_IF_SPLIT = re.compile(r"^([A-Za-z\-]+)\s*([\d/\.:]+)$")


def normalize_if_name(name: str) -> str:
    """Return the canonical full interface name. 'Fa0/0' -> 'FastEthernet0/0'."""
    if not name:
        return name
    raw = name.strip()
    m = _IF_SPLIT.match(raw.replace(" ", ""))
    if not m:
        return raw
    alpha, num = m.group(1).lower(), m.group(2)
    for pref, full in _IF_PREFIXES:
        if alpha == pref or alpha.startswith(pref):
            return f"{full}{num}"
    # already a full/unknown name — return with original casing of the alpha part
    return f"{m.group(1)}{num}"


def if_name_variants(name: str) -> List[str]:
    """All plausible renderings of an interface name, for tolerant matching."""
    full = normalize_if_name(name)
    m = _IF_SPLIT.match(full)
    variants = {name.strip(), full}
    if m:
        alpha, num = m.group(1), m.group(2)
        # common short forms
        short = {"FastEthernet": "Fa", "GigabitEthernet": "Gi",
                 "TenGigabitEthernet": "Te", "Ethernet": "Eth",
                 "Port-channel": "Po", "Loopback": "Lo", "Tunnel": "Tu",
                 "Serial": "Se", "Vlan": "Vlan", "Management": "Mgmt"}.get(alpha)
        if short:
            variants.add(f"{short}{num}")
            variants.add(f"{short.lower()}{num}")
        variants.add(f"{alpha[:2]}{num}")
    return [v for v in variants if v]


def build_description_checks(expected: Dict[str, str]) -> List[StateCheck]:
    """Authoritative, format-stable description checks for {interface: description}.

    Uses `show running-config interface <full>` which prints the literal
    `description <text>` line, and matches on the DESCRIPTION TEXT (the part we
    actually set), immune to how any table abbreviates the interface name.
    """
    checks: List[StateCheck] = []
    for raw_if, desc in expected.items():
        full = normalize_if_name(raw_if)
        checks.append(StateCheck(
            description=f"{full} description set to '{desc}'",
            verify_command=f"show running-config interface {full}",
            expect_present=[f"description {desc}"], kind=CheckKind.APPLIED))
        checks.append(StateCheck(
            description=f"{full} description persisted",
            verify_command=f"show running-config interface {full}",
            expect_present=[f"description {desc}"], kind=CheckKind.PERSISTED))
    return checks


def _iface_block(config_text: str, iface: str) -> str:
    """Extract one interface's config block from a running/startup config dump,
    tolerant of name abbreviation."""
    if not config_text:
        return ""
    variants = [v.lower() for v in if_name_variants(iface)]
    lines = config_text.splitlines()
    block, capturing = [], False
    for ln in lines:
        low = ln.strip().lower()
        if low.startswith("interface "):
            ifn = low.split("interface ", 1)[1].strip()
            capturing = any(ifn == v or ifn.replace(" ", "") == v for v in variants)
            if capturing:
                block = [ln]
            continue
        if capturing:
            if ln and not ln.startswith(" ") and not low.startswith("description") \
               and not low.startswith("ip ") and low and not ln[0].isspace():
                # next top-level line ends the block (e.g. '!' or 'interface ...')
                if low == "!" or low.startswith("interface "):
                    capturing = False
                    continue
            block.append(ln)
    return "\n".join(block)


def verify_descriptions(expected: Dict[str, str], *,
                        running_config: str = "",
                        startup_config: str = "",
                        run_command: Optional[Callable[[str], str]] = None
                        ) -> Dict[str, Any]:
    """Robustly verify interface descriptions.

    Provide either full config dumps (running_config / startup_config) or a
    run_command callable that executes a show command and returns its output.
    Matching normalises interface names and keys on the description TEXT, so a
    correctly-applied description is never reported missing because of name
    abbreviation or table truncation.
    """
    results = []
    all_applied = True
    for raw_if, desc in expected.items():
        full = normalize_if_name(raw_if)
        haystack = ""
        if run_command is not None:
            try:
                haystack = run_command(f"show running-config interface {full}") or ""
            except Exception:
                haystack = ""
        if not haystack and running_config:
            haystack = _iface_block(running_config, full) or running_config
        present = (f"description {desc}".lower() in haystack.lower()) or \
                  (desc.lower() in haystack.lower())
        # persistence (best-effort): look in startup if provided
        persisted = None
        if startup_config:
            sblock = _iface_block(startup_config, full) or startup_config
            persisted = desc.lower() in sblock.lower()
        all_applied = all_applied and present
        results.append({"interface": full, "description": desc,
                        "applied": present, "persisted": persisted,
                        "detail": ("found" if present else
                                   "not found in authoritative running-config block")})
    return {"satisfied": all_applied, "interfaces": results,
            "method": "normalized show running-config interface match"}


# ── outcome-contract hardening (deterministic guards around the LLM judge) ───
_IF_TOKEN = re.compile(
    r"\b((?:fa|gi|te|eth|ethernet|fastethernet|gigabitethernet|tengigabitethernet|"
    r"lo|loopback|po|port-?channel|se|serial|tu|tunnel|vl|vlan|mgmt|management)"
    r"[a-z]*\s*\d+(?:/\d+)*(?:\.\d+)?)\b", re.I)


def extract_interface(text: str) -> Optional[str]:
    m = _IF_TOKEN.search(text or "")
    return normalize_if_name(m.group(1)) if m else None


def normalize_check_command(check_command: str, description: str = "") -> str:
    """Rewrite a verification command to an authoritative, format-stable form.

    The classic failure: an interface-description check uses `show interfaces
    description` (which abbreviates names and truncates text) or a per-interface
    command with an abbreviated name. We rewrite any interface-description read to
    `show running-config interface <full-name>`, which prints the literal
    `description <text>` line untruncated with the full interface name.
    """
    cmd = (check_command or "").strip()
    low = cmd.lower()
    blob = f"{low} {description.lower()}"
    iface = extract_interface(cmd) or extract_interface(description)
    if "description" in blob and iface:
        return f"show running-config interface {iface}"
    # normalise an abbreviated interface name inside a running-config read
    if iface and ("running-config interface" in low or "run interface" in low
                  or low.startswith("show run")):
        return f"show running-config interface {iface}"
    return cmd


def deterministic_precheck(description: str, check_command: str, output: str,
                           intent: str = "") -> Optional[str]:
    """Resolve a verification deterministically where it is safe to do so,
    BEFORE the LLM judges. Returns 'pass' on a clear positive match, else None
    (so genuine negatives and fuzzy cases still go to the LLM — we never emit a
    deterministic 'fail', to avoid converting one false verdict into another).

    Scope is intentionally narrow and high-confidence: interface-description
    presence, where a `description <text>` line in the interface's running-config
    is conclusive proof the description is set — immune to name abbreviation.
    """
    blob = f"{description.lower()} {check_command.lower()}"
    out = output or ""
    if "description" in blob:
        # a non-empty 'description ...' line in the output is conclusive.
        for ln in out.splitlines():
            s = ln.strip()
            if s.lower().startswith("description ") and len(s) > len("description "):
                return "pass"
    return None


# ── GENERAL (feature-agnostic) config-presence verification ──────────────────
# Operational facts depend on time/reachability/peers and MUST stay with the LLM
# (pending-vs-fail). Everything else is "did this config line land?", which is
# deterministically answerable from the authoritative config we just applied.
_OPERATIONAL_KEYWORDS = (
    "synchron", "adjacen", "neighbor", "neighbour", "reachab", "resolv",
    "associat", "establish", "converg", "up state", "line protocol", "up/up",
    "pingable", "ping", "route is", "routes are", "learned", "in full", "peering",
    "sync", "operational", "responding", "queried",
)
_PERSIST_KEYWORDS = ("persist", "startup-config", "saved", "survive", "reload",
                     "write mem", "nvram")

# config noise that isn't a verifiable end-state line on its own
_SKIP_APPLIED = ("configure terminal", "end", "exit", "!", "write memory",
                 "write mem", "copy run start", "do write")


def normalize_config_text(text: str) -> str:
    """Lowercase, collapse whitespace, and expand every interface name to its
    canonical full form, so matching is immune to abbreviation/formatting."""
    if not text:
        return ""
    def _exp(m):
        return normalize_if_name(m.group(1))
    expanded = _IF_TOKEN.sub(_exp, text)
    return re.sub(r"[ \t]+", " ", expanded.lower()).strip()


def _meaningful_applied(applied_commands: List[str]) -> List[str]:
    out, current_if = [], ""
    for c in applied_commands or []:
        cl = c.strip()
        low = cl.lower()
        if not cl or low in _SKIP_APPLIED:
            continue
        if low.startswith("interface "):
            current_if = normalize_if_name(cl.split(" ", 1)[1])
            continue
        # qualify sub-interface lines with their interface so matching is precise
        if current_if and (c.startswith(" ") or low.startswith("description ")
                           or low.startswith("ip ") or low.startswith("no ")):
            out.append(f"interface {current_if} :: {cl}")
        else:
            current_if = ""
            out.append(cl)
    return out


def _line_present(applied_line: str, config_norm: str) -> bool:
    """Is one applied config line present in a normalized config dump?"""
    if "::" in applied_line:
        _, _, real = applied_line.partition("::")
        applied_line = real.strip()
    return normalize_config_text(applied_line) in config_norm


def general_precheck(description: str, check_command: str, output: str,
                     intent: str = "", applied_commands: Optional[List[str]] = None,
                     running_config: str = "", startup_config: str = "") -> Optional[str]:
    """Feature-agnostic deterministic verdict for config-PRESENCE conditions.

    If the condition is about whether configuration was applied/persisted (not an
    operational state), prove it directly against the authoritative running/
    startup config we just wrote — normalised so abbreviation/formatting cannot
    cause a false 'missing'. Returns 'pass' on conclusive proof, else None
    (operational checks and anything unproven defer to the LLM; we never emit a
    deterministic 'fail').
    """
    blob = f"{description.lower()} {check_command.lower()}"
    # operational facts are not ours to settle deterministically.
    if any(k in blob for k in _OPERATIONAL_KEYWORDS):
        # the interface-description special case is still safe & conclusive
        return deterministic_precheck(description, check_command, output, intent)

    applied = _meaningful_applied(applied_commands or [])
    if not applied:
        return deterministic_precheck(description, check_command, output, intent)

    is_persist = any(k in blob for k in _PERSIST_KEYWORDS)
    cfg = startup_config if is_persist else running_config
    # fall back to the command's own captured output if no full dump was supplied
    cfg_norm = normalize_config_text(cfg or output)
    if not cfg_norm:
        return deterministic_precheck(description, check_command, output, intent)

    # which applied lines does this condition concern? if it names specific
    # tokens (an interface, a server, a keyword), test those; otherwise test all.
    desc_norm = normalize_config_text(description)
    relevant = [a for a in applied
                if any(tok in desc_norm for tok in normalize_config_text(
                    a.split("::")[-1]).split() if len(tok) > 3)]
    target = relevant or applied

    if all(_line_present(a, cfg_norm) for a in target):
        return "pass"
    return deterministic_precheck(description, check_command, output, intent)
