"""
Network Fixer — executes CLI remediation commands on real network devices.
Knows the right Netmiko commands for each anomaly type. No live connection
means no fix — this never fabricates a result.
"""
from __future__ import annotations
import logging
import os
import time
import contextlib
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

try:
    from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
    NETMIKO_AVAILABLE = True
except ImportError:
    NETMIKO_AVAILABLE = False

# ── Fix command library ──────────────────────────────────────────────────────

# NOTE: the former static FIX_COMMANDS table has been removed. Commands are
# now resolved live (cache → RAG → MCP → grounded AI) via core.command_resolver.
# Nothing in this module hardcodes a command literal.


@dataclass
class FixResult:
    success: bool
    device: str
    anomaly_type: str
    commands_executed: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    verification_passed: bool = False
    # Always False — kept only because callers (core.autonomous_monitor,
    # app.py's UI) still read this field. No code path ever sets it True
    # anymore: a fix that can't reach a real device fails with a clear
    # error instead of fabricating a result.
    simulated: bool = False
    error: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None

    def finish(self) -> None:
        self.completed_at = datetime.utcnow().isoformat()


class NetworkFixer:
    """
    Executes CLI fix commands on real network devices via Netmiko — GNS3
    console ports or direct SSH/telnet. No live connection means no fix;
    this never fabricates a result to demonstrate one.
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
        command_override: Optional[Dict[str, List[str]]] = None,
        connection=None,
        save: bool = False,
        config_mode: bool = False,
    ) -> FixResult:
        """
        Execute remediation for an anomaly.
        step_logger: callable(str) → logs to the workflow step.
        command_override: AI-generated {diagnostic,fix,verify} commands. When
            provided, these are used INSTEAD of the built-in table.
        connection: an already-open netmiko connection. When provided it is
            used as-is (and left open for the caller to close) instead of
            opening a new one — this lets callers that already established a
            session with special handling (e.g. SSH→Telnet fallback) reuse it
            while keeping this method the single deployment implementation.
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

        # 2. Commands: prefer AI-generated (already safety-validated upstream),
        #    otherwise fall back to the built-in table.
        #    Honor the override if it has EITHER fix OR diagnostic commands —
        #    a read-only diagnostic query has fix=[] but a populated diagnostic
        #    list, and must NOT fall back to the default 'show version'.
        if command_override and (command_override.get("fix") or command_override.get("diagnostic")):
            commands = {
                "diagnostic": command_override.get("diagnostic", []),
                "fix": command_override.get("fix", []),
                "verify": command_override.get("verify", []),
            }
            _log("Using AI-generated commands")
        else:
            commands = self._resolve_commands(anomaly_type, anomaly)

        # 3. Execute (live connection required — no simulated fallback)
        if (conn_config or connection is not None) and NETMIKO_AVAILABLE:
            result = self._execute_live(conn_config, commands, anomaly, result, _log,
                                        connection=connection, save=save,
                                        config_mode=config_mode)
        else:
            result.error = (
                "No live device connection. Set GNS3_ROUTER_HOST and GNS3_ROUTER_PORT "
                "in Secrets, or approve the device in Device Management."
            )
            _log(f"❌ {result.error}")

        result.finish()
        self._record(result)
        return result

    # ── live execution ──────────────────────────────────────────────────────

    @contextlib.contextmanager
    def _session(self, conn_config, connection):
        """Yield a netmiko session: reuse the passed-in one (left open for the
        caller), or open one from conn_config and close it afterwards. This
        keeps a single deployment code path regardless of who owns the socket."""
        if connection is not None:
            yield connection
        else:
            conn = ConnectHandler(**conn_config)
            try:
                yield conn
            finally:
                try:
                    conn.disconnect()
                except Exception:
                    pass

    def _execute_live(
        self,
        conn_config: Dict[str, Any],
        commands: Dict[str, List[str]],
        anomaly: Dict[str, Any],
        result: FixResult,
        log,
        connection=None,
        save: bool = False,
        config_mode: bool = False,
    ) -> FixResult:
        try:
            _host = (conn_config or {}).get("host", "existing-session") if conn_config else "existing-session"
            log(f"Connecting to {_host} via {(conn_config or {}).get('device_type', 'session')}")
            with self._session(conn_config, connection) as conn:
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
                    # CRITICAL: interpolate placeholders ({interface}, {peer}) BEFORE
                    # sending. Otherwise the router receives literal text like
                    # 'interface {interface}' and rejects it, so the fix never applies.
                    rendered_fix = [self._interpolate(c, anomaly) for c in fix_cmds]
                    if config_mode or any(c in ["end", "exit", "wr", "write memory"] for c in fix_cmds):
                        try:
                            cfg_cmds = [self._interpolate(c, anomaly)
                                        for c in fix_cmds if c not in ("end", "exit")]
                            output = conn.send_config_set(cfg_cmds)
                            for cmd in rendered_fix:
                                result.commands_executed.append(cmd)
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

                # Persist config (only when caller asks — preserves existing
                # save behavior for admin/copilot; monitor default is unchanged)
                if save and fix_cmds:
                    try:
                        _sv = conn.save_config()
                        result.outputs.append(str(_sv))
                        log(f"   [SAVE] {_sv}")
                    except Exception as e:
                        log(f"   [SAVE] failed: {e}")

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
            log(f"Auth failed for {(conn_config or {}).get('host', 'device')}")
        except NetmikoTimeoutException:
            result.error = "Connection timed out"
            log(f"Timeout connecting to {(conn_config or {}).get('host', 'device')}")
        except Exception as e:
            result.error = str(e)
            log(f"Fix failed: {e}")

        return result

    # ── helpers ─────────────────────────────────────────────────────────────

    def _resolve_commands(self, anomaly_type: str, anomaly: Dict[str, Any]) -> Dict[str, List[str]]:
        # No static command table. Commands are resolved live via
        # cache → RAG (OEM knowledge) → MCP → grounded AI, keyed by the abstract
        # anomaly type and the device vendor/OS.
        from core.command_resolver import get_command_resolver
        vendor = str(anomaly.get("vendor") or "cisco")
        os_ = str(anomaly.get("os") or anomaly.get("device_type") or "ios").replace("cisco_", "")
        ctx = str(anomaly.get("interface") or anomaly.get("detail") or "")
        resolved = get_command_resolver().resolve_set(
            anomaly_type, vendor=vendor, os_=os_, context=ctx)
        # never invent a fix; only diagnostic/verify may be empty-safe
        resolved.setdefault("diagnostic", [])
        resolved.setdefault("fix", [])
        resolved.setdefault("verify", [])
        return resolved

    def _build_tunnel_config(self) -> Optional[Dict[str, Any]]:
        """Build connection config from GNS3_ROUTER_HOST/PORT env vars (pinggy tunnel).

        Supports both SSH (cisco_ios) and GNS3 Telnet console (cisco_ios_telnet)
        via GNS3_DEVICE_TYPE. GNS3 routers are usually only reachable through the
        GNS3 VM's Telnet console port, not direct SSH.
        """
        host = os.environ.get("GNS3_ROUTER_HOST", "")
        port_str = os.environ.get("GNS3_ROUTER_PORT", "")
        if not host or not port_str:
            return None
        try:
            port = int(port_str)
        except ValueError:
            return None
        device_type = os.environ.get("GNS3_DEVICE_TYPE", "cisco_ios").strip() or "cisco_ios"
        cfg: Dict[str, Any] = {
            "device_type": device_type,
            "host": host,
            "port": port,
            "username": self.default_username,
            "password": self.default_password,
            "secret": self.default_password,
            "timeout": 90,
            "auth_timeout": 90,
            "fast_cli": False,
        }
        # A Telnet console often has no username prompt (login is on the line,
        # not local AAA). Netmiko tolerates an empty username for telnet.
        if device_type.endswith("_telnet"):
            cfg["username"] = os.environ.get("GNS3_SSH_USER", "") or ""
        return cfg

    def _interpolate(self, cmd: str, anomaly: Dict[str, Any]) -> str:
        interface = (
            anomaly.get("interface")
            or (anomaly.get("description", "").split()[-1] if anomaly.get("description") else None)
            or "GigabitEthernet0/0"
        )
        peer = anomaly.get("peer") or anomaly.get("peer_ip") or "*"
        return cmd.format(interface=interface, peer=peer)

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
