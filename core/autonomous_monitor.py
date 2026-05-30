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
                    self._run_phase2(data["run"], data["anomaly"])

            # ── 3. Sim step + telemetry + anomaly detection ──────────────────
            self.orchestrator.simulator.step()
            telemetry = self.orchestrator.telemetry.collect_all_telemetry()
            anomalies = self.orchestrator.telemetry.detect_anomalies()

            # ── 4. External log polling (merges unique anomalies) ────────────
            existing_sigs = {
                f"{a.get('device')}:{a.get('type')}" for a in anomalies
            }

            # 4a. GitHub log source (router → local → GitHub → here).
            #     Primary source for cloud deployments.
            for ga in self._poll_github_logs():
                gsig = f"{ga.get('device')}:{ga.get('type')}"
                if gsig not in existing_sigs:
                    anomalies.append(ga)
                    existing_sigs.add(gsig)

            # 4b. Direct GNS3 SSH syslog (used when the lab is reachable).
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
                run = self._run_phase1(anomaly)
                if run:
                    self._active_signatures[sig] = run.run_id
                    workflows_started.append(run.run_id)

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

            # ── STEP 4: Remediation Planning ──────────────────────────────────
            self.tracker.step_start(run_id, 4)
            plan = self._build_plan(anomaly, rca)
            for p in plan:
                self.tracker.step_log(run_id, 4, f"  • {p}")
            self.tracker.step_complete(
                run_id, 4,
                f"Plan ready: {len(plan)} actions — awaiting operator approval",
                data={"plan": plan},
            )

            # Store for Phase 2; do NOT advance to step 5
            self.pending_approvals[run_id] = {
                "run": run,
                "anomaly": anomaly,
                "plan": plan,
                "rca": rca,
                "incident_id": incident_id,
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

    def _run_phase2(self, run: WorkflowRun, anomaly: Dict[str, Any]) -> None:
        """
        Execute steps 5-7 on an existing WorkflowRun after operator approval.
        Removes signature from _active_signatures only if recovery is verified.
        """
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

        try:
            # ── STEP 5: Fix Execution ─────────────────────────────────────────
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
                logger.info(f"[MONITOR] Signature {sig} cleared after verified recovery")
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

    def _poll_github_logs(self) -> List[Dict[str, Any]]:
        """
        Poll the GitHub log repository for currently-open interface anomalies.
        Returns a list of anomaly dicts; silently returns [] if unavailable.
        """
        if not self.github_log:
            return []
        try:
            anomalies = self.github_log.poll()
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
            return {
                "device_type": "cisco_ios",
                "host": host,
                "port": port,
                "username": username or "admin",
                "password": password or "admin",
                "timeout": 90,
                "auth_timeout": 90,
                "fast_cli": False,
                "_device_name": f"gns3-{host}",
            }

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

    def _get_device_config(self, device: str) -> Optional[Dict[str, Any]]:
        """
        Build SSH connection config for a device.
        Priority: env vars (GNS3_ROUTER_HOST/PORT) → netmiko device catalog → gns3 engine.
        Includes paramiko workarounds required for old Cisco IOS.
        """
        # 1. Env-var override (pingpy tunnel or direct SSH)
        host = os.environ.get("GNS3_ROUTER_HOST")
        port_str = os.environ.get("GNS3_ROUTER_PORT")
        username = os.environ.get("GNS3_ROUTER_USER")
        password = os.environ.get("GNS3_ROUTER_PASS")

        if host and port_str:
            try:
                port = int(port_str)
            except ValueError:
                port = 22
            return {
                "device_type": "cisco_ios",
                "host": host,
                "port": port,
                "username": username or "admin",
                "password": password or "admin",
                "timeout": 90,
                "auth_timeout": 90,
                "fast_cli": False,
            }

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
