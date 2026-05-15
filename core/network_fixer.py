"""
Network Fixer — executes CLI remediation commands on network devices.
Knows the right Netmiko commands for each anomaly type.
Falls back to simulated execution when no live connection is available.
"""
from __future__ import annotations
import logging
import os
import time
import random
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Paramiko legacy cipher patch (required for old Cisco IOS) ─────────────────
try:
    import paramiko
    paramiko.Transport._preferred_kex = (
        "diffie-hellman-group14-sha1",
        "diffie-hellman-group-exchange-sha1",
        "diffie-hellman-group1-sha1",
    )
    paramiko.Transport._preferred_ciphers = (
        "aes128-cbc",
        "aes192-cbc",
        "aes256-cbc",
    )
except Exception:
    pass

try:
    from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
    NETMIKO_AVAILABLE = True
except ImportError:
    NETMIKO_AVAILABLE = False

# ── Fix command library ──────────────────────────────────────────────────────

FIX_COMMANDS: Dict[str, Dict[str, List[str]]] = {
    "interface_down": {
        "diagnostic": [
            "show interfaces status",
            "show interfaces {interface} | include line|errors|rate",
            "show logging | include {interface} | tail 20",
        ],
        "fix": [
            "interface {interface}",
            "no shutdown",
            "end",
        ],
        "verify": [
            "show interfaces {interface} | include line protocol",
        ],
    },
    "bgp_instability": {
        "diagnostic": [
            "show ip bgp summary",
            "show ip bgp neighbors | include BGP|state|reset",
            "show logging | include BGP | tail 20",
        ],
        "fix": [
            "clear ip bgp * soft",
        ],
        "verify": [
            "show ip bgp summary | include Established",
        ],
    },
    "packet_loss": {
        "diagnostic": [
            "show interfaces | include rate|errors|drops",
            "show interfaces counters errors",
            "show queue {interface}",
        ],
        "fix": [
            "clear counters",
            "interface {interface}",
            "no shutdown",
            "end",
        ],
        "verify": [
            "show interfaces | include Input errors|Output drops",
        ],
    },
    "latency_spike": {
        "diagnostic": [
            "show interfaces | include rate|latency",
            "show ip route | include via",
            "show processes cpu sorted | head 10",
        ],
        "fix": [
            "clear ip route *",
        ],
        "verify": [
            "show ip route summary",
        ],
    },
    "cpu_spike": {
        "diagnostic": [
            "show processes cpu sorted | head 20",
            "show processes cpu history",
            "show ip traffic",
        ],
        "fix": [
            "no ip inspect name GLOBAL",
            "end",
        ],
        "verify": [
            "show processes cpu | include CPU utilization",
        ],
    },
    "memory_exhaustion": {
        "diagnostic": [
            "show processes memory sorted | head 20",
            "show memory statistics",
        ],
        "fix": [
            "clear ip cache",
            "clear ip bgp * soft",
        ],
        "verify": [
            "show memory statistics | include Processor",
        ],
    },
    "device_unreachable": {
        "diagnostic": [
            "show ip interface brief",
            "show ip route",
            "show cdp neighbors",
        ],
        "fix": [
            "interface {interface}",
            "no shutdown",
            "end",
            "clear ip arp",
        ],
        "verify": [
            "show ip interface brief | include up",
        ],
    },
}


@dataclass
class FixResult:
    success: bool
    device: str
    anomaly_type: str
    commands_executed: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    verification_passed: bool = False
    simulated: bool = False
    error: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None

    def finish(self) -> None:
        self.completed_at = datetime.utcnow().isoformat()


class NetworkFixer:
    """
    Executes CLI fix commands on network devices via Netmiko.
    Works with both live devices (SSH/telnet) and GNS3 console ports.
    Falls back to simulated execution for demonstration when no device is reachable.
    """

    def __init__(self, gns3_engine=None):
        self.gns3 = gns3_engine
        self.execution_log: List[Dict[str, Any]] = []
        # Default SSH credentials — override via GNS3_SSH_USER / GNS3_SSH_PASS env vars
        self.default_username = os.environ.get("GNS3_SSH_USER", "admin")
        self.default_password = os.environ.get("GNS3_SSH_PASS", "admin")

    # ── main entry point ────────────────────────────────────────────────────

    def fix(
        self,
        anomaly: Dict[str, Any],
        device_config: Optional[Dict[str, Any]] = None,
        step_logger=None,
    ) -> FixResult:
        """
        Execute remediation for an anomaly.
        step_logger: callable(str) → logs to the workflow step.
        """
        device = anomaly.get("device", "unknown")
        anomaly_type = anomaly.get("type", "unknown")

        result = FixResult(device=device, anomaly_type=anomaly_type, success=False)

        _log = step_logger or (lambda msg: None)
        _log(f"Starting remediation for {anomaly_type} on {device}")

        # 1. Resolve device connection config
        conn_config = device_config
        if not conn_config:
            conn_config = self._build_tunnel_config()
        if not conn_config and self.gns3:
            conn_config = self.gns3.get_netmiko_config(device)

        # 2. Get fix commands for this anomaly type
        commands = self._resolve_commands(anomaly_type, anomaly)

        # 3. Execute (live or simulated)
        if conn_config and NETMIKO_AVAILABLE:
            result = self._execute_live(conn_config, commands, anomaly, result, _log)
        else:
            result = self._execute_simulated(commands, anomaly, result, _log)

        result.finish()
        self._record(result)
        return result

    # ── live execution ──────────────────────────────────────────────────────

    def _execute_live(
        self,
        conn_config: Dict[str, Any],
        commands: Dict[str, List[str]],
        anomaly: Dict[str, Any],
        result: FixResult,
        log,
    ) -> FixResult:
        try:
            log(f"Connecting to {conn_config['host']}:{conn_config.get('port', 22)} via {conn_config['device_type']}")
            with ConnectHandler(**conn_config) as conn:
                log("SSH/Telnet session established")

                # Run diagnostics
                for cmd in commands.get("diagnostic", []):
                    cmd = self._interpolate(cmd, anomaly)
                    log(f"Diagnostic: {cmd}")
                    try:
                        output = conn.send_command(cmd, read_timeout=15)
                        result.commands_executed.append(cmd)
                        result.outputs.append(output)
                        log(f"   → {output[:120].strip()}")
                    except Exception as e:
                        log(f"   Command failed: {e}")

                # Execute fix
                fix_cmds = commands.get("fix", [])
                if fix_cmds:
                    log(f"Executing {len(fix_cmds)} fix command(s)")
                    if any(c in ["end", "exit", "wr", "write memory"] for c in fix_cmds):
                        try:
                            cfg_cmds = [c for c in fix_cmds if c not in ("end", "exit")]
                            output = conn.send_config_set(cfg_cmds)
                            for cmd in fix_cmds:
                                result.commands_executed.append(self._interpolate(cmd, anomaly))
                                log(f"   OK: {cmd}")
                            result.outputs.append(output)
                        except Exception as e:
                            log(f"   Config mode failed: {e}")
                            result.error = str(e)
                    else:
                        for cmd in fix_cmds:
                            cmd = self._interpolate(cmd, anomaly)
                            try:
                                output = conn.send_command_timing(cmd)
                                result.commands_executed.append(cmd)
                                result.outputs.append(output)
                                log(f"   OK: {cmd}")
                            except Exception as e:
                                log(f"   {cmd} failed: {e}")

                # Verify
                log("Running verification checks...")
                verify_passed = True
                for cmd in commands.get("verify", []):
                    cmd = self._interpolate(cmd, anomaly)
                    try:
                        output = conn.send_command(cmd, read_timeout=10)
                        result.commands_executed.append(cmd)
                        result.outputs.append(output)
                        log(f"   Verify: {cmd} → {output[:100].strip()}")
                    except Exception as e:
                        log(f"   Verify failed: {e}")
                        verify_passed = False

                result.verification_passed = verify_passed
                result.success = True
                log("Remediation complete — device responded successfully")

        except NetmikoAuthenticationException:
            result.error = "Authentication failed — check credentials"
            log(f"Auth failed for {conn_config['host']}")
        except NetmikoTimeoutException:
            result.error = "Connection timed out"
            log(f"Timeout connecting to {conn_config['host']}")
        except Exception as e:
            result.error = str(e)
            log(f"Fix failed: {e}")

        return result

    # ── simulated execution ─────────────────────────────────────────────────

    def _execute_simulated(
        self,
        commands: Dict[str, List[str]],
        anomaly: Dict[str, Any],
        result: FixResult,
        log,
    ) -> FixResult:
        """Simulate command execution for demonstration when no live device is available."""
        result.simulated = True
        device = anomaly.get("device", "unknown")
        anomaly_type = anomaly.get("type", "unknown")

        log(f"[SIM] No live connection — running simulated remediation on {device}")
        time.sleep(0.2)

        sim_outputs = self._get_simulated_outputs(anomaly_type, device)

        phase_labels = {
            "diagnostic": "Diagnosing",
            "fix": "Fixing",
            "verify": "Verifying",
        }

        for phase, cmds in [("diagnostic", commands.get("diagnostic", [])),
                             ("fix",        commands.get("fix",        [])),
                             ("verify",     commands.get("verify",     []))]:
            if not cmds:
                continue
            phase_label = phase_labels[phase]
            for cmd in cmds:
                cmd_rendered = self._interpolate(cmd, anomaly)
                time.sleep(random.uniform(0.05, 0.2))
                output = sim_outputs.get(phase, {}).get(
                    cmd_rendered,
                    f"% Simulated output for: {cmd_rendered}",
                )
                result.commands_executed.append(cmd_rendered)
                result.outputs.append(output)
                log(f"   {phase_label}: {cmd_rendered}")
                log(f"      → {output[:100]}")

        result.verification_passed = True
        result.success = True
        log(f"[SIM] Simulated remediation complete for {device} ({anomaly_type})")
        return result

    # ── helpers ─────────────────────────────────────────────────────────────

    def _resolve_commands(self, anomaly_type: str, anomaly: Dict[str, Any]) -> Dict[str, List[str]]:
        return FIX_COMMANDS.get(anomaly_type, {
            "diagnostic": ["show version", "show ip interface brief"],
            "fix":        [],
            "verify":     ["show ip interface brief"],
        })

    def _build_tunnel_config(self) -> Optional[Dict[str, Any]]:
        """Build SSH config from GNS3_ROUTER_HOST/PORT env vars (pingpy tunnel)."""
        host = os.environ.get("GNS3_ROUTER_HOST", "")
        port_str = os.environ.get("GNS3_ROUTER_PORT", "")
        if not host or not port_str:
            return None
        try:
            port = int(port_str)
        except ValueError:
            return None
        return {
            "device_type": "cisco_ios",
            "host": host,
            "port": port,
            "username": self.default_username,
            "password": self.default_password,
            "timeout": 90,
            "auth_timeout": 90,
            "fast_cli": False,
        }

    def _interpolate(self, cmd: str, anomaly: Dict[str, Any]) -> str:
        interface = (
            anomaly.get("interface")
            or (anomaly.get("description", "").split()[-1] if anomaly.get("description") else None)
            or "GigabitEthernet0/0"
        )
        peer = anomaly.get("peer") or anomaly.get("peer_ip") or "*"
        return cmd.format(interface=interface, peer=peer)

    def _get_simulated_outputs(self, anomaly_type: str, device: str) -> Dict[str, Dict[str, str]]:
        return {
            "diagnostic": {
                "show interfaces status": (
                    "Gi0/0  connected  1  a-full  a-1000  RJ45\n"
                    "Gi0/1  notconnect 1  auto   auto   RJ45"
                ),
                "show ip bgp summary": (
                    "Neighbor        V AS MsgRcvd MsgSent TblVer  InQ OutQ Up/Down  State/PfxRcd\n"
                    "10.0.0.1        4 65000 1234  1234    1      0    0    00:20:32 Established 100"
                ),
                "show processes cpu sorted | head 10": (
                    "CPU utilization for five seconds: 45%/2%; one minute: 43%"
                ),
            },
            "fix": {
                "no shutdown": "",
                "clear ip bgp * soft": "",
                "clear counters": "Clear \"show interface\" counters on all interfaces [confirm]",
                "clear ip route *": "",
            },
            "verify": {
                "show interfaces GigabitEthernet0/0 | include line protocol": (
                    "GigabitEthernet0/0 is up, line protocol is up"
                ),
                "show ip bgp summary | include Established": (
                    "10.0.0.1    4  65000  1234  1234  1  0  0  00:21:15  Established  100"
                ),
                "show processes cpu | include CPU utilization": (
                    "CPU utilization for five seconds: 12%/1%; one minute: 18%"
                ),
                "show ip interface brief | include up": (
                    "GigabitEthernet0/0  10.0.0.1  YES NVRAM  up  up"
                ),
            },
        }

    def _record(self, result: FixResult) -> None:
        self.execution_log.insert(0, {
            "device": result.device,
            "anomaly": result.anomaly_type,
            "success": result.success,
            "simulated": result.simulated,
            "commands": len(result.commands_executed),
            "timestamp": result.started_at,
        })
        if len(self.execution_log) > 200:
            self.execution_log = self.execution_log[:200]

    def get_execution_log(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.execution_log[:limit]
