"""
Canonical Execution Pipeline
============================

ONE reusable execution path shared by every runtime (Admin Configuration,
NLP / Intent, Copilot, Autonomous Monitor).

It owns the sequence:

    Device Facts → Intent → Configuration Generation → Deployment
                 → Verification → Learning

…by REUSING the existing implementations — it introduces no new deployment,
verification, memory, or learning logic:

    • Deployment    → core.network_fixer.NetworkFixer.fix   (the ONLY deployer)
    • Verification  → core.intelligence.outcome_contract.OutcomeContractEngine
    • Workflow      → core.workflow_tracker.WorkflowTracker
    • Memory        → core.intelligence.operational_memory + core.intelligence.memory
    • Learning      → core.intelligence.learning.LearningEngine
    • (optional)    → core.ai_config.generate_config / core.intent_engine.IntentEngine

The UI no longer calls ConnectHandler.send_config_set directly; it calls
ExecutionPipeline.deploy(), which delegates the single device write to
NetworkFixer.fix().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable


@dataclass
class ExecutionResult:
    """Outcome of one execution through the canonical pipeline."""
    device: str
    success: bool = False
    deployed_commands: List[str] = field(default_factory=list)
    fix_result: Any = None          # core.network_fixer.FixResult
    contract: Any = None            # OutcomeContractEngine result (or None)
    verified: Optional[bool] = None
    error: str = ""
    governance: Any = None          # core.governance.GovernanceContract (as dict)
    policy: Any = None              # core.policy.PolicyContract (as dict)
    logs: List[str] = field(default_factory=list)


class ExecutionPipeline:
    """
    Single execution path. Construct once with the existing singletons and call
    ``deploy()`` from every runtime. Deployment is always delegated to the
    injected NetworkFixer; nothing here opens its own config session.
    """

    def __init__(self, fixer, tracker=None, ai_call: Optional[Callable] = None):
        # All reused, already-constructed objects — no new engines created here.
        self.fixer = fixer            # core.network_fixer.NetworkFixer (required)
        self.tracker = tracker        # core.workflow_tracker.WorkflowTracker (optional)
        self.ai_call = ai_call        # call_ai (optional; only needed for verification)

    # ── optional generation stage (reuses generate_config) ──────────────────
    def generate(self, request: str, device: str, device_facts: str = "",
                 fleet_context: str = "", inventory_summary: str = "") -> Dict[str, Any]:
        """Reuse ai_config.generate_config. Callers that already generated their
        commands skip this; it exists so the pipeline can own the stage without
        duplicating any generation logic."""
        from core.ai_config import generate_config
        return generate_config(
            request, device, self.ai_call,
            device_facts=device_facts,
            fleet_context=fleet_context,
            inventory_summary=inventory_summary,
        )

    # ── canonical deployment + verification + learning ──────────────────────
    def deploy(
        self,
        *,
        device: str,
        fix_commands: List[str],
        device_config: Optional[Dict[str, Any]] = None,
        connection=None,
        exec_commands: Optional[List[str]] = None,
        verify_commands: Optional[List[str]] = None,
        intent: str = "",
        protocol: str = "",
        site: str = "",
        operator: str = "",
        verify: bool = False,
        run_command: Optional[Callable] = None,
        device_facts: str = "",
        save: bool = False,
        config_mode: bool = True,
        step_logger: Optional[Callable] = None,
        anomaly: Optional[Dict[str, Any]] = None,
        govern: bool = True,
        rollback_commands: Optional[List[str]] = None,
        govern_strict: bool = False,
        policy: bool = True,
        policy_strict: bool = False,
        autonomous: bool = False,
    ) -> ExecutionResult:
        """
        Deploy ``fix_commands`` to ``device`` through the single deployer
        (NetworkFixer.fix) and, when ``verify`` is set and an ``ai_call`` +
        ``run_command`` are available, prove the outcome and record/learn from
        it — exactly the post-deploy sequence the admin path used inline.

        Either ``device_config`` (NetworkFixer opens the session) or
        ``connection`` (an already-open session, left open for the caller) must
        be supplied.
        """
        result = ExecutionResult(device=device)

        def _log(msg: str) -> None:
            result.logs.append(str(msg))
            if step_logger:
                try:
                    step_logger(msg)
                except Exception:
                    pass

        # Optional workflow run (best-effort; never blocks deployment)
        if self.tracker is not None:
            try:
                self.tracker.create_run(f"deploy:{device}")
            except Exception:
                pass

        # ── GOVERNANCE GATE (Milestone 4 — Enterprise Change Governance) ──
        # Final engineering decision BEFORE any device write. Every deployment
        # request passes through here. Governance reuses Compliance, the autonomy
        # Authorization gate, Risk, Rollback readiness and (optional) Simulation
        # to authorize or STOP the deployment. The LLM never decides deployment
        # safety. On a non-authorized decision we return WITHOUT calling
        # NetworkFixer; governance never opens a session or writes config itself.
        if govern:
            try:
                from core.governance import govern_change
                _gov = govern_change(
                    device=device,
                    commands=list(fix_commands or []),
                    intent=intent,
                    protocol=protocol,
                    site=site,
                    operator=operator,
                    rollback_commands=rollback_commands,
                    device_facts=device_facts,
                    strict=govern_strict,
                )
                result.governance = _gov.to_dict()
                for w in _gov.warnings:
                    _log(f"GOVERNANCE WARNING: {w}")
                if not _gov.authorized:
                    result.success = False
                    result.error = _gov.summary()
                    _log(f"GOVERNANCE: {_gov.status.value} — deployment stopped.")
                    return result  # STOP — do NOT reach the deployer
            except Exception as _ge:
                # Governance must never crash deployment; fail-open on its own
                # error (never on an explicit non-authorized verdict). The bypass
                # is recorded explicitly so it is auditable, never silent.
                result.governance = {"status": "not_evaluated",
                                     "bypassed": True, "reason": f"error: {_ge}"}
                _log(f"governance skipped (error): {_ge}")
        else:
            # Explicit, auditable bypass — governance was deliberately disabled.
            result.governance = {"status": "not_evaluated",
                                 "bypassed": True, "reason": "govern=False"}
            _log("GOVERNANCE: not evaluated (govern=False).")

        # ── POLICY GATE (Milestone 5 — Enterprise Policy & Autonomous Control) ──
        # Organizational permission BEFORE any device write, evaluated AFTER and
        # independently of Governance. Reuses the business-rules subsystem (change
        # freeze, maintenance window, business criticality, operator/role and
        # autonomous eligibility). On a non-permitted decision we return WITHOUT
        # calling NetworkFixer; policy never deploys, generates, or reasons.
        if policy:
            try:
                from core.policy import evaluate_policy
                _pol = evaluate_policy(
                    device=device, intent=intent, operator=operator,
                    protocol=protocol, site=site,
                    autonomous=autonomous, strict=policy_strict,
                )
                result.policy = _pol.to_dict()
                for w in _pol.business_warnings:
                    _log(f"POLICY WARNING: {w}")
                if not _pol.permitted:
                    result.success = False
                    result.error = _pol.summary()
                    _log(f"POLICY: {_pol.status.value} — execution stopped.")
                    return result  # STOP — do NOT reach the deployer
            except Exception as _pe:
                # Policy must never crash deployment; fail-open on its own error
                # (never on an explicit non-permitted decision). Bypass recorded.
                result.policy = {"status": "not_evaluated",
                                 "bypassed": True, "reason": f"error: {_pe}"}
                _log(f"policy skipped (error): {_pe}")
        else:
            result.policy = {"status": "not_evaluated",
                             "bypassed": True, "reason": "policy=False"}
            _log("POLICY: not evaluated (policy=False).")

        # ── DEPLOYMENT — the ONLY device write, via NetworkFixer ─────────────
        fr = self.fixer.fix(
            anomaly or {"device": device},
            device_config=device_config,
            step_logger=_log,
            command_override={
                "diagnostic": exec_commands or [],
                "fix": fix_commands or [],
                "verify": verify_commands or [],
            },
            connection=connection,
            save=save,
            config_mode=config_mode,
        )
        result.fix_result = fr
        result.success = bool(getattr(fr, "success", False))
        result.deployed_commands = list(getattr(fr, "commands_executed", []) or [])
        if getattr(fr, "error", ""):
            result.error = fr.error

        # ── VERIFICATION + MEMORY + LEARNING (reused, opt-in) ────────────────
        # Mirrors the admin block precisely; runs only when the caller supplies
        # the same inputs it had before, so no path gains or loses behavior.
        if verify and self.ai_call and intent and run_command and fix_commands:
            try:
                from core.intelligence.outcome_contract import OutcomeContractEngine
                _oce = OutcomeContractEngine(ai_call=self.ai_call)
                contract = _oce.enforce(
                    intent=intent,
                    device_name=device,
                    applied_commands=fix_commands,
                    run_command=run_command,
                    device_facts=device_facts,
                    converge_timeout_s=45,
                    poll_interval_s=5,
                )
                result.contract = contract
                result.verified = bool(getattr(contract, "satisfied", None))
                try:
                    _log(contract.to_log())
                except Exception:
                    pass

                # Operational memory (verified change records itself)
                try:
                    from core.intelligence.operational_memory import get_operational_memory
                    get_operational_memory().record_from_contract(
                        contract, site=site, protocol=protocol,
                        operator=operator, commands=fix_commands,
                    )
                except Exception as _me:
                    _log(f"[MEMORY] not recorded: {_me}")

                # Derived/consolidated memory
                try:
                    from core.intelligence.memory import get_memory_system
                    get_memory_system().record_from_contract(
                        contract, site=site, protocol=protocol,
                        operator=operator, commands=fix_commands,
                    )
                except Exception as _cme:
                    _log(f"[MEMORY+] not consolidated: {_cme}")

                # Learning loop
                try:
                    from core.intelligence.learning import get_learning_engine
                    get_learning_engine().learn_from_contract(
                        contract, site=site, protocol=protocol,
                        operator=operator, commands=fix_commands,
                    )
                except Exception as _lme:
                    _log(f"[LEARN] not recorded: {_lme}")

            except Exception as _ce:
                _log(f"[CONTRACT] could not run outcome contract: {_ce}")

        return result


# ── module-level singleton ──────────────────────────────────────────────────
_PIPELINE: Optional[ExecutionPipeline] = None


def get_execution_pipeline(fixer, tracker=None, ai_call: Optional[Callable] = None) -> ExecutionPipeline:
    """Return the shared pipeline, constructing it once from existing objects.
    Re-binds the (optional) tracker/ai_call if they were not set yet."""
    global _PIPELINE
    if _PIPELINE is None:
        _PIPELINE = ExecutionPipeline(fixer, tracker=tracker, ai_call=ai_call)
    else:
        if tracker is not None and _PIPELINE.tracker is None:
            _PIPELINE.tracker = tracker
        if ai_call is not None and _PIPELINE.ai_call is None:
            _PIPELINE.ai_call = ai_call
    return _PIPELINE
