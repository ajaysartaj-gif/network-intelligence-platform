"""
core/intelligence/config_synthesis/verification.py
===================================================
Honest verification — judge the configuration, not the environment.

Two failure modes in the screenshots were not configuration errors at all:

  1. A perfectly correct config was marked "NOT satisfied" because public NTP
     never *associated* — impossible in an isolated lab. Association is an
     OPERATIONAL, reachability-dependent fact, not proof the intent was wrong.

  2. On R3 the save aborted with «Pattern not detected: 'R3\\#'» — a Netmiko
     prompt-detection failure in the TRANSPORT, not the device. Because the save
     failed, startup-config stayed empty and five correct checks "failed". That
     is a persistence/transport problem to RETRY, not a config to redo.

This module separates those truths. A plan is judged satisfied when its APPLIED
checks pass; PERSISTED failures are reported as "applied but not saved — retry
save" (with a concrete repair directive) when a save-transport failure is
detected; OPERATIONAL/reachability-dependent checks degrade to "pending", never
to "failed", in an isolated environment.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.intelligence.config_synthesis.base import StateCheck, CheckKind, ConfigPlan


# signatures that mean "the SAVE transport failed", not "the config is wrong".
_SAVE_FAIL_SIGNS = [
    r"pattern not detected",
    r"\[save\]\s*failed",
    r"save\s+failed",
    r"timed?-?out",
    r"read_timeout",
]


def detect_save_transport_failure(raw_output: str) -> Optional[str]:
    low = (raw_output or "").lower()
    for pat in _SAVE_FAIL_SIGNS:
        if re.search(pat, low):
            return pat.replace("\\", "")
    return None


def save_repair_directive(device_prompt: str = "") -> Dict[str, Any]:
    """Concrete guidance to re-attempt the save robustly (the R3\\# fix)."""
    prompt = device_prompt or "#"
    return {
        "action": "retry_save",
        "method": "write memory",
        "netmiko_kwargs": {
            # the real fix: tell Netmiko exactly what prompt to expect, and give
            # it room, instead of letting auto-detection miss 'R3#'.
            "expect_string": r"#",
            "read_timeout": 60,
            "cmd_verify": False,
        },
        "note": (f"save aborted on prompt detection; retry 'write memory' with "
                 f"expect_string='#' (matches '{prompt}') and a longer read_timeout, "
                 f"then re-read startup-config before judging persistence"),
    }


@dataclass
class CheckResult:
    check: StateCheck
    passed: Optional[bool]      # True / False / None (pending)
    detail: str = ""


@dataclass
class VerificationReport:
    device: str
    satisfied: bool
    applied_ok: bool
    persisted_ok: Optional[bool]
    results: List[CheckResult] = field(default_factory=list)
    save_transport_failed: bool = False
    repair: Optional[Dict[str, Any]] = None
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"device": self.device, "satisfied": self.satisfied,
                "applied_ok": self.applied_ok, "persisted_ok": self.persisted_ok,
                "save_transport_failed": self.save_transport_failed,
                "repair": self.repair, "summary": self.summary,
                "checks": [{"description": r.check.description,
                            "kind": r.check.kind.value,
                            "passed": r.passed, "detail": r.detail}
                           for r in self.results]}


def _evaluate_check(check: StateCheck, running: str, startup: str,
                    isolated: bool) -> CheckResult:
    if check.kind == CheckKind.APPLIED:
        hay = running
    elif check.kind == CheckKind.PERSISTED:
        hay = startup
    else:  # OPERATIONAL
        hay = running  # operational evidence usually in show-command output
    hay_l = (hay or "").lower()

    # operational + reachability-dependent in an isolated env → pending, not fail
    if check.kind == CheckKind.OPERATIONAL and check.reachability_dependent and isolated:
        return CheckResult(check, None, "pending: reachability-dependent in isolated environment")

    present_ok = all(s.lower() in hay_l for s in check.expect_present) if check.expect_present else True
    absent_ok = all(s.lower() not in hay_l for s in check.expect_absent) if check.expect_absent else True
    ok = present_ok and absent_ok
    if not ok and not hay:
        return CheckResult(check, None, "pending: no output captured for this check")
    return CheckResult(check, ok, "ok" if ok else "expected content not found")


def verify_plan(plan: ConfigPlan, *, running_config: str = "",
                startup_config: str = "", raw_output: str = "",
                isolated: bool = False) -> VerificationReport:
    save_fail = detect_save_transport_failure(raw_output)
    results: List[CheckResult] = []
    for c in plan.checks:
        results.append(_evaluate_check(c, running_config, startup_config, isolated))

    applied = [r for r in results if r.check.kind == CheckKind.APPLIED]
    persisted = [r for r in results if r.check.kind == CheckKind.PERSISTED]

    applied_ok = all(r.passed for r in applied) if applied else True
    # if the save transport failed, persistence is unknown/not-yet, not 'wrong'.
    if save_fail:
        persisted_ok = None
    else:
        graded = [r for r in persisted if r.passed is not None]
        persisted_ok = all(r.passed for r in graded) if graded else None

    # honest verdict: the INTENT is satisfied if it's applied; persistence and
    # operational state are reported separately and don't fail a correct config.
    satisfied = bool(applied_ok)
    repair = None
    if save_fail or (persisted_ok is False):
        repair = save_repair_directive()

    parts = [f"applied={'ok' if applied_ok else 'FAIL'}"]
    if persisted_ok is True:
        parts.append("persisted=ok")
    elif persisted_ok is False:
        parts.append("persisted=FAIL (retry save)")
    elif save_fail:
        parts.append(f"persisted=unknown (save transport failed: {save_fail})")
    pend = [r for r in results if r.passed is None and r.check.kind == CheckKind.OPERATIONAL]
    if pend:
        parts.append(f"{len(pend)} operational check(s) pending reachability")

    return VerificationReport(
        device=plan.device, satisfied=satisfied, applied_ok=applied_ok,
        persisted_ok=persisted_ok, results=results,
        save_transport_failed=bool(save_fail), repair=repair,
        summary="; ".join(parts))
