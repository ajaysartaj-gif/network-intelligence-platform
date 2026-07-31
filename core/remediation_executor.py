"""
core/remediation_executor.py
=============================
Safe execution of network fixes with pre-checks, post-checks, and automatic rollback.

Remediation flow:
  1. PRE-CHECK: Validate commands, device readiness, syntax
  2. APPROVAL: Get human sign-off (if required)
  3. EXECUTE: SSH to devices, run commands
  4. POST-CHECK: Verify fix achieved goal
  5. ROLLBACK: Auto-roll if post-check fails
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Enums & Data Models
# ═══════════════════════════════════════════════════════════════════════════════

class ExecutionStatus(str, Enum):
    """Execution pipeline status."""
    PENDING = "pending"
    PRE_CHECK_PASSED = "pre_check_passed"
    PRE_CHECK_FAILED = "pre_check_failed"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    EXECUTION_FAILED = "execution_failed"
    POST_CHECK_RUNNING = "post_check_running"
    POST_CHECK_PASSED = "post_check_passed"
    POST_CHECK_FAILED = "post_check_failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    COMPLETE = "complete"

    def is_terminal(self) -> bool:
        """Is this a terminal state?"""
        return self in (
            ExecutionStatus.PRE_CHECK_FAILED,
            ExecutionStatus.EXECUTION_FAILED,
            ExecutionStatus.ROLLED_BACK,
            ExecutionStatus.POST_CHECK_PASSED,
            ExecutionStatus.COMPLETE
        )


@dataclass
class RemediationPlan:
    """A fix ready for execution."""
    root_cause: str                              # "MTU mismatch between OSPF neighbors"
    fix_explanation: str                         # Human-readable explanation
    fix_commands: List[str]                      # ["(10.0.0.1) ip ospf mtu-ignore"]
    rollback_commands: List[str]                 # Undo the fix
    verification_commands: List[str]             # Prove fix worked
    expected_outcome: str                        # What should we see after fix?
    risk_level: str = "medium"                   # low | medium | high
    estimated_duration_seconds: float = 30.0


@dataclass
class ExecutionResult:
    """Result of fix execution."""
    plan: RemediationPlan
    status: ExecutionStatus = ExecutionStatus.PENDING
    pre_check_errors: List[str] = field(default_factory=list)
    pre_check_warnings: List[str] = field(default_factory=list)
    execution_output: Dict[str, Dict[str, str]] = field(default_factory=dict)  # device_ip -> {cmd: output}
    execution_errors: List[str] = field(default_factory=list)
    post_check_output: Dict[str, Dict[str, str]] = field(default_factory=dict)
    post_check_result: Optional[str] = None      # "success" | "failure reason"
    rolled_back: bool = False
    rollback_errors: List[str] = field(default_factory=list)
    outcome: Optional[str] = None                # "fixed" | "degraded" | "error"

    def is_success(self) -> bool:
        """Did the fix work?"""
        return self.outcome == "fixed" and not self.rolled_back


# ═══════════════════════════════════════════════════════════════════════════════
# Remediation Executor
# ═══════════════════════════════════════════════════════════════════════════════

class RemediationExecutor:
    """Execute network fixes safely with pre/post checks and rollback."""

    def __init__(self,
                 ssh_collector: Callable[[Any, List[str]], Dict[str, str]],
                 command_validator: Callable[[str], bool],
                 approval_required: bool = True,
                 auto_rollback_on_failure: bool = True):
        """
        Parameters
        ----------
        ssh_collector : Callable(device, commands) -> {cmd: output}
            SSH executor from IntentEngine or similar
        command_validator : Callable(cmd) -> bool
            Returns True if command is safe to execute (read-only check)
        approval_required : bool
            If True, execution waits for approval after pre-check
        auto_rollback_on_failure : bool
            If True, automatically rolls back if post-check fails
        """
        self.collector = ssh_collector
        self.validator = command_validator
        self.approval_required = approval_required
        self.auto_rollback = auto_rollback_on_failure
        self.history: List[ExecutionResult] = []

    def execute(self,
                plan: RemediationPlan,
                devices: List[Any],
                approval_callback: Optional[Callable[[RemediationPlan], bool]] = None) -> ExecutionResult:
        """
        Execute a remediation plan with full safety pipeline.

        Parameters
        ----------
        plan : RemediationPlan
            The fix to execute
        devices : List[Any]
            Approved device objects with .ip, .hostname, etc
        approval_callback : Callable(plan) -> bool
            Function to get human approval. If None, approval is auto-granted.

        Returns
        -------
        ExecutionResult
            Complete execution trace and outcome
        """
        result = ExecutionResult(plan=plan, status=ExecutionStatus.PENDING)

        # STEP 1: PRE-CHECK
        logger.info(f"Pre-checking fix: {plan.root_cause}")
        self._run_pre_checks(result, devices)

        if result.pre_check_errors:
            result.status = ExecutionStatus.PRE_CHECK_FAILED
            logger.error(f"Pre-check failed: {result.pre_check_errors}")
            self.history.append(result)
            return result

        result.status = ExecutionStatus.PRE_CHECK_PASSED
        if result.pre_check_warnings:
            logger.warning(f"Pre-check warnings: {result.pre_check_warnings}")

        # STEP 2: APPROVAL (if required)
        if self.approval_required:
            result.status = ExecutionStatus.AWAITING_APPROVAL
            if approval_callback:
                approved = approval_callback(plan)
                if not approved:
                    logger.info("Fix not approved by user")
                    self.history.append(result)
                    return result
            result.status = ExecutionStatus.APPROVED

        # STEP 3: EXECUTE
        logger.info(f"Executing fix on {len(devices)} device(s)")
        result.status = ExecutionStatus.EXECUTING
        self._execute_commands(result, devices)

        if result.execution_errors:
            result.status = ExecutionStatus.EXECUTION_FAILED
            logger.error(f"Execution failed: {result.execution_errors}")
            self.history.append(result)
            return result

        # STEP 4: POST-CHECK
        logger.info("Running post-check verification")
        result.status = ExecutionStatus.POST_CHECK_RUNNING
        self._run_post_checks(result, devices)

        if result.post_check_result == "success":
            result.status = ExecutionStatus.POST_CHECK_PASSED
            result.outcome = "fixed"
            logger.info("✅ Fix verified: Post-check passed")
        else:
            result.status = ExecutionStatus.POST_CHECK_FAILED
            logger.warning(f"❌ Post-check failed: {result.post_check_result}")

            # STEP 5: AUTO-ROLLBACK (if enabled and failure confirmed)
            if self.auto_rollback and result.post_check_result != "success":
                logger.warning("🔄 Initiating automatic rollback")
                result.status = ExecutionStatus.ROLLING_BACK
                self._run_rollback(result, devices)

                if result.rollback_errors:
                    result.outcome = "error"  # Rollback failed — escalate
                    logger.error(f"❌ Rollback failed: {result.rollback_errors}")
                else:
                    result.rolled_back = True
                    result.status = ExecutionStatus.ROLLED_BACK
                    result.outcome = "degraded"
                    logger.warning("✅ Rollback completed")

        result.status = ExecutionStatus.COMPLETE
        self.history.append(result)
        return result

    def _run_pre_checks(self, result: ExecutionResult, devices: List[Any]) -> None:
        """Validate fix before execution."""
        plan = result.plan

        # CHECK 1: Are all target devices reachable?
        device_map = {d.ip: d for d in devices}
        for cmd in plan.fix_commands:
            device_ip = self._extract_device_ip(cmd)
            if device_ip and device_ip not in device_map:
                result.pre_check_errors.append(f"Device {device_ip} not found in approved list")
            elif device_ip and not self._is_reachable(device_ip):
                result.pre_check_errors.append(f"Device {device_ip} not reachable (ping failed)")

        # CHECK 2: Are commands safe (not dangerous)?
        for cmd in plan.fix_commands:
            actual_cmd = self._extract_command(cmd)
            if actual_cmd and not self.validator(actual_cmd):
                result.pre_check_errors.append(f"Unsafe/destructive command: {actual_cmd}")

        # CHECK 3: Command syntax basic validation
        for cmd in plan.fix_commands:
            if len(cmd) > 500:
                result.pre_check_warnings.append(f"Command very long (>{len(cmd)} chars): may fail on some devices")

        # CHECK 4: Rollback commands present
        if not plan.rollback_commands:
            result.pre_check_warnings.append("No rollback commands provided — will not be able to undo if needed")

        logger.info(f"Pre-check: {len(result.pre_check_errors)} errors, {len(result.pre_check_warnings)} warnings")

    def _execute_commands(self, result: ExecutionResult, devices: List[Any]) -> None:
        """Run fix commands on devices."""
        plan = result.plan
        device_map = {d.ip: d for d in devices}

        # Group commands by device
        commands_by_device = self._group_commands_by_device(plan.fix_commands)

        for device_ip, cmds in commands_by_device.items():
            device = device_map.get(device_ip)
            if not device:
                result.execution_errors.append(f"Device {device_ip} not found")
                continue

            try:
                logger.info(f"Executing {len(cmds)} command(s) on {device.hostname}")
                outputs = self.collector(device, cmds)
                result.execution_output[device_ip] = outputs

                # Check for error indicators in output
                for cmd, output in outputs.items():
                    if "error" in output.lower() or "% unknown command" in output.lower():
                        result.execution_errors.append(
                            f"Device {device.hostname}: {cmd} returned error: {output[:100]}"
                        )

            except Exception as e:
                result.execution_errors.append(f"SSH to {device.hostname} ({device_ip}): {str(e)}")
                logger.error(f"Execution error on {device_ip}: {str(e)}")

    def _run_post_checks(self, result: ExecutionResult, devices: List[Any]) -> None:
        """Verify fix achieved expected outcome."""
        plan = result.plan
        device_map = {d.ip: d for d in devices}

        # Collect verification output
        commands_by_device = self._group_commands_by_device(plan.verification_commands)

        for device_ip, cmds in commands_by_device.items():
            device = device_map.get(device_ip)
            if not device:
                continue

            try:
                outputs = self.collector(device, cmds)
                result.post_check_output[device_ip] = outputs

            except Exception as e:
                logger.warning(f"Post-check SSH to {device.hostname} failed: {str(e)}")

        # Interpret verification output
        result.post_check_result = self._interpret_verification(
            plan.expected_outcome,
            result.post_check_output
        )

    def _run_rollback(self, result: ExecutionResult, devices: List[Any]) -> None:
        """Apply rollback commands."""
        plan = result.plan
        device_map = {d.ip: d for d in devices}

        commands_by_device = self._group_commands_by_device(plan.rollback_commands)

        for device_ip, cmds in commands_by_device.items():
            device = device_map.get(device_ip)
            if not device:
                result.rollback_errors.append(f"Device {device_ip} not found for rollback")
                continue

            try:
                logger.warning(f"Rolling back {len(cmds)} command(s) on {device.hostname}")
                self.collector(device, cmds)

            except Exception as e:
                result.rollback_errors.append(f"Rollback on {device.hostname}: {str(e)}")
                logger.error(f"Rollback error on {device_ip}: {str(e)}")

    # ── Helper methods ─────────────────────────────────────────────────────────

    @staticmethod
    def _extract_device_ip(cmd: str) -> Optional[str]:
        """Extract device IP from command in format '(10.0.0.1) show running'."""
        if cmd.startswith("("):
            try:
                end = cmd.index(")")
                return cmd[1:end]
            except (ValueError, IndexError):
                return None
        return None

    @staticmethod
    def _extract_command(cmd: str) -> str:
        """Extract actual command from format '(10.0.0.1) show running'."""
        if cmd.startswith("("):
            try:
                end = cmd.index(")")
                return cmd[end + 1:].strip()
            except ValueError:
                return cmd
        return cmd

    @staticmethod
    def _group_commands_by_device(commands: List[str]) -> Dict[str, List[str]]:
        """Parse (device_ip) cmd format and group by device."""
        grouped: Dict[str, List[str]] = {}
        for cmd in commands:
            device_ip = RemediationExecutor._extract_device_ip(cmd)
            actual_cmd = RemediationExecutor._extract_command(cmd)

            if device_ip:
                if device_ip not in grouped:
                    grouped[device_ip] = []
                grouped[device_ip].append(actual_cmd)

        return grouped

    @staticmethod
    def _is_reachable(ip: str, timeout_seconds: int = 2) -> bool:
        """Quick ping check to verify device is reachable."""
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", str(timeout_seconds), ip],
                capture_output=True,
                timeout=timeout_seconds + 1
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _interpret_verification(expected_outcome: str,
                               verification_output: Dict[str, Dict[str, str]]) -> str:
        """
        Interpret post-check output. Does it match expected outcome?

        Returns: "success" | "failure: reason"
        """
        if not verification_output:
            return "failure: no post-check output collected"

        # Combine all output
        all_output = "\n".join([
            output
            for outputs in verification_output.values()
            for output in outputs.values()
        ])

        # Simple heuristic matching
        # In production, this should be done by the hypothesis engine
        # or via AI interpretation
        if "full" in expected_outcome.lower() and "full" in all_output.lower():
            return "success"
        elif "up" in expected_outcome.lower() and "down" not in all_output.lower():
            return "success"
        elif expected_outcome.lower() in all_output.lower():
            return "success"
        elif "error" in all_output.lower():
            return "failure: error in verification output"
        else:
            return "failure: expected outcome not found in verification"
