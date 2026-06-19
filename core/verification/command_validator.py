"""
core/verification/command_validator.py
======================================
Pre-deploy command validation.

Before any [CONFIG] or [EXEC] command goes to the SSH transport, we
verify it against:
  1. The device's actual running version (from `show version`)
  2. The knowledge cache / vendor docs (does the command even exist?)
  3. A safety pattern check (no destructive ops like `reload`, `erase`)

Returns ValidationResult — operator sees badges per command.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

from core.knowledge.base import KnowledgeEntry, ConfidenceLevel
from core.knowledge.orchestrator import get_orchestrator
from core.verification.version_parser import DeviceVersion, compare_versions

logger = logging.getLogger("NetBrain.Verification.CommandValidator")


# ═══════════════════════════════════════════════════════════════════════════════
# Hard-coded safety patterns — never execute these
# ═══════════════════════════════════════════════════════════════════════════════

DESTRUCTIVE_PATTERNS = [
    r"^\s*reload\b",
    r"^\s*write\s+erase\b",
    r"^\s*erase\s+(?:startup|nvram|flash|all)",
    r"^\s*delete\s+(?:flash|nvram)",
    r"^\s*format\s+(?:flash|disk)",
    r"^\s*request\s+system\s+halt",
    r"^\s*request\s+system\s+power-off",
    r"^\s*no\s+ip\s+routing\b",
    r"^\s*no\s+line\s+vty\b",
    r"^\s*no\s+enable\s+(?:password|secret)\b",
    r"^\s*username\s+\S+\s+(?:password|secret)\s+0\b",  # plaintext password setting
    r"^\s*hostname\s+\S+\s*$",                            # hostname change
    r"^\s*factory-reset\b",
    r"^\s*restore\s+factory-default",
]

DESTRUCTIVE_RE = re.compile("|".join(DESTRUCTIVE_PATTERNS), re.IGNORECASE)


# ═══════════════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ValidationFinding:
    """One validation issue for one command."""
    level:   str = "info"     # 'pass' / 'warning' / 'block'
    message: str = ""
    detail:  str = ""


@dataclass
class CommandValidation:
    """Result for a single command."""
    command:     str = ""
    is_safe:     bool = True              # passes all checks
    is_blocked:  bool = False             # destructive — must NOT deploy
    findings:    List[ValidationFinding] = field(default_factory=list)
    knowledge:   Optional[KnowledgeEntry] = None   # source it was validated against

    def badge(self) -> str:
        if self.is_blocked:
            return "🚫 BLOCKED"
        if not self.findings:
            return "✅ OK"
        worst = max(f.level for f in self.findings) if self.findings else "info"
        if worst == "block":
            return "🚫 BLOCKED"
        if worst == "warning":
            return "⚠️ WARN"
        return "✅ OK"

    def is_deployable(self) -> bool:
        """Safe to send to the device?"""
        return self.is_safe and not self.is_blocked


@dataclass
class ValidationResult:
    """Result for a batch of commands."""
    per_command: List[CommandValidation] = field(default_factory=list)

    @property
    def all_safe(self) -> bool:
        return all(c.is_deployable() for c in self.per_command)

    @property
    def has_blocked(self) -> bool:
        return any(c.is_blocked for c in self.per_command)

    def summary(self) -> dict:
        return {
            "total":   len(self.per_command),
            "ok":      sum(1 for c in self.per_command if c.is_deployable() and not c.findings),
            "warn":    sum(1 for c in self.per_command if c.findings and not c.is_blocked),
            "blocked": sum(1 for c in self.per_command if c.is_blocked),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# CommandValidator
# ═══════════════════════════════════════════════════════════════════════════════

class CommandValidator:
    """Validates commands before they're sent to a device."""

    def __init__(self):
        self.orchestrator = get_orchestrator()

    # ── Public API ────────────────────────────────────────────────────────────

    def validate_batch(
        self,
        commands: List[str],
        device_version: Optional[DeviceVersion] = None,
    ) -> ValidationResult:
        """Validate a list of commands against a device version."""
        result = ValidationResult()
        for raw_cmd in commands:
            result.per_command.append(self.validate_one(raw_cmd, device_version))
        return result

    def validate_one(
        self,
        raw_command: str,
        device_version: Optional[DeviceVersion] = None,
    ) -> CommandValidation:
        """Validate a single command."""
        # Strip [CONFIG] / [EXEC] / [ROLLBACK] tags for validation purposes
        cmd = self._strip_tags(raw_command)

        v = CommandValidation(command=raw_command)

        # ── Check 1: Destructive pattern ──
        if DESTRUCTIVE_RE.match(cmd):
            v.is_blocked = True
            v.is_safe = False
            v.findings.append(ValidationFinding(
                level="block",
                message="DESTRUCTIVE command blocked",
                detail=f"Matches safety policy — '{cmd[:60]}' would not be auto-deployed.",
            ))
            return v

        # ── Check 2: Knowledge lookup (if vendor known) ──
        if device_version and device_version.vendor != "unknown":
            entry = self.orchestrator.lookup(
                device_version.vendor,
                cmd,
                device_version.platform,
            )
            v.knowledge = entry

            if entry.citation.confidence == ConfidenceLevel.UNVERIFIED:
                v.findings.append(ValidationFinding(
                    level="warning",
                    message="Command unverified against vendor docs",
                    detail="No source found; AI-generated. Review before deploying.",
                ))

            # ── Check 3: Version compatibility ──
            if (entry.min_version and device_version.release
                and entry.citation.confidence != ConfidenceLevel.UNVERIFIED):
                # Extract numeric from min_version, e.g. "IOS-XE 16.9" → "16.9"
                min_ver_match = re.search(r"\d+\.\d+(?:\.\d+)?", entry.min_version)
                if min_ver_match:
                    min_ver = min_ver_match.group(0)
                    cmp = compare_versions(device_version.release, min_ver)
                    if cmp < 0:
                        v.findings.append(ValidationFinding(
                            level="warning",
                            message=(
                                f"Command may require newer release. Device runs "
                                f"{device_version.release}, command needs ≥ {min_ver}."
                            ),
                            detail=f"Source: {entry.citation.source_url or 'docs'}",
                        ))

        return v

    @staticmethod
    def _strip_tags(raw: str) -> str:
        """Remove [CONFIG], [EXEC], [ROLLBACK] tags."""
        cmd = (raw or "").strip()
        for tag in ("[CONFIG]", "[EXEC]", "[ROLLBACK]"):
            if cmd.startswith(tag):
                cmd = cmd[len(tag):].strip()
                break
        return cmd


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton accessor
# ═══════════════════════════════════════════════════════════════════════════════

_validator_instance: Optional[CommandValidator] = None


def get_validator() -> CommandValidator:
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = CommandValidator()
    return _validator_instance
