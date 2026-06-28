"""
Evidence Assessor (Milestone 2)
==============================

Decides whether enough VERIFIED runtime evidence exists to safely generate
configuration. It REUSES existing repository parsers (the config-synthesis
intent parser and interface normalizer) and inspects already-collected device
facts. It contains NO hardcoded per-protocol networking logic and collects
nothing itself — it only assesses evidence that other engines already gathered.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .contract import EvidenceContract, EvidenceItem, EvidenceStatus

# Interface tokens used only to spot references in a request — not protocol logic.
_IFACE_RE = re.compile(
    r"\b((?:Gigabit|TenGig|FortyGig|HundredGig|Fast|Forty|Hundred|Gig|Ten|"
    r"Ethernet|Eth|Loopback|Lo|Serial|Se|Vlan|Vl|Tunnel|Tu|Port-?channel|Po|"
    r"Fa|Gi|Te)[A-Za-z-]*\s?\d[\d/.:]*)\b",
    re.IGNORECASE,
)


class EvidenceAssessor:
    """Assess verified evidence for a change request against collected facts."""

    def assess(
        self,
        request: str,
        device: str,
        device_facts: str = "",
        fleet_context: str = "",
        inventory_summary: str = "",
        **ctx: Any,
    ) -> EvidenceContract:
        facts = (device_facts or "").strip()
        facts_l = facts.lower()
        inv_l = (inventory_summary or "").lower()
        haystack = facts_l + " " + inv_l

        # Reuse the existing intent parser — no hardcoded networking logic here.
        params: Dict[str, Any] = {}
        try:
            from core.intelligence.config_synthesis import parse_intent
            _intent = parse_intent(request or "")
            params = getattr(_intent, "params", {}) or {}
        except Exception:
            params = {}

        probes: List[EvidenceItem] = []

        def add(key: str, label: str, present: bool, required: bool, detail: str = "") -> None:
            probes.append(EvidenceItem(key, label, bool(present), bool(required), detail))

        have_facts = bool(facts)

        # ── baseline evidence required before the LLM may generate config ──
        add("device_identity", "Target device identity",
            bool(device and str(device).strip()), True, f"device={device}")

        add("cli_output", "Verified CLI / device facts", have_facts, True,
            "live facts present" if have_facts else "no live CLI data collected")

        # reachability counts as missing if facts are absent or explicitly unreachable
        reachable = have_facts and ("reachable=false" not in facts_l)
        add("reachability", "Device reachability", reachable, True,
            "reachable" if reachable else "unreachable / unverified")

        # ── platform / vendor (reported, weighted, not blocking) ──
        vendor_known = any(v in haystack for v in (
            "cisco", "arista", "juniper", "nokia", "ios", "nxos", "eos",
            "junos", "vendor", "platform"))
        add("vendor", "Vendor / platform detection", vendor_known, False,
            "" if vendor_known else "vendor/platform not evident in facts")

        # ── existing/running configuration (reported, weighted) ──
        have_cfg = any(k in facts_l for k in (
            "running-config", "running config", "current configuration", "config:"))
        add("existing_config", "Existing running configuration", have_cfg, False)

        # ── interface evidence — REQUIRED only when the request references one ──
        ref_ifaces = self._referenced_interfaces(request, params)
        if ref_ifaces:
            present = have_facts and any(self._iface_in(i, facts) for i in ref_ifaces)
            add("interface", "Interface state for " + ", ".join(ref_ifaces),
                present, True, "" if present else "referenced interface not in facts")

        # ── topology / neighbor (reported, weighted) ──
        add("topology", "Topology / neighbor information",
            any(k in facts_l for k in ("neighbor", "cdp", "lldp", "topology")),
            False)

        # ── scoring ──
        required = [p for p in probes if p.required]
        req_present = sum(1 for p in required if p.present)
        present_total = sum(1 for p in probes if p.present)
        total = len(probes)
        completeness = (100.0 * present_total / total) if total else 0.0
        confidence = (req_present / len(required)) if required else 1.0
        all_required = (req_present == len(required))

        if all_required:
            status = EvidenceStatus.COMPLETE
        elif req_present >= 1:
            status = EvidenceStatus.PARTIAL
        else:
            status = EvidenceStatus.INSUFFICIENT

        available = [p for p in probes if p.present]
        missing = [p for p in probes if not p.present]

        warnings: List[str] = []
        if not vendor_known:
            warnings.append("Vendor/platform not confirmed from collected facts.")
        if not have_cfg:
            warnings.append("Running configuration was not captured.")

        recommendations = self._recommend(
            self._priority_missing(missing), device)

        return EvidenceContract(
            device=device,
            status=status,
            completeness=completeness,
            confidence=confidence,
            available=available,
            missing=missing,
            warnings=warnings,
            recommendations=recommendations,
        )

    # ── helpers (reuse existing parsers; no protocol logic) ──────────────────
    def _referenced_interfaces(self, request: str, params: Dict[str, Any]) -> List[str]:
        found: List[str] = []
        p = params.get("interface") or params.get("interfaces")
        if p:
            found = p if isinstance(p, list) else [p]
        if not found:
            found = [m.strip() for m in _IFACE_RE.findall(request or "")]
        # normalize via the existing interface parser when available
        norm: List[str] = []
        for i in found:
            norm.append(self._normalize_iface(i))
        seen, out = set(), []
        for i in norm:
            k = (i or "").lower()
            if i and k not in seen:
                seen.add(k)
                out.append(i)
        return out

    def _normalize_iface(self, iface: str) -> str:
        try:
            from core.intelligence.config_synthesis.interface import normalize_if_name
            return normalize_if_name(iface)
        except Exception:
            return iface

    def _iface_in(self, iface: str, facts: str) -> bool:
        """True if the referenced interface appears in the facts, comparing
        CANONICAL forms on both sides so abbreviated/expanded names match
        (e.g. 'TenGigE9/9' == 'TenGigabitEthernet9/9')."""
        if not iface:
            return False
        target = self._normalize_iface(iface).lower()
        fl = facts.lower()
        fact_ifaces = {self._normalize_iface(m).lower() for m in _IFACE_RE.findall(facts)}
        if target and target in fact_ifaces:
            return True
        return iface.lower() in fl

    def _priority_missing(self, missing: List[EvidenceItem]) -> List[EvidenceItem]:
        req = [m for m in missing if m.required]
        return req if req else missing

    def _recommend(self, missing: List[EvidenceItem], device: str) -> List[str]:
        text = {
            "cli_output": f"Log in to {device} and collect live CLI "
                          f"(e.g. 'show running-config', 'show ip interface brief').",
            "reachability": f"Verify {device} is reachable (ping/SSH) before "
                            f"generating configuration.",
            "interface": f"Collect interface state on {device} "
                         f"('show interfaces', 'show ip interface brief').",
            "existing_config": f"Capture the running configuration of {device} "
                               f"('show running-config').",
            "vendor": f"Confirm vendor/platform of {device} ('show version').",
            "topology": f"Collect neighbor/topology data for {device} "
                        f"('show cdp neighbors detail' / 'show lldp neighbors detail').",
            "device_identity": "Specify the target device for this change.",
        }
        out, seen = [], set()
        for m in missing:
            rec = text.get(m.key)
            if rec and rec not in seen:
                seen.add(rec)
                out.append(rec)
        return out


# ── module-level singleton + convenience ────────────────────────────────────
_ASSESSOR: Optional[EvidenceAssessor] = None


def get_evidence_assessor() -> EvidenceAssessor:
    global _ASSESSOR
    if _ASSESSOR is None:
        _ASSESSOR = EvidenceAssessor()
    return _ASSESSOR


def assess_evidence(request: str, device: str, device_facts: str = "", **ctx: Any) -> EvidenceContract:
    """Convenience entry point used by the Execution Engine."""
    return get_evidence_assessor().assess(request, device, device_facts, **ctx)
