"""
Universal Vendor Adapter Framework — the Vendor SDK
===================================================
Every vendor adapter implements this ONE interface. The Troubleshooting Engine
communicates ONLY through it and never contains `if vendor == ...` logic.

Methods marked @abstractmethod are required; the rest have safe defaults so
simple adapters stay small. Additional methods may be added by adapters freely.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .models import (
    NormalizedError, NormalizedObject, ValidationResult, VendorProfile, ErrorClass,
)
from .operations import Operation, RemediationIntent, RemediationPlan


@dataclass
class DeviceProbe:
    """Lightweight input to detect(): whatever is already known about a device
    plus an optional transport callable for a single discovery command. Adapters
    must not assume any particular hint is present."""
    device: Any = None
    hints: Dict[str, Any] = field(default_factory=dict)   # e.g. sys_descr, banner, api_type
    run: Optional[Callable[[str], str]] = None            # optional: run one probe command


@dataclass
class Transport:
    """Vendor-neutral transport handle passed to execute(). The adapter decides
    which commands to send; the transport only moves bytes."""
    send: Callable[[Any, List[str]], Dict[str, str]]      # (device, commands) -> {cmd: output}


class VendorAdapter(ABC):
    """The universal Vendor SDK. Implement one per vendor/platform family."""

    #: unique adapter id used ONLY by the registry/gateway for resolution.
    #: This is never used by the engine for branching.
    name: str = "unnamed"
    #: priority when several adapters match equally (higher wins); generic uses low.
    priority: int = 50

    # ── identity ────────────────────────────────────────────────────────────────
    @abstractmethod
    def detect(self, probe: DeviceProbe) -> VendorProfile:
        """Return a VendorProfile with a confidence 0..1 (0 = not mine)."""

    @abstractmethod
    def capabilities(self, profile: VendorProfile) -> List[str]:
        """Return discoverable capability names (free-form, e.g. 'routing.ospf')."""

    def discover(self, profile: VendorProfile, transport: "Transport") -> List[NormalizedObject]:
        """Optional inventory/topology discovery. Default: nothing."""
        return []

    # ── evidence path: intent -> command -> raw -> normalized ───────────────────
    @abstractmethod
    def build_command(self, operation: Operation, profile: VendorProfile) -> List[str]:
        """Translate a normalized Operation into vendor command(s)."""

    def execute(self, device: Any, commands: List[str], transport: "Transport") -> Dict[str, str]:
        """Run commands via the neutral transport. Adapters may override for API/telemetry."""
        if transport is None or not commands:
            return {}
        return transport.send(device, commands)

    @abstractmethod
    def parse_output(self, operation: Operation, raw: Dict[str, str],
                     profile: VendorProfile) -> List[NormalizedObject]:
        """Convert raw CLI/API/telemetry output into NormalizedObjects."""

    def normalize(self, objects: List[NormalizedObject]) -> List[NormalizedObject]:
        """Optional post-normalization hook. Default: pass-through."""
        return objects

    # ── remediation path: intent -> vendor syntax (+ rollback + verification) ────
    @abstractmethod
    def build_fix(self, intent: RemediationIntent, profile: VendorProfile) -> List[str]:
        """Translate a RemediationIntent into vendor configuration commands."""

    @abstractmethod
    def build_rollback(self, intent: RemediationIntent, profile: VendorProfile) -> List[str]:
        """Generate rollback for the same intent. MUST accompany every fix."""

    def build_verification(self, intent: RemediationIntent, profile: VendorProfile) -> List[str]:
        """Post-change verification commands. Default: none."""
        return []

    def validate(self, commands: List[str], profile: VendorProfile) -> ValidationResult:
        """Vendor-side safety/syntax check. Default: allow, no warnings."""
        return ValidationResult(ok=True)

    # ── errors ──────────────────────────────────────────────────────────────────
    @abstractmethod
    def translate_error(self, raw_error: str) -> NormalizedError:
        """Convert a vendor-specific error string into a NormalizedError."""

    # ── capability / operation support (helpers; overridable) ───────────────────
    def supports_operation(self, operation_name: str, profile: VendorProfile) -> bool:
        return True

    def supports_intent(self, intent_name: str, profile: VendorProfile) -> bool:
        return True
