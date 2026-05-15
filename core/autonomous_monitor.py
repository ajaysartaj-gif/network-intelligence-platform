"""
Autonomous Monitor — orchestrates the full detect → analyze → fix → verify cycle.
Designed to be called from Streamlit's polling loop (no background threads).
Records every action in WorkflowTracker for real-time UI visualization.
"""
from __future__ import annotations
import logging
import time
from datetime import datetime
from typing import Dict, List, Any, Optional

from core.workflow_tracker import WorkflowTracker, WorkflowRun, StepStatus

logger = logging.getLogger(__name__)


class AutonomousMonitor:
    """
    Runs one complete autonomous remediation cycle per call.
    Integrates telemetry → anomaly detection → AI RCA → fix execution → verification.
    All steps are tracked in WorkflowTracker for real-time Streamlit display.
    """

    def __init__(
        self,
        orchestrator,          # OperationsOrchestrator
        workflow_tracker: WorkflowTracker,
        network_fixer,         # NetworkFixer
        ai_call_fn=None,       # callable(str) → str
    ):
        self.orchestrator = orchestrator
        self.tracker = workflow_tracker
        self.fixer = network_fixer
        self.ai_call = ai_call_fn
        self.cycle_count = 0
        self.last_cycle_result: Dict[str, Any] = {}
        # Track which anomaly signatures have active workflows to avoid duplicates
        self._active_signatures: set = set()

    # ── public API ──────────────────────────────────────────────────────────

    def run_cycle(self) -> Dict[str, Any]:
        """
        Execute one monitoring cycle. Call this from Streamlit's polling loop.
        Returns a summary dict for the UI.
        """
        self.cycle_count += 1
        cycle_start = datetime.utcnow()

        try:
            # 1. Simulation step + telemetry collection
            self.orchestrator.simulator.step()
            telemetry = self.orchestrator.telemetry.collect_all_telemetry()
            anomalies = self.orchestrator.telemetry.detect_anomalies()

            # 2. For each critical/high anomaly, start autonomous workflow
            workflows_started = []
            for anomaly in anomalies:
                if anomaly.get("severity") not in ("critical", "high"):
                    continue
                sig = f"{anomaly.get('device')}:{anomaly.get('type')}"
                if sig in self._active_signatures:
                    continue  # workflow already running for this
                self._active_signatures.add(sig)
                run = self._run_autonomous_workflow(anomaly)
                if run:
                    workflows_started.append(run.run_id)
                    # Remove signature after workflow completes so new ones can start
                    if run.status != "running":
                        self._active_signatures.discard(sig)

            # 3. Build result summary
            duration_ms = (datetime.utcnow() - cycle_start).total_seconds() * 1000
            result = {
                "cycle": self.cycle_count,
                "timestamp": datetime.utcnow().isoformat(),
                "duration_ms": round(duration_ms, 1),
                "devices_polled": len(telemetry.get("device_metrics", {})),
                "anomalies_found": len(anomalies),
                "workflows_started": len(workflows_started),
                "active_workflows": len(self.tracker.get_active_runs()),
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

    # ── autonomous workflow pipeline ─────────────────────────────────────────

    def _run_autonomous_workflow(self, anomaly: Dict[str, Any]) -> Optional[WorkflowRun]:
        """
        Execute the full 7-step remediation pipeline for a single anomaly.
        """
        device = anomaly.get("device", "unknown")
        anomaly_type = anomaly.get("type", "unknown")
        severity = anomaly.get("severity", "high")

        # Create incident + workflow run
        incident_id = self._ensure_incident(anomaly)
        run = self.tracker.create_run(incident_id, device, anomaly_type, severity)
        run_id = run.run_id
        logger.info(f"[MONITOR] Starting workflow {run_id} for {anomaly_type} on {device}")

        try:
            # ── STEP 1: Telemetry Collection ─────────────────────────────
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

            # ── STEP 2: Anomaly Detection ─────────────────────────────────
            self.tracker.step_start(run_id, 2)
            desc = anomaly.get("description", f"{anomaly_type} detected on {device}")
            self.tracker.step_log(run_id, 2, f"Anomaly confirmed: {desc}")
            threshold_info = self._get_threshold_info(anomaly)
            self.tracker.step_log(run_id, 2, threshold_info)
            self.tracker.step_complete(
                run_id, 2,
                f"Anomaly: {anomaly_type} | Severity: {severity.upper()}",
            )

            # ── STEP 3: AI Root Cause Analysis ────────────────────────────
            self.tracker.step_start(run_id, 3)
            self.tracker.step_log(run_id, 3, "Querying AI for root cause analysis...")
            rca = self._run_rca(anomaly, incident_id)
            self.tracker.step_log(run_id, 3, f"AI RCA: {rca[:200]}")
            self.tracker.step_complete(run_id, 3, rca[:300], data={"rca": rca})
            self.orchestrator.state.update_incident(
                incident_id, status="investigating",
                note=f"AI RCA: {rca[:200]}"
            )

            # ── STEP 4: Remediation Planning ──────────────────────────────
            self.tracker.step_start(run_id, 4)
            plan = self._build_plan(anomaly, rca)
            for p in plan:
                self.tracker.step_log(run_id, 4, f"  • {p}")
            self.tracker.step_complete(
                run_id, 4,
                f"Plan ready: {len(plan)} actions",
                data={"plan": plan},
            )

            # ── STEP 5: Fix Execution ─────────────────────────────────────
            self.tracker.step_start(run_id, 5)
            self.tracker.step_log(run_id, 5, f"Executing fix for {anomaly_type} on {device}")

            def step5_log(msg: str) -> None:
                self.tracker.step_log(run_id, 5, msg)

            device_cfg = self._get_device_config(device)
            fix_result = self.fixer.fix(anomaly, device_config=device_cfg, step_logger=step5_log)

            if fix_result.success:
                mode = "[SIM]" if fix_result.simulated else "[LIVE]"
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

            # ── STEP 6: Recovery Verification ────────────────────────────
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

            # ── STEP 7: Incident Closure ──────────────────────────────────
            self.tracker.step_start(run_id, 7)
            if fix_result.success and recovered:
                self.orchestrator.state.update_incident(
                    incident_id, status="resolved",
                    note="Autonomous remediation completed. Recovery verified by telemetry."
                )
                self.tracker.step_complete(
                    run_id, 7,
                    f"Incident {incident_id} resolved autonomously",
                )
                run.complete(f"Autonomous remediation successful for {device} ({anomaly_type})")
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

            logger.info(f"[MONITOR] Workflow {run_id} completed: {run.status}")

        except Exception as e:
            logger.error(f"[MONITOR] Workflow {run_id} failed at step: {e}", exc_info=True)
            current = run.current_step()
            if current:
                current.fail(str(e))
            run.fail(f"Workflow failed: {e}")

        return run

    # ── helpers ──────────────────────────────────────────────────────────────

    def _ensure_incident(self, anomaly: Dict[str, Any]) -> str:
        """Create an incident record in the state manager and return its ID."""
        device = anomaly.get("device", "unknown")
        anomaly_type = anomaly.get("type", "unknown")
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

    def _run_rca(self, anomaly: Dict[str, Any], incident_id: str) -> str:
        """Run root cause analysis — AI-powered when available, local heuristics otherwise."""
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
        """Re-run anomaly detection and check if the specific anomaly is gone."""
        try:
            new_anomalies = self.orchestrator.telemetry.detect_anomalies()
            still_present = any(
                a.get("device") == device and a.get("type") == anomaly_type
                for a in new_anomalies
            )
            return not still_present
        except Exception:
            return False

    def _get_device_config(self, device: str) -> Optional[Dict[str, Any]]:
        """Try to get live device connection config from catalog."""
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
                    return dev
        except Exception:
            pass
        return None

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
