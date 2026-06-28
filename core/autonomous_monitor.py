"""
Autonomous Monitor — orchestrates the detect → analyze → fix → verify cycle.
Designed to be called from Streamlit's polling loop (no background threads).
Records every action in WorkflowTracker for real-time UI visualization.

Phase 1 (steps 1-4): Telemetry → Detection → RCA → Planning.
  Ends by storing data in pending_approvals and awaiting operator approval.
Phase 2 (steps 5-7): Fix Execution → Verification → Closure.
  Only runs after an operator approves the pending run.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Any, Optional

from core.workflow_tracker import WorkflowTracker, WorkflowRun, StepStatus

logger = logging.getLogger(__name__)

# Live-only mode: show ONLY the real GNS3 network (devices + anomalies from the
# log pipeline). Set NETBRAIN_LIVE_ONLY=0 to re-enable the built-in demo simulator.
LIVE_ONLY = os.environ.get("NETBRAIN_LIVE_ONLY", "1").strip().lower() not in ("0", "false", "no")

try:
    from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
    NETMIKO_AVAILABLE = True
except ImportError:
    NETMIKO_AVAILABLE = False


class AutonomousMonitor:
    """
    Runs one autonomous remediation cycle per call to run_cycle().
    Integrates telemetry → anomaly detection → AI RCA → approval gate
    → fix execution → verification → closure.

    Approval gate:
      - Phase 1 (steps 1-4) completes and waits in pending_approvals.
      - Phase 2 (steps 5-7) only runs once the operator approves.
    """

    def __init__(
        self,
        orchestrator,           # OperationsOrchestrator
        workflow_tracker: WorkflowTracker,
        network_fixer,          # NetworkFixer
        ai_call_fn=None,        # callable(str) → str
    ):
        self.orchestrator = orchestrator
        self.tracker = workflow_tracker
        self.fixer = network_fixer
        self.ai_call = ai_call_fn
        self.cycle_count = 0
        self.last_cycle_result: Dict[str, Any] = {}
        self.last_fix_result: Optional[Dict[str, Any]] = None

        # GitHub log source — reads router syslog pushed to the gns3-router-logs
        # repo.  This is the primary anomaly source for cloud deployments where
        # the GNS3 lab is not directly reachable over SSH.
        try:
            from core.github_log_engine import GitHubLogEngine
            self.github_log = GitHubLogEngine()
        except Exception as e:  # pragma: no cover
            logger.warning(f"[MONITOR] GitHub log engine init failed: {e}")
            self.github_log = None

        # sig → run_id; only removed on verified recovery or operator rejection
        self._active_signatures: Dict[str, str] = {}

        # run_id → {run, anomaly, plan, rca, incident_id}
        self.pending_approvals: Dict[str, Dict] = {}

        # Sets populated by the UI / operator
        self.approved_run_ids: set = set()
        self.rejected_run_ids: set = set()
        # Signatures recently remediated → (cycle_count when fixed). Prevents the
        # fix→up→down flapping loop: we do NOT re-act on an interface we just
        # brought up. Cleared after REMEDIATION_COOLDOWN cycles AND only once the
        # interface has been confirmed stable (not in the current anomaly set).
        self._remediation_cooldown: Dict[str, int] = {}
        self.REMEDIATION_COOLDOWN = 6  # cycles to suppress re-action after a fix

    # ── public API ──────────────────────────────────────────────────────────

    def run_cycle(self) -> Dict[str, Any]:
        """
        Execute one monitoring cycle.  Call from Streamlit's polling loop.
        Returns a summary dict for the UI.
        """
        self.cycle_count += 1
        cycle_start = datetime.utcnow()

        try:
            # ── 1. Process rejections ────────────────────────────────────────
            for run_id in list(self.rejected_run_ids):
                data = self.pending_approvals.pop(run_id, None)
                self.rejected_run_ids.discard(run_id)
                if data:
                    run: WorkflowRun = data["run"]
                    # Remove the signature so the cycle can re-evaluate later
                    anomaly = data["anomaly"]
                    sig = f"{anomaly.get('device')}:{anomaly.get('type')}"
                    self._active_signatures.pop(sig, None)
                    run.complete("Fix rejected by operator")
                    logger.info(f"[MONITOR] Run {run_id} rejected by operator")

            # ── 2. Process approvals ─────────────────────────────────────────
            for run_id in list(self.approved_run_ids):
                data = self.pending_approvals.pop(run_id, None)
                self.approved_run_ids.discard(run_id)
                if data:
                    logger.info(f"[MONITOR] Run {run_id} approved — starting Phase 2")
                    self._run_phase2(data["run"], data["anomaly"], data)

            # ── 3. Telemetry + anomaly detection ─────────────────────────────
            if LIVE_ONLY:
                # Live network only: no simulated devices/anomalies. On the
                # first cycle after a (re)start, purge any stale demo state.
                if self.cycle_count == 1:
                    self._purge_demo_state()
                # Poll the GitHub log first (this discovers real routers), then
                # register them so the dashboard shows the live topology.
                anomalies = self._poll_github_logs()
                self._register_live_devices()
                telemetry = {"device_metrics": self.orchestrator.state.get_all_device_metrics()}
            else:
                # Legacy demo mode (set NETBRAIN_LIVE_ONLY=0 to enable).
                self.orchestrator.simulator.step()
                telemetry = self.orchestrator.telemetry.collect_all_telemetry()
                anomalies = self.orchestrator.telemetry.detect_anomalies()

            # ── 4. External log polling (merges unique anomalies) ────────────
            existing_sigs = {
                f"{a.get('device')}:{a.get('type')}" for a in anomalies
            }

            # 4a. GitHub log source (router → local → GitHub → here).
            #     Primary source for cloud deployments.
            if not LIVE_ONLY:
                for ga in self._poll_github_logs():
                    gsig = f"{ga.get('device')}:{ga.get('type')}"
                    if gsig not in existing_sigs:
                        anomalies.append(ga)
                        existing_sigs.add(gsig)

            # 4b. Direct GNS3 SSH syslog (only when NOT in live-only mode).
            #     In live-only mode the GitHub log is the sole source, so we must
            #     NOT open an SSH session every cycle — doing so spams the router
            #     console with 'SSH-2.0-paramiko' and corrupts the Telnet console.
            if not LIVE_ONLY:
                for ga in self._poll_gns3_logs():
                    gsig = f"{ga.get('device')}:{ga.get('type')}"
                    if gsig not in existing_sigs:
                        anomalies.append(ga)
                        existing_sigs.add(gsig)

            # ── 5. Kick off Phase 1 for new high/critical anomalies ──────────
            workflows_started = []
            current_sigs = {
                f"{a.get('device')}:{a.get('type')}"
                for a in anomalies
                if a.get("severity") in ("critical", "high")
            }

            for anomaly in anomalies:
                if anomaly.get("severity") not in ("critical", "high"):
                    continue
                sig = f"{anomaly.get('device')}:{anomaly.get('type')}"
                if sig in self._active_signatures:
                    continue  # already being handled
                if sig in self._remediation_cooldown:
                    # We recently fixed this. Don't re-act on a flap.
                    logger.info(f"[MONITOR] {sig} in remediation cooldown — skipping re-action")
                    continue
                run = self._run_phase1(anomaly)
                if run:
                    self._active_signatures[sig] = run.run_id
                    workflows_started.append(run.run_id)

            # ── 5b. Expire cooldowns once enough cycles have passed ──────────
            for sig in list(self._remediation_cooldown.keys()):
                if self.cycle_count - self._remediation_cooldown[sig] >= self.REMEDIATION_COOLDOWN:
                    self._remediation_cooldown.pop(sig, None)

            # ── 6. Clean up stale signatures (anomaly no longer present) ──────
            for sig in list(self._active_signatures.keys()):
                if sig not in current_sigs:
                    # Only remove if there is no pending approval for this sig
                    run_id = self._active_signatures[sig]
                    if run_id not in self.pending_approvals:
                        self._active_signatures.pop(sig, None)

            # ── 7. Build result summary ───────────────────────────────────────
            duration_ms = (datetime.utcnow() - cycle_start).total_seconds() * 1000
            result = {
                "cycle": self.cycle_count,
                "timestamp": datetime.utcnow().isoformat(),
                "duration_ms": round(duration_ms, 1),
                "devices_polled": len(telemetry.get("device_metrics", {})),
                "anomalies_found": len(anomalies),
                "workflows_started": len(workflows_started),
                "active_workflows": len(self.tracker.get_active_runs()),
                "pending_approvals": len(self.pending_approvals),
                "anomalies": anomalies,
            }
            self.last_cycle_result = result
            return result

        except Exception as e:
            logger.error(f"Monitor cycle {self.cycle_count} failed: {e}", exc_info=True)
            return {
                "cycle": self.cycle_count,
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
                "anomalies_found": 0,
                "workflows_started": 0,
            }

    # ── Phase 1: Telemetry → Detection → RCA → Planning ─────────────────────

    def _run_phase1(self, anomaly: Dict[str, Any]) -> Optional[WorkflowRun]:
        """
        Execute steps 1-4 for a single anomaly.
        Stores result in pending_approvals and returns the WorkflowRun.
        Does NOT start steps 5-7.
        """
        device = anomaly.get("device", "unknown")
        anomaly_type = anomaly.get("type", "unknown")
        severity = anomaly.get("severity", "high")

        incident_id = self._ensure_incident(anomaly)
        run = self.tracker.create_run(incident_id, device, anomaly_type, severity)
        run_id = run.run_id
        logger.info(f"[MONITOR] Phase 1 start: {run_id} — {anomaly_type} on {device}")

        try:
            # ── STEP 1: Telemetry Collection ─────────────────────────────────
            self.tracker.step_start(run_id, 1)
            self.tracker.step_log(run_id, 1, f"Collecting live telemetry from {device}")
            metrics = self.orchestrator.state.get_device_metrics(device)
            if metrics:
                self.tracker.step_log(run_id, 1,
                    f"CPU: {metrics.cpu:.1f}% | Memory: {metrics.memory:.1f}% | "
                    f"Latency: {metrics.latency_ms:.1f}ms | Loss: {metrics.packet_loss_pct:.2f}%")
            self.tracker.step_complete(
                run_id, 1,
                f"Telemetry collected from {device}",
                data={
                    "metrics": {
                        "cpu": getattr(metrics, "cpu", 0),
                        "memory": getattr(metrics, "memory", 0),
                    }
                },
            )

            # ── STEP 2: Anomaly Detection ─────────────────────────────────────
            self.tracker.step_start(run_id, 2)
            desc = anomaly.get("description", f"{anomaly_type} detected on {device}")
            self.tracker.step_log(run_id, 2, f"Anomaly confirmed: {desc}")
            threshold_info = self._get_threshold_info(anomaly)
            self.tracker.step_log(run_id, 2, threshold_info)
            self.tracker.step_complete(
                run_id, 2,
                f"Anomaly: {anomaly_type} | Severity: {severity.upper()}",
            )

            # ── STEP 3: AI Root Cause Analysis ────────────────────────────────
            self.tracker.step_start(run_id, 3)
            self.tracker.step_log(run_id, 3, "Querying AI for root cause analysis...")
            rca = self._run_rca(anomaly, incident_id)
            self.tracker.step_log(run_id, 3, f"AI RCA: {rca[:200]}")
            self.tracker.step_complete(run_id, 3, rca[:300], data={"rca": rca})
            self.orchestrator.state.update_incident(
                incident_id, status="investigating",
                note=f"AI RCA: {rca[:200]}"
            )

            # ── STEP 4: Remediation Planning (AI-generated + safety-filtered) ─
            self.tracker.step_start(run_id, 4)

            ai_commands = None
            ai_status = "unavailable"
            ai_block_reasons: List[str] = []
            try:
                from core.ai_remediation import generate_fix_commands
                device_facts = self._device_facts(device)
                knowledge = self._retrieve_knowledge(anomaly)
                gen = generate_fix_commands(anomaly, self.ai_call, device_facts, knowledge)
                ai_status = gen["status"]
                if ai_status == "ok":
                    ai_commands = gen["commands"]
                    self.tracker.step_log(run_id, 4, "AI generated remediation commands (passed safety filter)")
                    for c in ai_commands.get("fix", []):
                        self.tracker.step_log(run_id, 4, f"  • {c}")
                elif ai_status == "unsafe":
                    ai_block_reasons = gen["reasons"]
                    self.tracker.step_log(run_id, 4,
                        f"AI proposed UNSAFE commands — blocked: {gen.get('blocked')}")
                else:
                    ai_block_reasons = gen["reasons"]
                    self.tracker.step_log(run_id, 4,
                        f"AI unavailable: {'; '.join(gen.get('reasons', []))}")
            except Exception as e:
                logger.warning(f"[MONITOR] AI command generation error: {e}")
                ai_block_reasons = [str(e)]

            # Human-readable plan for the card (descriptive).
            plan = self._build_plan(anomaly, rca)

            # Decide whether this run can auto-remediate:
            #  - ai_status == "ok"  → use AI commands.
            #  - AI unavailable BUT a safe built-in fix exists for this known
            #    anomaly type → fall back to the built-in commands (so basic
            #    remediation keeps working even with no AI / free-tier down).
            #  - AI proposed UNSAFE commands → always manual (never auto-run).
            #  - AI unavailable AND no built-in fix → manual.
            SAFE_BUILTIN_TYPES = {"interface_down"}   # has a known-safe 'no shutdown'
            use_builtin_fallback = (
                ai_status in ("unavailable", "empty")
                and anomaly_type in SAFE_BUILTIN_TYPES
            )
            if ai_status == "ok":
                needs_manual = False
            elif ai_status == "unsafe":
                needs_manual = True            # never auto-run unsafe AI output
            elif use_builtin_fallback:
                needs_manual = False           # safe hardcoded fix will be used
                self.tracker.step_log(
                    run_id, 4,
                    "AI unavailable — using safe built-in remediation for "
                    f"{anomaly_type} (no shutdown).")
            else:
                needs_manual = True

            self.tracker.step_complete(
                run_id, 4,
                f"Plan ready ({'AI-generated' if ai_status=='ok' else 'built-in' if use_builtin_fallback else 'MANUAL required'}) "
                f"— awaiting operator approval",
                data={"plan": plan, "ai_status": ai_status},
            )

            # Store for Phase 2; do NOT advance to step 5
            self.pending_approvals[run_id] = {
                "run": run,
                "anomaly": anomaly,
                "plan": plan,
                "rca": rca,
                "incident_id": incident_id,
                "ai_commands": ai_commands,      # safe AI commands, or None
                "ai_status": ai_status,          # ok | unsafe | unavailable
                "needs_manual": needs_manual,
                "use_builtin_fallback": use_builtin_fallback,
                "ai_block_reasons": ai_block_reasons,
            }
            run.status = "awaiting_approval"
            logger.info(f"[MONITOR] Phase 1 complete: {run_id} — awaiting approval")

        except Exception as e:
            logger.error(f"[MONITOR] Phase 1 failed for {run_id}: {e}", exc_info=True)
            current = run.current_step()
            if current:
                current.fail(str(e))
            run.fail(f"Phase 1 failed: {e}")

        return run

    # ── Phase 2: Fix Execution → Verification → Closure ─────────────────────

    def _run_phase2(self, run: WorkflowRun, anomaly: Dict[str, Any],
                    approval_data: Optional[Dict[str, Any]] = None) -> None:
        """
        Execute steps 5-7 on an existing WorkflowRun after operator approval.
        Removes signature from _active_signatures only if recovery is verified.
        Uses AI-generated, safety-filtered commands. If the AI was unavailable
        or proposed unsafe commands (needs_manual), the fix is NOT auto-run —
        the run is escalated for manual handling.
        """
        approval_data = approval_data or {}
        run_id = run.run_id
        device = anomaly.get("device", "unknown")
        anomaly_type = anomaly.get("type", "unknown")
        sig = f"{device}:{anomaly_type}"

        # Retrieve stored incident_id (may be on the run already)
        incident_id = run.incident_id

        logger.info(f"[MONITOR] Phase 2 start: {run_id} — {anomaly_type} on {device}")

        run.status = "running"
        fix_result = None
        recovered = False

        # ── Policy gate: if AI couldn't safely produce commands, escalate ────
        if approval_data.get("needs_manual"):
            self.tracker.step_start(run_id, 5)
            reasons = "; ".join(approval_data.get("ai_block_reasons", [])) or \
                      "AI did not produce safe commands"
            self.tracker.step_fail(
                run_id, 5,
                f"Manual intervention required — {reasons}. No commands were run.")
            self.orchestrator.state.update_incident(
                incident_id, status="investigating",
                note=f"AI remediation unavailable/unsafe ({reasons}). Escalated for manual handling."
            )
            run.complete("Escalated for manual handling — no automated fix applied")
            self.last_fix_result = {
                "success": False, "simulated": False, "commands": [],
                "error": f"Manual required: {reasons}", "device": device,
                "manual": True,
            }
            logger.info(f"[MONITOR] {run_id} escalated for manual handling")
            return

        try:
            # ── STEP 5: Fix Execution ─────────────────────────────────────────
            self.tracker.step_start(run_id, 5)
            _src = "AI" if approval_data.get("ai_status") == "ok" else "built-in"
            self.tracker.step_log(run_id, 5, f"Executing {_src} fix for {anomaly_type} on {device}")

            def step5_log(msg: str) -> None:
                self.tracker.step_log(run_id, 5, msg)

            device_cfg = self._get_device_config(device)
            ai_commands = approval_data.get("ai_commands")  # safe AI commands
            from core.execution_pipeline import get_execution_pipeline
            _pipe = get_execution_pipeline(self.fixer, self.tracker)
            _er = _pipe.deploy(
                device=device,
                anomaly=anomaly,
                device_config=device_cfg,
                exec_commands=(ai_commands or {}).get("diagnostic", []),
                fix_commands=(ai_commands or {}).get("fix", []),
                verify_commands=(ai_commands or {}).get("verify", []),
                step_logger=step5_log,
                config_mode=False,
            )
            fix_result = _er.fix_result

            # Expose the outcome so the UI can show live-vs-sim and commands run.
            self.last_fix_result = {
                "success": bool(getattr(fix_result, "success", False)),
                "simulated": bool(getattr(fix_result, "simulated", True)),
                "commands": list(getattr(fix_result, "commands_executed", []) or []),
                "error": getattr(fix_result, "error", None),
                "device": device,
            }

            if fix_result.success:
                mode = "[SIM]" if fix_result.simulated else "[LIVE]"
                # Start the anti-flap cooldown the moment a fix is applied — BEFORE
                # verification — so a rapid down→up→down flap can't re-trigger us.
                self._remediation_cooldown[sig] = self.cycle_count
                self.tracker.step_complete(
                    run_id, 5,
                    f"{mode} Executed {len(fix_result.commands_executed)} commands successfully",
                    data={
                        "commands": fix_result.commands_executed,
                        "simulated": fix_result.simulated,
                    },
                )
            else:
                self.tracker.step_fail(run_id, 5, fix_result.error or "Fix execution failed")

            # ── STEP 6: Recovery Verification ─────────────────────────────────
            self.tracker.step_start(run_id, 6)
            self.tracker.step_log(run_id, 6, "Re-polling telemetry to verify recovery...")
            time.sleep(0.1)  # brief pause for simulation realism
            recovered = self._verify_recovery(device, anomaly_type)
            if recovered:
                self.tracker.step_complete(run_id, 6, "Metrics returned to normal thresholds")
            else:
                self.tracker.step_complete(
                    run_id, 6,
                    "Recovery not yet confirmed — monitoring continues",
                )

            # ── STEP 7: Incident Closure ───────────────────────────────────────
            self.tracker.step_start(run_id, 7)
            if fix_result and fix_result.success and recovered:
                self.orchestrator.state.update_incident(
                    incident_id, status="resolved",
                    note="Autonomous remediation completed. Recovery verified by telemetry."
                )
                self.tracker.step_complete(
                    run_id, 7,
                    f"Incident {incident_id} resolved autonomously",
                )
                run.complete(
                    f"Autonomous remediation successful for {device} ({anomaly_type})"
                )
                # Verified clear — remove signature so fresh incidents can open if needed
                self._active_signatures.pop(sig, None)
                # Start a cooldown: the interface we just brought UP will emit
                # "up" then possibly flap; we must NOT re-act on it for a while.
                self._remediation_cooldown[sig] = self.cycle_count
                logger.info(f"[MONITOR] Signature {sig} cleared + cooldown started after verified recovery")
            else:
                self.orchestrator.state.update_incident(
                    incident_id, status="investigating",
                    note="Autonomous fix attempted. Manual review may be required."
                )
                self.tracker.step_complete(
                    run_id, 7,
                    f"Incident {incident_id} remains open — escalated for review",
                )
                run.complete("Partial remediation — escalated for manual review")
                # Do NOT remove signature — retry on next cycle

            logger.info(f"[MONITOR] Phase 2 complete: {run_id} status={run.status}")

        except Exception as e:
            logger.error(f"[MONITOR] Phase 2 failed for {run_id}: {e}", exc_info=True)
            current = run.current_step()
            if current:
                current.fail(str(e))
            run.fail(f"Phase 2 failed: {e}")

    # ── GNS3 log polling ────────────────────────────────────────────────────

    def _register_live_devices(self) -> None:
        """
        Register real routers seen in the GitHub logs into state, so the
        dashboard reflects the live GNS3 topology (R1, R2, ...) rather than
        simulated sites. Health is derived from syslog interface state.
        """
        if not self.github_log:
            return
        try:
            from core.state_manager import DeviceMetrics
        except Exception:
            return
        try:
            health = self.github_log.get_device_health()
        except Exception:
            health = {}
        for hostname, info in health.items():
            self.orchestrator.state.update_device_metrics(
                hostname,
                DeviceMetrics(
                    hostname=hostname,
                    reachable=bool(info.get("reachable", True)),
                    interface_errors=int(info.get("interface_errors", 0)),
                ),
            )

    def _purge_demo_state(self) -> None:
        """One-time cleanup of any leftover simulated devices/incidents/approvals."""
        try:
            self.orchestrator.state.device_metrics.clear()
            self.orchestrator.state.incidents.clear()
        except Exception:
            pass
        self.pending_approvals.clear()
        self.approved_run_ids.clear()
        self.rejected_run_ids.clear()
        self._active_signatures.clear()
        logger.info("[MONITOR] Live-only mode: purged simulated demo state")

    def _poll_github_logs(self) -> List[Dict[str, Any]]:
        """
        Poll the GitHub log repository for currently-open interface anomalies.
        Returns a list of anomaly dicts; silently returns [] if unavailable.
        """
        if not self.github_log:
            return []
        try:
            # github_log.poll() returns None (updates internal state in-place)
            # We must call poll() first to refresh, then read open anomalies
            self.github_log.poll()
            # Build anomaly dicts from the actionable recent_events
            anomalies = []
            for ev in getattr(self.github_log, "recent_events", []) or []:
                if ev.get("actionable") and ev.get("interface"):
                    anomalies.append({
                        "device":    ev.get("device", self.github_log.default_device),
                        "type":      "interface_down",
                        "interface": ev.get("interface", ""),
                        "severity":  "high",
                        "source":    "github_log",
                    })
            if anomalies:
                logger.info(
                    f"[MONITOR] GitHub log source: {len(anomalies)} open anomaly(ies)"
                )
            return anomalies
        except Exception as e:
            logger.debug(f"[MONITOR] GitHub log poll unavailable: {e}")
            return []

    def _poll_gns3_logs(self) -> List[Dict[str, Any]]:
        """
        Poll GNS3 device logs for interface/BGP/OSPF anomalies via SSH.
        Returns a list of anomaly dicts; silently returns [] if unavailable.
        """
        if not NETMIKO_AVAILABLE:
            return []
        try:
            conn_cfg = self._get_gns3_ssh_config()
            if not conn_cfg:
                return []

            anomalies: List[Dict[str, Any]] = []
            device_name = conn_cfg.get("_device_name", conn_cfg.get("host", "gns3-router"))

            with ConnectHandler(**{k: v for k, v in conn_cfg.items() if not k.startswith("_")}) as conn:
                # Syslog check
                try:
                    log_output = conn.send_command(
                        r"show logging | include %DOWN\|%ERR\|%OSPF\|%BGP",
                        read_timeout=15,
                    )
                    for line in log_output.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        atype = "bgp_instability" if "BGP" in line or "OSPF" in line else "interface_down"
                        anomalies.append({
                            "device": device_name,
                            "type": atype,
                            "severity": "high",
                            "description": line[:200],
                            "source": "gns3_syslog",
                        })
                except Exception as e:
                    logger.debug(f"[MONITOR] GNS3 syslog poll error: {e}")

                # Interface brief check
                try:
                    brief_output = conn.send_command("show ip interface brief", read_timeout=15)
                    for line in brief_output.splitlines():
                        parts = line.split()
                        if len(parts) >= 6:
                            iface = parts[0]
                            status = parts[4].lower()
                            proto = parts[5].lower()
                            if status == "down" or proto == "down":
                                anomalies.append({
                                    "device": device_name,
                                    "type": "interface_down",
                                    "severity": "high",
                                    "description": f"Interface {iface} is {status}/{proto}",
                                    "interface": iface,
                                    "source": "gns3_interface_brief",
                                })
                except Exception as e:
                    logger.debug(f"[MONITOR] GNS3 interface brief error: {e}")

            return anomalies

        except Exception as e:
            logger.debug(f"[MONITOR] GNS3 log poll unavailable: {e}")
            return []

    def _get_gns3_ssh_config(self) -> Optional[Dict[str, Any]]:
        """
        Build SSH config for GNS3 router, checking env vars first, then gns3 engine.
        """
        host = os.environ.get("GNS3_ROUTER_HOST")
        port_str = os.environ.get("GNS3_ROUTER_PORT")
        username = os.environ.get("GNS3_ROUTER_USER")
        password = os.environ.get("GNS3_ROUTER_PASS")

        if host and port_str:
            try:
                port = int(port_str)
            except ValueError:
                port = 22
            device_type = (os.environ.get("GNS3_DEVICE_TYPE", "cisco_ios").strip()
                           or "cisco_ios")
            cfg: Dict[str, Any] = {
                "device_type": device_type,
                "host": host,
                "port": port,
                "password": password or "admin",
                "secret": password or "admin",
                "timeout": 90,
                "auth_timeout": 90,
                "fast_cli": False,
                "_device_name": f"gns3-{host}",
            }
            if device_type.endswith("_telnet"):
                tu = os.environ.get("GNS3_TELNET_USER", "").strip()
                if tu:
                    cfg["username"] = tu
            else:
                cfg["username"] = username or "admin"
            return cfg

        # Fallback: ask gns3 engine for the first available node's console config
        try:
            gns3 = getattr(self.orchestrator, "gns3", None)
            if gns3 and hasattr(gns3, "nodes") and gns3.nodes:
                first_node = next(iter(gns3.nodes))
                cfg = gns3.get_netmiko_config(first_node)
                if cfg:
                    cfg = dict(cfg)
                    cfg["_device_name"] = first_node
                    # Apply paramiko workarounds required for old Cisco IOS
                    cfg.setdefault("timeout", 90)
                    cfg.setdefault("auth_timeout", 90)
                    cfg["fast_cli"] = False
                    return cfg
        except Exception as e:
            logger.debug(f"[MONITOR] GNS3 engine config lookup failed: {e}")

        return None

    # ── helpers ──────────────────────────────────────────────────────────────

    def _ensure_incident(self, anomaly: Dict[str, Any]) -> str:
        """
        Return existing open incident_id for this device, or create a new one.
        Scans all incidents for an open one (status 'new' or 'investigating')
        whose affected_devices contains the device, to avoid duplicate incidents
        for the same persistent anomaly.
        """
        device = anomaly.get("device", "unknown")
        anomaly_type = anomaly.get("type", "unknown")

        # Scan for an existing open incident on this device
        try:
            all_incidents = self.orchestrator.state.get_all_incidents()
            for inc_id, inc in all_incidents.items():
                if inc.get("status") in ("new", "investigating"):
                    if device in inc.get("affected_devices", []):
                        logger.debug(
                            f"[MONITOR] Reusing incident {inc_id} for {device}/{anomaly_type}"
                        )
                        return inc_id
        except Exception as e:
            logger.warning(f"[MONITOR] Incident scan failed: {e}")

        # No open incident found — create a new one
        incident_id = (
            f"INC-{datetime.utcnow().strftime('%H%M%S%f')}"
            f"-{abs(hash(device)) % 9999:04d}"
        )
        affected = [device] if device != "unknown" else []
        impacted = (
            self.orchestrator.state.calculate_service_impact(affected)
            .get("impacted_services", [])
        )
        self.orchestrator.state.create_incident(
            incident_id=incident_id,
            title=f"{anomaly_type.replace('_', ' ').title()} on {device}",
            description=anomaly.get("description", f"{anomaly_type} detected on {device}"),
            severity=anomaly.get("severity", "high"),
            affected_devices=affected,
            affected_services=impacted,
        )
        return incident_id

    def _retrieve_knowledge(self, anomaly: Dict[str, Any]) -> str:
        """
        RAG: retrieve relevant runbook docs + past resolved incidents for this
        anomaly, to ground the AI's remediation in THIS network's practices.
        """
        lines: List[str] = []
        atype = anomaly.get("type", "")
        device = anomaly.get("device", "")
        query = f"{atype} {anomaly.get('interface','')} {anomaly.get('description','')}"

        # 1. Runbook documents via the RAG engine.
        try:
            rag = getattr(self.orchestrator, "rag", None)
            if rag:
                hits = rag.search(query, vendor="Cisco", top_k=3)
                for h in hits[:3]:
                    lines.append(f"- Runbook '{h.get('title')}': {h.get('snippet','')}")
        except Exception:
            pass

        # 2. Past RESOLVED incidents on the same device (what worked before).
        try:
            incidents = self.orchestrator.state.get_all_incidents()
            past = [
                inc for inc in incidents.values()
                if inc.get("status") == "resolved"
                and device in (inc.get("affected_devices") or [])
            ]
            for inc in past[-2:]:
                note = ""
                if inc.get("timeline"):
                    note = inc["timeline"][-1].get("note", "")
                lines.append(f"- Past incident '{inc.get('title','')}' resolved: {note}")
        except Exception:
            pass

        return "\n".join(lines)

    def _device_facts(self, device: str) -> str:
        """Short factual context about the device for the AI prompt."""
        facts = []
        try:
            m = self.orchestrator.state.get_device_metrics(device)
            if m:
                facts.append(f"reachable={getattr(m,'reachable',True)}")
                facts.append(f"interface_errors={getattr(m,'interface_errors',0)}")
        except Exception:
            pass
        try:
            if self.github_log:
                health = self.github_log.get_device_health().get(device, {})
                down = health.get("down_interfaces", [])
                if down:
                    facts.append(f"down_interfaces={','.join(down)}")
        except Exception:
            pass
        return ("Device facts: " + "; ".join(facts)) if facts else ""

    def _get_device_config(self, device: str) -> Optional[Dict[str, Any]]:
        """
        Build connection config for a device.
        Priority: env vars (GNS3_ROUTER_HOST/PORT) → netmiko device catalog → gns3 engine.
        Honors GNS3_DEVICE_TYPE so a GNS3 Telnet console (cisco_ios_telnet) is used
        instead of SSH. Includes paramiko workarounds for old Cisco IOS over SSH.
        """
        # 1. Env-var override (pinggy tunnel or direct connection)
        host = os.environ.get("GNS3_ROUTER_HOST")
        port_str = os.environ.get("GNS3_ROUTER_PORT")
        # Accept both naming conventions for credentials.
        username = os.environ.get("GNS3_ROUTER_USER") or os.environ.get("GNS3_SSH_USER")
        password = os.environ.get("GNS3_ROUTER_PASS") or os.environ.get("GNS3_SSH_PASS")
        device_type = (os.environ.get("GNS3_DEVICE_TYPE", "cisco_ios").strip()
                       or "cisco_ios")

        if host and port_str:
            try:
                port = int(port_str)
            except ValueError:
                port = 22
            cfg: Dict[str, Any] = {
                "device_type": device_type,
                "host": host,
                "port": port,
                "password": password or "admin",
                "secret": password or "admin",
                "timeout": 90,
                "auth_timeout": 90,
                "fast_cli": False,
            }
            # A GNS3 Telnet console usually has NO username prompt (login is on
            # the line, privilege 15). Passing a username makes netmiko wait for
            # a prompt that never comes → timeout. So for telnet we omit the
            # username unless a dedicated GNS3_TELNET_USER is explicitly set.
            if device_type.endswith("_telnet"):
                telnet_user = os.environ.get("GNS3_TELNET_USER", "").strip()
                if telnet_user:
                    cfg["username"] = telnet_user
            else:
                cfg["username"] = username or "admin"
            return cfg

        # 2. Netmiko device catalog
        try:
            from config.netmiko_devices import load_device_catalog
            catalog = load_device_catalog()
            for dev in catalog:
                hostname = (
                    dev.get("hostname")
                    or dev.get("name")
                    or dev.get("host")
                    or dev.get("ip_address")
                )
                if hostname == device:
                    cfg = dict(dev)
                    cfg.setdefault("timeout", 90)
                    cfg.setdefault("auth_timeout", 90)
                    cfg["fast_cli"] = False
                    return cfg
        except Exception:
            pass

        # 3. GNS3 engine console config
        try:
            gns3 = getattr(self.orchestrator, "gns3", None)
            if gns3:
                cfg = gns3.get_netmiko_config(device)
                if cfg:
                    cfg = dict(cfg)
                    cfg.setdefault("timeout", 90)
                    cfg.setdefault("auth_timeout", 90)
                    cfg["fast_cli"] = False
                    return cfg
        except Exception:
            pass

        return None

    def _run_rca(self, anomaly: Dict[str, Any], incident_id: str) -> str:
        """Run root cause analysis — AI-powered when available, heuristics otherwise."""
        device = anomaly.get("device", "unknown")
        anomaly_type = anomaly.get("type", "unknown")
        metrics = self.orchestrator.state.get_device_metrics(device)
        impacted = (
            self.orchestrator.state.calculate_service_impact([device])
            .get("impacted_services", [])
        )

        if self.ai_call:
            try:
                prompt = (
                    f"Network incident analysis:\n"
                    f"Incident: {incident_id}\n"
                    f"Device: {device}\n"
                    f"Issue: {anomaly_type}\n"
                    f"Severity: {anomaly.get('severity', 'high')}\n"
                    f"Description: {anomaly.get('description', 'N/A')}\n"
                    f"Metrics: CPU={getattr(metrics, 'cpu', 'N/A')}% "
                    f"Memory={getattr(metrics, 'memory', 'N/A')}% "
                    f"Latency={getattr(metrics, 'latency_ms', 'N/A')}ms "
                    f"Loss={getattr(metrics, 'packet_loss_pct', 'N/A')}%\n"
                    f"Impacted services: {', '.join(impacted) or 'none identified'}\n\n"
                    f"Provide: 1) Root cause (2 sentences) "
                    f"2) Impact assessment 3) Fix steps (numbered)"
                )
                response = self.ai_call(prompt)
                if response:
                    return response
            except Exception as e:
                logger.warning(f"AI RCA failed: {e}, using local RCA")

        return self._local_rca(anomaly_type, device)

    def _local_rca(self, anomaly_type: str, device: str) -> str:
        """Heuristic root cause analysis when AI is unavailable."""
        rca_map = {
            "interface_down": (
                f"Physical or logical interface failure on {device}. "
                f"Interface transitioned to down state, interrupting traffic forwarding "
                f"and potentially affecting downstream BGP/OSPF adjacencies."
            ),
            "bgp_instability": (
                f"BGP session instability on {device} caused by keepalive timeouts or "
                f"hold timer expiry. Routing table churn may cause traffic black-holing "
                f"until sessions re-establish."
            ),
            "packet_loss": (
                f"Excessive packet loss on {device} indicating interface errors, queue "
                f"drops, or upstream congestion. Service quality degraded for all traffic "
                f"traversing this device."
            ),
            "latency_spike": (
                f"WAN latency elevation on {device} caused by circuit congestion, routing "
                f"suboptimality, or upstream provider issue. Applications experiencing "
                f"high RTT and potential timeouts."
            ),
            "cpu_spike": (
                f"CPU overload on {device} — likely caused by routing protocol convergence, "
                f"high traffic inspection load, or a process consuming excessive cycles."
            ),
            "memory_exhaustion": (
                f"Memory pressure on {device} — routing table growth, BGP prefix explosion, "
                f"or memory leak in a process. Risk of process crash if not addressed."
            ),
            "device_unreachable": (
                f"Device {device} is not responding. Power failure, management plane crash, "
                f"or physical connectivity loss to the device."
            ),
            "voice_degradation": (
                f"Voice QoS degradation on {device} — jitter and latency exceeding MOS "
                f"thresholds. Routing instability causing voice packet drops."
            ),
        }
        return rca_map.get(
            anomaly_type,
            f"Operational anomaly {anomaly_type} detected on {device}. "
            f"Investigation required to determine root cause and service impact.",
        )

    def _build_plan(self, anomaly: Dict[str, Any], rca: str) -> List[str]:
        """Build a human-readable remediation plan for the UI."""
        anomaly_type = anomaly.get("type", "unknown")
        device = anomaly.get("device", "unknown")
        plans: Dict[str, List[str]] = {
            "interface_down": [
                f"Connect to {device} via SSH/telnet",
                "Identify downed interface",
                "Execute 'no shutdown'",
                "Verify line protocol up",
            ],
            "bgp_instability": [
                f"Connect to {device}",
                "Review BGP neighbor table",
                "Execute 'clear ip bgp * soft'",
                "Verify Established state",
            ],
            "packet_loss": [
                f"Connect to {device}",
                "Check interface error counters",
                "Clear counters",
                "Verify loss drops below threshold",
            ],
            "latency_spike": [
                f"Connect to {device}",
                "Check routing table for suboptimal paths",
                "Clear IP route cache",
                "Verify latency returns to baseline",
            ],
            "cpu_spike": [
                f"Connect to {device}",
                "Identify top CPU process",
                "Apply QoS policy if traffic-driven",
                "Monitor CPU for recovery",
            ],
            "memory_exhaustion": [
                f"Connect to {device}",
                "Identify memory-consuming process",
                "Clear IP cache and ARP",
                "Monitor memory usage",
            ],
            "device_unreachable": [
                f"Ping {device} from management station",
                "Check OOB console access",
                "Verify interface status",
                "Attempt no shutdown on mgmt interface",
            ],
        }
        return plans.get(
            anomaly_type,
            [
                f"Investigate {anomaly_type} on {device}",
                "Apply standard remediation",
                "Verify recovery",
            ],
        )

    def _verify_recovery(self, device: str, anomaly_type: str) -> bool:
        """Re-check the live log source to see if the anomaly is actually gone."""
        try:
            # In live-only mode, recovery must be confirmed from the GitHub log
            # (the real router state), not the simulated telemetry engine.
            if self.github_log is not None:
                live = self.github_log.poll()
                still_present = any(
                    a.get("device") == device and a.get("type") == anomaly_type
                    for a in live
                )
                return not still_present
            new_anomalies = self.orchestrator.telemetry.detect_anomalies()
            still_present = any(
                a.get("device") == device and a.get("type") == anomaly_type
                for a in new_anomalies
            )
            return not still_present
        except Exception:
            return False

    def _get_threshold_info(self, anomaly: Dict[str, Any]) -> str:
        """Return a human-readable threshold vs. measured value string."""
        atype = anomaly.get("type", "")
        val = (
            anomaly.get("value")
            or anomaly.get("latency_ms")
            or anomaly.get("loss_pct")
        )
        threshold_map = {
            "cpu_spike":          "Threshold: CPU >= 90%",
            "memory_exhaustion":  "Threshold: Memory >= 90%",
            "latency_spike":      "Threshold: Latency > 100ms",
            "packet_loss":        "Threshold: Loss > 5%",
            "bgp_instability":    "Threshold: Any BGP session down",
            "interface_down":     "Threshold: Interface not 'up'",
            "device_unreachable": "Threshold: Device not responding",
        }
        threshold = threshold_map.get(atype, "Threshold: anomaly criteria met")
        if val is not None:
            return f"Measured: {val} | {threshold}"
        return threshold
