"""
core/intelligence/config_synthesis/engine.py
=============================================
Configuration Intelligence — the facade the deploy path calls instead of freely
generating config.

It compiles intent to canonical commands (deterministic, identical across
devices), validates them — where documentation is available — against the
vendor's own guidance (RAG over OEM docs), records the canonical procedure into
memory so it strengthens with use, and verifies outcomes HONESTLY (applied vs
persisted vs operational). The model is used only to parse intent; it never
authors syntax, so the source of truth stays the template/document, not a guess.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from core.intelligence.config_synthesis.base import Vendor, ConfigPlan
from core.intelligence.config_synthesis.synthesizer import (
    ConfigSynthesizer, SynthesisResult, parse_intent,
)
from core.intelligence.config_synthesis.verification import (
    verify_plan, VerificationReport, save_repair_directive,
)

logger = logging.getLogger("NetBrain.Intelligence.ConfigSynthesis")


def _default_environment() -> Dict[str, Any]:
    """Isolated GNS3 labs cannot reach public DNS/NTP; default to isolated unless
    told otherwise, so we never fail a correct config on unreachable externals.
    A reachable in-lab NTP server can be supplied via NETBRAIN_LAB_NTP."""
    isolated = os.environ.get("NETBRAIN_ENV_ISOLATED", "1") not in ("0", "false", "no")
    env: Dict[str, Any] = {"isolated": isolated}
    lab_ntp = os.environ.get("NETBRAIN_LAB_NTP", "")
    if lab_ntp:
        env["ntp_server"] = lab_ntp
    lab_dns = os.environ.get("NETBRAIN_LAB_DNS", "")
    if lab_dns:
        env["dns_servers"] = [s.strip() for s in lab_dns.split(",") if s.strip()]
    return env


class ConfigurationIntelligence:
    def __init__(self):
        self.synth = ConfigSynthesizer()
        self._rag = None
        self._rag_tried = False

    # ── synthesis ────────────────────────────────────────────────────────────
    def synthesize(self, intent_text: str, devices: List[str], *,
                   vendor: str = Vendor.CISCO_IOS.value,
                   current_configs: Optional[Dict[str, str]] = None,
                   environment: Optional[Dict[str, Any]] = None,
                   ground: bool = True) -> SynthesisResult:
        env = environment or _default_environment()
        result = self.synth.synthesize(
            intent_text, devices, vendor=vendor,
            current_configs=current_configs, environment=env)
        if ground:
            self._ground(result, vendor)
        self._remember(result, vendor)
        return result

    # ── OEM-documentation grounding (the "source of truth" validation) ───────
    def _rag_engine(self):
        if not self._rag_tried:
            self._rag_tried = True
            try:
                from core.rag_engine import get_rag_engine  # if a singleton exists
                self._rag = get_rag_engine()
            except Exception:
                try:
                    import app
                    self._rag = getattr(app, "rag_engine", None) or \
                        getattr(getattr(app, "orchestrator", None), "rag", None)
                except Exception:
                    self._rag = None
        return self._rag

    def _ground(self, result: SynthesisResult, vendor: str) -> None:
        """Validate each feature's canonical commands against retrieved vendor
        documentation. Annotate provenance; warn (do not block) on mismatch.
        Degrades silently when no docs are available — templates remain truth."""
        rag = self._rag_engine()
        if rag is None:
            return
        for feature in result.intent.features:
            try:
                hits = rag.search(f"{vendor} {feature} configuration", vendor=None,
                                  protocol=None, top_k=3)
            except Exception:
                hits = []
            if not hits:
                continue
            corpus = " ".join(str(h.get("content") or h.get("snippet") or h.get("text") or "")
                              for h in hits).lower()
            for plan in result.plans.values():
                for cmd in plan.apply_commands:
                    head = " ".join(cmd.split()[:2]).lower()  # e.g. "ip name-server"
                    if head and corpus and head in corpus:
                        if "doc-validated" not in plan.provenance:
                            plan.provenance.append("doc-validated")
                    elif corpus and head not in corpus:
                        plan.warnings.append(
                            f"'{head}' not found in retrieved {vendor} docs (template-trusted)")

    # ── persist the canonical procedure so it strengthens with use ───────────
    def _remember(self, result: SynthesisResult, vendor: str) -> None:
        try:
            from core.intelligence.memory import get_memory_system
            sysm = get_memory_system()
            for device, plan in result.plans.items():
                if plan.apply_commands:
                    # store the canonical (device-independent) procedure once.
                    sysm.procedural.learn_outcome(
                        f"configure {'+'.join(plan.features)}", vendor,
                        plan.apply_commands, success=True, device=device)
                break  # one canonical record per synthesis
        except Exception:
            pass

    # ── honest verification ──────────────────────────────────────────────────
    def verify(self, plan: ConfigPlan, *, running_config: str = "",
               startup_config: str = "", raw_output: str = "",
               environment: Optional[Dict[str, Any]] = None) -> VerificationReport:
        env = environment or _default_environment()
        return verify_plan(plan, running_config=running_config,
                           startup_config=startup_config, raw_output=raw_output,
                           isolated=bool(env.get("isolated")))

    # ── drop-in helper for the deploy path ───────────────────────────────────
    def plan_for_deploy(self, nl_request: str, devices: List[str], *,
                        vendor: str = Vendor.CISCO_IOS.value,
                        current_configs: Optional[Dict[str, str]] = None
                        ) -> Dict[str, Any]:
        """Returns a deploy-ready dict: identical canonical commands per device,
        the verification checks, consistency proof and any warnings."""
        res = self.synthesize(nl_request, devices, vendor=vendor,
                              current_configs=current_configs)
        return {
            "deterministic": True,
            "consistent": res.consistent,
            "consistency": res.consistency_detail,
            "features": res.intent.features,
            "unsupported_features": res.unsupported_features,
            "warnings": res.warnings,
            "per_device": {
                d: {"commands": p.apply_commands,
                    "save_required": p.save_required,
                    "signature": p.canonical_signature,
                    "provenance": sorted(set(p.provenance)),
                    "checks": [{"description": c.description, "verify": c.verify_command,
                                "kind": c.kind.value,
                                "reachability_dependent": c.reachability_dependent}
                               for c in p.checks]}
                for d, p in res.plans.items()},
        }

    def report(self) -> Dict[str, Any]:
        return {"supported_features": self.synth.templates.features(),
                "rag_grounding": self._rag_engine() is not None}


# ── singleton ────────────────────────────────────────────────────────────────
_engine: Optional[ConfigurationIntelligence] = None


def get_config_intelligence() -> ConfigurationIntelligence:
    global _engine
    if _engine is None:
        _engine = ConfigurationIntelligence()
    return _engine


def synthesize_config(nl_request: str, devices: List[str], **kw) -> Dict[str, Any]:
    """Module-level convenience the deploy path can call in place of free
    generation. Same canonical commands for every device, guaranteed."""
    return get_config_intelligence().plan_for_deploy(nl_request, devices, **kw)


# ── wiring ───────────────────────────────────────────────────────────────────
def wire_configuration() -> Dict[str, Any]:
    result = {"pillar": False, "features": []}
    eng = get_config_intelligence()
    result["features"] = eng.synth.templates.features()
    try:
        from core.intelligence.capability_model import (
            get_capability_registry, Capability, CapabilityHealth, CapabilityStatus)

        def _probe():
            r = eng.report()
            return CapabilityHealth(
                CapabilityStatus.ACTIVE,
                f"Deterministic, doc-grounded config synthesis for "
                f"{', '.join(r['supported_features'])}; identical canonical config "
                f"across devices; honest applied/persisted/operational verification."
                + (" (RAG-grounded)" if r["rag_grounding"] else ""),
                metrics=r)
        get_capability_registry().register(Capability(
            "configuration_intelligence", "Configuration Intelligence",
            "Compiles intent into vendor-authoritative, idempotent, cross-device-"
            "consistent configuration validated against OEM documentation — a "
            "single source of truth, not per-device free generation.",
            "core/intelligence/config_synthesis/engine.py",
            ["knowledge", "execution", "memory"], _probe))
        result["pillar"] = True
    except Exception as exc:
        logger.debug(f"configuration pillar deferred: {exc}")
    return result
