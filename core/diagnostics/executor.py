"""Technology-agnostic diagnostic runtime.

Generalizes what was, last turn, a single hardcoded `debug` executor into a
runtime driven entirely by data on a `DiagnosticCapability`/
`DiagnosticActionSpec` pair -- no technology name is ever branched on here.
The lifecycle itself (preconditions -> enable -> wait -> collect ->
guaranteed disable+verify) is the one thing every diagnostic action shares,
which is exactly why it lives in code once instead of being duplicated per
technology.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from .capability import DiagnosticActionSpec, DiagnosticCapability, PreconditionKind

RunCommands = Callable[[List[str]], Dict[str, str]]

MAX_DURATION_SECONDS = 30


@dataclass
class DiagnosticResult:
    device: str
    technology: str
    action: str
    command: str
    requested_duration_s: int
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    actual_duration_s: float = 0.0
    output: str = ""
    cleanly_disabled: bool = False
    refused: bool = False
    refusal_reason: str = ""
    error: str = ""

    def summary(self) -> str:
        if self.refused:
            return f"Refused: {self.refusal_reason}"
        status = "cleanly disabled" if self.cleanly_disabled else "CLEANUP UNVERIFIED"
        return (f"{self.device}: {self.technology}/{self.action} ran "
                f"{self.actual_duration_s:.1f}s ({self.started_at} -> {self.ended_at}), {status}")


def _check_cpu_below(run_commands: RunCommands, spec: DiagnosticActionSpec,
                      threshold: Optional[float]) -> Tuple[bool, str]:
    try:
        out = run_commands([spec.cpu_check_command]).get(spec.cpu_check_command, "")
    except Exception as exc:
        return False, f"could not read CPU load: {exc}"
    m = re.search(spec.cpu_parse_pattern, out or "")
    if not m:
        return False, "could not parse CPU utilization output -- refusing to guess"
    pct = float(m.group(1))
    if threshold is not None and pct >= threshold:
        return False, f"CPU already at {pct:.0f}% -- at or above the {threshold:.0f}% safety threshold"
    return True, f"CPU at {pct:.0f}%, safe to proceed"


def _check_memory_below(run_commands: RunCommands, spec: DiagnosticActionSpec,
                         threshold: Optional[float]) -> Tuple[bool, str]:
    try:
        out = run_commands([spec.memory_check_command]).get(spec.memory_check_command, "")
    except Exception as exc:
        return False, f"could not read memory usage: {exc}"
    m = re.search(spec.memory_parse_pattern, out or "")
    if not m:
        return False, "could not parse memory usage output -- refusing to guess"
    pct = float(m.group(1))
    if threshold is not None and pct >= threshold:
        return False, f"memory usage already at {pct:.0f}% -- at or above the {threshold:.0f}% safety threshold"
    return True, f"memory usage at {pct:.0f}%, safe to proceed"


def _check_logging_buffered(run_commands: RunCommands, spec: DiagnosticActionSpec,
                             _threshold: Optional[float]) -> Tuple[bool, str]:
    try:
        out = run_commands([spec.logging_check_command]).get(spec.logging_check_command, "")
    except Exception as exc:
        return False, f"could not read logging config: {exc}"
    m = re.search(spec.logging_buffered_pattern, out or "", re.IGNORECASE)
    if not m:
        return False, ("could not confirm buffered logging is enabled -- refusing to "
                        "risk synchronous console output")
    if m.group(1).lower().startswith("disabled"):
        return False, ("buffered logging is disabled on this device -- refusing to "
                        "risk synchronous console output")
    return True, "buffered logging confirmed"


_PRECONDITION_CHECKS: Dict[PreconditionKind, Callable[[RunCommands, DiagnosticActionSpec, Optional[float]], Tuple[bool, str]]] = {
    PreconditionKind.CPU_BELOW: _check_cpu_below,
    PreconditionKind.MEMORY_BELOW: _check_memory_below,
    PreconditionKind.LOGGING_BUFFERED: _check_logging_buffered,
}


def _verify_cleanly_disabled(verify_output: str, clean_pattern: str) -> bool:
    out = (verify_output or "").strip()
    if not out:
        return True
    return not re.search(clean_pattern, out, re.IGNORECASE)


def run_diagnostic(
    capability: DiagnosticCapability,
    action_spec: DiagnosticActionSpec,
    device: str,
    run_commands: RunCommands,
    duration_seconds: Optional[int] = None,
) -> DiagnosticResult:
    """Run one capability's diagnostic action against a real device.

    Enable -> wait -> collect -> unconditionally disable and verify,
    regardless of what happens in between. Every step is driven by data on
    `capability`/`action_spec`; nothing here is specific to any technology.
    """
    requested = duration_seconds if duration_seconds is not None else capability.max_duration_s
    requested = max(1, min(requested, capability.max_duration_s, MAX_DURATION_SECONDS))
    command = "; ".join(action_spec.enable_commands)
    result = DiagnosticResult(
        device=device, technology=capability.technology, action=capability.action,
        command=command, requested_duration_s=requested,
    )

    if not action_spec.enable_commands:
        result.refused = True
        result.refusal_reason = f"no enable commands configured for {capability.technology}/{capability.action}"
        return result

    for precondition in capability.preconditions:
        check = _PRECONDITION_CHECKS.get(precondition.kind)
        if check is None:
            result.refused = True
            result.refusal_reason = f"unknown precondition kind: {precondition.kind}"
            return result
        ok, reason = check(run_commands, action_spec, precondition.threshold)
        if not ok:
            result.refused = True
            result.refusal_reason = reason
            return result

    result.started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    try:
        run_commands(list(action_spec.enable_commands))
        time.sleep(requested)
        result.output = run_commands([action_spec.collect_command]).get(action_spec.collect_command, "")
    except Exception as exc:
        result.error = str(exc)
    finally:
        try:
            verify = run_commands([action_spec.disable_command, action_spec.verify_command])
            result.cleanly_disabled = _verify_cleanly_disabled(
                verify.get(action_spec.verify_command, ""), action_spec.verify_clean_pattern)
        except Exception as exc:
            result.error = (result.error + "; " if result.error else "") + f"cleanup failed: {exc}"
            result.cleanly_disabled = False
        result.ended_at = datetime.now(timezone.utc).isoformat()
        result.actual_duration_s = time.monotonic() - t0

    return result
