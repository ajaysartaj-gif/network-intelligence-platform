"""Vendor-neutral / vendor-specific data model for the Diagnostic Capability
Framework.

Mirrors core.knowledge.compiler.protocol_registry's ProtocolSpec/AdapterSpec
split: a `DiagnosticCapability` describes WHAT a diagnostic action is (safety
level, preconditions, expected evidence) independent of any vendor CLI; a
`DiagnosticActionSpec` supplies the real commands/patterns one vendor family
uses to implement it. New technologies are pure data added to the registries
in `registry.py` -- nothing here or in the executor branches on a technology
name.

Preconditions use a small, fixed vocabulary (`PreconditionKind`) rather than
one bespoke field per technology, so the executor's precondition interpreter
never grows a new case just because a new technology is registered.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class PreconditionKind(str, Enum):
    CPU_BELOW = "cpu_below"
    MEMORY_BELOW = "memory_below"
    LOGGING_BUFFERED = "logging_buffered"


@dataclass
class Precondition:
    kind: PreconditionKind
    threshold: Optional[float] = None  # required for CPU_BELOW / MEMORY_BELOW


@dataclass
class DiagnosticCapability:
    """Vendor-neutral description of one bounded diagnostic action."""
    technology: str                      # registry key, e.g. "ospf", "hsrp"
    action: str                          # e.g. "adjacency_debug" -- a technology may register more than one
    description: str
    safety_level: str                    # "low" | "medium" | "high"
    preconditions: List[Precondition] = field(default_factory=list)
    max_duration_s: int = 10
    expected_evidence: str = ""
    requires_governance: bool = True


@dataclass
class DiagnosticActionSpec:
    """Vendor-specific rendering of a DiagnosticCapability into real commands.

    Defaults match IOS-like syntax, shared across every Cisco-family
    technology (`undebug all` / `show debugging` / `show processes cpu` are
    platform-wide, not per-protocol) -- most registry entries only need to
    override `enable_commands`.
    """
    enable_commands: List[str] = field(default_factory=list)
    disable_command: str = "undebug all"
    verify_command: str = "show debugging"
    verify_clean_pattern: str = r"debugging is on"
    collect_command: str = "show logging"
    cpu_check_command: str = "show processes cpu"
    cpu_parse_pattern: str = r"five seconds:\s*(\d+)%"
    memory_check_command: str = "show processes memory"
    memory_parse_pattern: str = r"Total:\s*\d+.*?Used:\s*(\d+)%?"
    logging_check_command: str = "show logging"
    logging_buffered_pattern: str = r"Buffered logging:\s*(\S+)"
