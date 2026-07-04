"""
Universal Vendor Adapter Framework — the Vendor Gateway
=======================================================
The single facade the Troubleshooting Engine uses. It resolves the right adapter
per device (via detection) and delegates every vendor-touching action to the SDK.

This module contains NO vendor conditionals. It only orchestrates the SDK.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from .models import NormalizedError, NormalizedObject, ValidationResult, VendorProfile, ErrorClass
from .operations import Operation, RemediationIntent, RemediationPlan
from .registry import detect_adapter
from .sdk import DeviceProbe, Transport, VendorAdapter

logger = logging.getLogger(__name__)


class VendorGateway:
    """Engine's only door to vendor land.

    Parameters
    ----------
    send : callable(device, [commands]) -> {command: output}
        The neutral transport (e.g. platform SSH). The gateway never inspects
        commands; adapters own them.
    hint_provider : optional callable(device) -> dict
        Supplies detection hints (sys_descr / banner / api metadata) already
        gathered by the platform, so detect() needn't make a live call.
    """

    def __init__(self,
                 send: Optional[Callable[[Any, List[str]], Dict[str, str]]] = None,
                 hint_provider: Optional[Callable[[Any], Dict[str, Any]]] = None) -> None:
        self._transport = Transport(send=send) if send else Transport(send=lambda d, c: {})
        self._hint_provider = hint_provider
        self._resolved: Dict[str, Tuple[VendorAdapter, VendorProfile]] = {}

    # ── resolution ──────────────────────────────────────────────────────────────
    def resolve(self, device: Any, hints: Optional[Dict[str, Any]] = None
                ) -> Tuple[Optional[VendorAdapter], Optional[VendorProfile]]:
        key = str(getattr(device, "ip", device))
        if key in self._resolved:
            return self._resolved[key]
        merged = dict(self._hint_provider(device)) if self._hint_provider else {}
        if hints:
            merged.update(hints)
        probe = DeviceProbe(device=device, hints=merged,
                            run=lambda cmd: self._transport.send(device, [cmd]).get(cmd, ""))
        adapter, profile = detect_adapter(probe)
        if adapter:
            self._resolved[key] = (adapter, profile)
        return adapter, profile

    def profile(self, device: Any) -> Optional[VendorProfile]:
        _, p = self.resolve(device)
        return p

    def capabilities(self, device: Any) -> List[str]:
        adapter, profile = self.resolve(device)
        if not adapter:
            return []
        try:
            return adapter.capabilities(profile)
        except Exception:
            return list(profile.capabilities) if profile else []

    # ── evidence: normalized Operation -> normalized objects ────────────────────
    def collect(self, device: Any, operation: Operation
                ) -> Tuple[List[NormalizedObject], Optional[NormalizedError]]:
        adapter, profile = self.resolve(device)
        if not adapter:
            return [], NormalizedError(error_class=ErrorClass.UNSUPPORTED,
                                       message="no adapter resolved for device")
        try:
            commands = adapter.build_command(operation, profile)
            raw = adapter.execute(device, commands, self._transport)
            objects = adapter.normalize(adapter.parse_output(operation, raw, profile))
            return objects, None
        except Exception as exc:
            return [], adapter.translate_error(str(exc))

    # ── remediation: normalized Intent -> vendor plan (fix+rollback+verify) ─────
    def remediate(self, device: Any, intent: RemediationIntent) -> RemediationPlan:
        adapter, profile = self.resolve(device)
        if not adapter:
            return RemediationPlan(supported=False,
                                   explanation="no adapter resolved for device")
        if not adapter.supports_intent(intent.name, profile):
            return RemediationPlan(supported=False,
                                   explanation=f"intent '{intent.name}' unsupported by {adapter.name}")
        fix = adapter.build_fix(intent, profile) or []
        rollback = adapter.build_rollback(intent, profile) or []
        verification = adapter.build_verification(intent, profile) or []
        validation = adapter.validate(fix, profile)
        return RemediationPlan(
            fix_commands=fix,
            rollback_commands=rollback,
            verification_commands=verification,
            explanation=intent.rationale,
            supported=bool(fix) and validation.ok,
        )

    def validate(self, device: Any, commands: List[str]) -> ValidationResult:
        adapter, profile = self.resolve(device)
        if not adapter:
            return ValidationResult(ok=False, blocked=commands, detail="no adapter")
        return adapter.validate(commands, profile)

    def supports_operation(self, device: Any, operation_name: str) -> bool:
        adapter, profile = self.resolve(device)
        if not adapter:
            return False
        try:
            return adapter.supports_operation(operation_name, profile)
        except Exception:
            return True

    def supported_intents(self, device: Any) -> List[str]:
        adapter, profile = self.resolve(device)
        if not adapter:
            return []
        try:
            return list(adapter.supported_intents(profile))
        except Exception:
            return []

    def translate_error(self, device: Any, raw_error: str) -> NormalizedError:
        adapter, _ = self.resolve(device)
        if not adapter:
            return NormalizedError(error_class=ErrorClass.UNKNOWN, message=raw_error, raw=raw_error)
        return adapter.translate_error(raw_error)
