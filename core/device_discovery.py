"""
core/device_discovery.py
========================
NetBrain AI — Live Device Discovery Engine
-------------------------------------------
Listens for ICMP ping replies (via scapy or socket probe fallback),
auto-classifies GNS3 devices, queues them for approval, and integrates
with the LocalRouterAccessManager for immediate AI troubleshooting.

Works on: macOS · Linux · GitHub Codespaces · Windows (with Npcap)
"""
from __future__ import annotations

import os, re, socket, subprocess, threading, time, logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any

logger = logging.getLogger("NetBrain.DeviceDiscovery")

# ── Scapy (optional — used for real passive ICMP sniff) ───────────────────────
try:
    from scapy.all import sniff, IP, ICMP          # type: ignore
    SCAPY_OK = True
except Exception:
    SCAPY_OK = False

# ── Netmiko (for AI-assisted SSH troubleshooting) ────────────────────────────
try:
    from netmiko import ConnectHandler             # type: ignore
    NETMIKO_OK = True
except Exception:
    NETMIKO_OK = False


# ══════════════════════════════════════════════════════════════════════════════
# Data classes
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DiscoveredDevice:
    ip: str
    hostname: str = ""
    mac: str = ""
    device_type: str = "cisco_ios"
    vendor: str = ""
    open_ports: List[int] = field(default_factory=list)
    ping_rtt_ms: float = 0.0
    first_seen: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    last_seen: str  = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    source: str = "ping"          # "ping" | "arp" | "manual" | "gns3"
    status: str = "pending"       # "pending" | "approved" | "rejected" | "troubleshooting"
    approved_by: str = ""
    ssh_port: int = 22
    telnet_port: int = 23
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class TroubleshootSession:
    device_ip: str
    device_hostname: str
    status: str = "running"       # "running" | "complete" | "failed"
    steps: List[Dict[str, Any]] = field(default_factory=list)
    commands_run: List[str] = field(default_factory=list)
    output: str = ""
    ai_diagnosis: str = ""
    ai_fix_plan: str = ""
    fix_applied: bool = False
    approved: bool = False
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# Discovery Engine
# ══════════════════════════════════════════════════════════════════════════════

class DeviceDiscoveryEngine:
    """
    Passive + active discovery of devices on the local network.

    Passive  : Sniffs ICMP echo-replies via scapy (if available).
    Active   : TCP probe against common management ports (22, 23, 80, 443).
    Poll loop: Runs in a background thread; Streamlit reads `pending_devices`.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._known: Dict[str, DiscoveredDevice] = {}       # ip → device
        self._pending: Dict[str, DiscoveredDevice] = {}     # awaiting approval
        self._approved: Dict[str, DiscoveredDevice] = {}    # approved inventory
        self._sessions: Dict[str, TroubleshootSession] = {} # ip → session
        self._sniff_thread: Optional[threading.Thread] = None
        self._probe_thread: Optional[threading.Thread] = None
        self._running = False
        self._gns3_subnets: List[str] = ["192.168.0.0/24", "10.0.0.0/24",
                                          "172.16.0.0/24"]
        self.poll_interval_sec = 10
        self._seen_ips_this_cycle: set = set()

    # ── Start / Stop ──────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        if SCAPY_OK:
            self._sniff_thread = threading.Thread(
                target=self._scapy_sniff_loop, daemon=True, name="DevDisc-Sniff")
            self._sniff_thread.start()
            logger.info("Passive ICMP sniffer started (scapy).")
        else:
            logger.info("Scapy not available — using ARP+probe fallback.")
        self._probe_thread = threading.Thread(
            target=self._arp_probe_loop, daemon=True, name="DevDisc-Probe")
        self._probe_thread.start()

    def stop(self):
        self._running = False

    # ── Scapy passive sniffer ─────────────────────────────────────────────────

    def _scapy_sniff_loop(self):
        """Sniff ICMP echo-reply packets — picks up any device that replies to ping."""
        def _handle(pkt):
            try:
                if pkt.haslayer(ICMP) and pkt[ICMP].type == 0:   # echo-reply
                    src_ip = pkt[IP].src
                    self._register_ip(src_ip, source="ping")
            except Exception:
                pass
        while self._running:
            try:
                sniff(filter="icmp", prn=_handle, timeout=5, store=False)
            except Exception as e:
                logger.debug(f"Scapy sniff error: {e}")
                time.sleep(5)

    # ── ARP / probe fallback loop ─────────────────────────────────────────────

    def _arp_probe_loop(self):
        """Parse ARP table + probe common ports to find live hosts."""
        while self._running:
            try:
                # macOS / Linux ARP table
                arp_out = subprocess.check_output(
                    ["arp", "-an"], stderr=subprocess.DEVNULL
                ).decode(errors="replace")
                for line in arp_out.splitlines():
                    m = re.search(r'\((\d+\.\d+\.\d+\.\d+)\)', line)
                    if m:
                        ip = m.group(1)
                        if not ip.endswith(".255") and not ip.endswith(".0"):
                            # Get MAC if present
                            mac_m = re.search(r'([\da-f]{1,2}(?::[\da-f]{1,2}){5})', line, re.I)
                            mac = mac_m.group(1) if mac_m else ""
                            self._register_ip(ip, mac=mac, source="arp")
            except Exception:
                pass
            time.sleep(self.poll_interval_sec)

    # ── Register a discovered IP ──────────────────────────────────────────────

    def _register_ip(self, ip: str, mac: str = "", source: str = "ping"):
        """Classify and queue a newly discovered IP for approval."""
        with self._lock:
            if ip in self._known:
                self._known[ip].last_seen = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return   # already known

            logger.info(f"New device discovered: {ip} (via {source})")

            # Resolve hostname
            hostname = self._resolve_hostname(ip)

            # Detect open management ports
            open_ports = self._probe_ports(ip, [22, 23, 80, 443, 8080])

            # Guess device type
            device_type, vendor = self._guess_device_type(ip, open_ports, hostname)

            dev = DiscoveredDevice(
                ip=ip, hostname=hostname, mac=mac,
                device_type=device_type, vendor=vendor,
                open_ports=open_ports, source=source,
                status="pending",
            )
            self._known[ip] = dev
            self._pending[ip] = dev

    # ── Manual ping trigger (called from UI) ─────────────────────────────────

    def ping_and_discover(self, ip: str) -> Optional[DiscoveredDevice]:
        """Actively ping an IP and register if reachable."""
        rtt = self._icmp_ping(ip)
        if rtt is not None:
            self._register_ip(ip, source="manual")
            dev = self._known.get(ip)
            if dev:
                dev.ping_rtt_ms = rtt
            return dev
        return None

    def scan_subnet(self, subnet_prefix: str = "192.168.0"):
        """Scan all .1–.254 hosts in a /24 subnet in background."""
        def _scan():
            for i in range(1, 255):
                ip = f"{subnet_prefix}.{i}"
                rtt = self._icmp_ping(ip, timeout=0.5)
                if rtt is not None:
                    self._register_ip(ip, source="ping")
                    if ip in self._known:
                        self._known[ip].ping_rtt_ms = rtt
        t = threading.Thread(target=_scan, daemon=True)
        t.start()

    # ── Approval workflow ─────────────────────────────────────────────────────

    def approve_device(self, ip: str, approved_by: str = "admin") -> bool:
        with self._lock:
            dev = self._pending.get(ip)
            if not dev:
                return False
            dev.status = "approved"
            dev.approved_by = approved_by
            self._approved[ip] = dev
            self._pending.pop(ip, None)

            # Also register into LocalRouterAccessManager if available
            try:
                from Local_Router_Access import get_manager, Device, DeviceCredentials
                mgr = get_manager()
                mgr.register_device(Device(
                    hostname=dev.hostname or ip,
                    ip=ip,
                    device_type=dev.device_type,
                    ssh_port=dev.ssh_port,
                ))
                logger.info(f"Device {ip} approved and registered in LocalRouterAccessManager.")
            except Exception as e:
                logger.warning(f"Could not register {ip} in LRA: {e}")
            return True

    def reject_device(self, ip: str) -> bool:
        with self._lock:
            dev = self._pending.get(ip)
            if not dev:
                return False
            dev.status = "rejected"
            self._pending.pop(ip, None)
            return True

    # ── Getters ───────────────────────────────────────────────────────────────

    def get_pending(self) -> List[DiscoveredDevice]:
        with self._lock:
            return list(self._pending.values())

    def get_approved(self) -> List[DiscoveredDevice]:
        with self._lock:
            return list(self._approved.values())

    def get_all(self) -> List[DiscoveredDevice]:
        with self._lock:
            return list(self._known.values())

    def get_device(self, ip: str) -> Optional[DiscoveredDevice]:
        return self._known.get(ip)

    # ── AI Troubleshooting ───────────────────────────────────────────────────

    def start_ai_troubleshoot(self, ip: str, call_ai_fn,
                               credentials: Dict[str, str],
                               approved: bool = False) -> TroubleshootSession:
        """
        SSH into device, run diagnostics, get AI analysis + fix plan.
        Only executes fixes if approved=True.
        """
        dev = self._known.get(ip)
        hostname = dev.hostname if dev else ip
        session = TroubleshootSession(device_ip=ip, device_hostname=hostname)
        self._sessions[ip] = session

        t = threading.Thread(
            target=self._run_troubleshoot,
            args=(session, dev, credentials, call_ai_fn, approved),
            daemon=True,
        )
        t.start()
        return session

    def _run_troubleshoot(self, session: TroubleshootSession,
                           dev: Optional[DiscoveredDevice],
                           creds: Dict[str, str],
                           call_ai_fn,
                           apply_fixes: bool):
        def step(name: str, ok: bool, detail: str = "", output: str = ""):
            session.steps.append({"name": name, "ok": ok,
                                  "detail": detail, "output": output,
                                  "ts": datetime.now().strftime("%H:%M:%S")})
            logger.info(f"[Troubleshoot {session.device_ip}] {name}: {'OK' if ok else 'FAIL'} — {detail}")

        ip      = session.device_ip
        dtype   = (dev.device_type if dev else "cisco_ios") or "cisco_ios"
        ssh_port = int(dev.ssh_port if dev else 22)

        # ── Step 1: Ping ──────────────────────────────────────────────────────
        rtt = self._icmp_ping(ip)
        if rtt is None:
            step("Ping", False, f"{ip} not reachable")
            session.status = "failed"
            return
        step("Ping", True, f"RTT {rtt:.1f} ms")

        # ── Step 2: Port check ────────────────────────────────────────────────
        ssh_ok = self._tcp_check(ip, ssh_port)
        step("SSH Port", ssh_ok, f"Port {ssh_port} {'open' if ssh_ok else 'closed'}")
        if not ssh_ok:
            tel_ok = self._tcp_check(ip, 23)
            step("Telnet Port", tel_ok, f"Port 23 {'open' if tel_ok else 'closed'}")
            if not tel_ok:
                session.status = "failed"
                return
            dtype = dtype.replace("cisco_ios", "cisco_ios_telnet") \
                         .replace("cisco_iosxe", "cisco_ios_telnet")

        # ── Step 3: SSH login ─────────────────────────────────────────────────
        if not NETMIKO_OK:
            step("SSH Login", False, "netmiko not installed")
            session.status = "failed"
            return

        conn = None
        try:
            cfg: Dict[str, Any] = dict(
                device_type=dtype,
                host=ip,
                port=ssh_port,
                username=creds.get("username", "admin"),
                password=creds.get("password", "admin"),
                timeout=20,
                fast_cli=False,
            )
            if creds.get("enable_secret"):
                cfg["secret"] = creds["enable_secret"]
            conn = ConnectHandler(**cfg)
            step("SSH Login", True, f"Logged in as {cfg['username']}")
        except Exception as e:
            step("SSH Login", False, str(e))
            session.status = "failed"
            return

        try:
            # ── Step 4: Gather diagnostics ────────────────────────────────────
            diag_cmds = [
                "show version",
                "show interfaces",
                "show ip interface brief",
                "show ip route",
                "show logging | last 30",
                "show processes cpu sorted | head 10",
            ]
            raw_outputs: Dict[str, str] = {}
            for cmd in diag_cmds:
                try:
                    out = conn.send_command(cmd, read_timeout=15)
                    raw_outputs[cmd] = out
                    session.commands_run.append(cmd)
                    step(f"Run: {cmd}", True, f"{len(out)} chars")
                except Exception as e:
                    raw_outputs[cmd] = f"ERROR: {e}"
                    step(f"Run: {cmd}", False, str(e))

            full_diag = "\n\n".join(
                f"=== {c} ===\n{o}" for c, o in raw_outputs.items()
            )
            session.output = full_diag

            # ── Step 5: AI diagnosis ──────────────────────────────────────────
            step("AI Analysis", True, "Sending diagnostics to AI...")
            diagnosis_prompt = (
                "You are a senior Cisco network engineer performing remote diagnostics.\n"
                f"Device IP: {ip}  Hostname: {session.device_hostname}\n\n"
                "Below is the full diagnostic output from the device:\n\n"
                f"{full_diag[:6000]}\n\n"
                "Tasks:\n"
                "1. Identify ALL problems, anomalies, or misconfigurations visible in this output.\n"
                "2. For each problem, explain the root cause clearly.\n"
                "3. Provide an exact numbered list of IOS commands to fix each problem.\n"
                "4. Mark commands that need 'configure terminal' context separately.\n"
                "5. Assess overall device health: CRITICAL / DEGRADED / HEALTHY.\n\n"
                "Format your response as:\n"
                "HEALTH: <status>\n\n"
                "PROBLEMS FOUND:\n<numbered list>\n\n"
                "FIX COMMANDS:\n<exact IOS commands, one per line, prefixed with context: [EXEC] or [CONFIG]>\n\n"
                "SUMMARY:\n<2-3 sentence plain-English summary>"
            )
            try:
                ai_response = call_ai_fn(diagnosis_prompt)
                session.ai_diagnosis = ai_response
                step("AI Analysis", True, "Diagnosis complete")
            except Exception as e:
                session.ai_diagnosis = f"AI unavailable: {e}"
                step("AI Analysis", False, str(e))

            # ── Step 6: Extract and apply fixes (only if approved) ────────────
            fix_plan = _extract_fix_commands(session.ai_diagnosis)
            session.ai_fix_plan = "\n".join(fix_plan)

            if apply_fixes and fix_plan:
                step("Apply Fixes", True, f"Applying {len(fix_plan)} command(s)...")
                try:
                    # Separate exec vs config commands
                    config_cmds = [c.replace("[CONFIG]", "").strip()
                                   for c in fix_plan if "[CONFIG]" in c]
                    exec_cmds   = [c.replace("[EXEC]", "").strip()
                                   for c in fix_plan if "[EXEC]" in c]
                    fix_output  = []
                    if exec_cmds:
                        for c in exec_cmds:
                            o = conn.send_command(c, read_timeout=20)
                            fix_output.append(f"$ {c}\n{o}")
                            session.commands_run.append(c)
                    if config_cmds:
                        o = conn.send_config_set(config_cmds)
                        fix_output.append(f"[CONFIG]\n{o}")
                    step("Apply Fixes", True,
                         "Fixes applied",
                         output="\n\n".join(fix_output))
                    session.fix_applied = True
                except Exception as e:
                    step("Apply Fixes", False, str(e))
            elif fix_plan:
                step("Fixes Ready", True,
                     f"{len(fix_plan)} fix command(s) ready — awaiting approval")

        finally:
            try:
                conn.disconnect()
            except Exception:
                pass
            session.status = "complete"
            session.completed_at = datetime.now().isoformat()

    def get_session(self, ip: str) -> Optional[TroubleshootSession]:
        return self._sessions.get(ip)

    def approve_and_apply_fixes(self, ip: str, call_ai_fn,
                                 credentials: Dict[str, str]) -> TroubleshootSession:
        """Re-run troubleshoot with apply_fixes=True after user approves."""
        return self.start_ai_troubleshoot(ip, call_ai_fn, credentials, approved=True)

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _icmp_ping(self, ip: str, timeout: float = 1.0) -> Optional[float]:
        """Returns RTT in ms or None if unreachable."""
        try:
            param = "-n" if os.name == "nt" else "-c"
            t0 = time.perf_counter()
            rc = subprocess.call(
                ["ping", param, "1", "-W", str(int(timeout * 1000)),  ip],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            if rc == 0:
                return (time.perf_counter() - t0) * 1000
        except Exception:
            pass
        return None

    def _tcp_check(self, ip: str, port: int, timeout: int = 3) -> bool:
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except OSError:
            return False

    def _probe_ports(self, ip: str, ports: List[int]) -> List[int]:
        return [p for p in ports if self._tcp_check(ip, p, timeout=1)]

    def _resolve_hostname(self, ip: str) -> str:
        try:
            return socket.gethostbyaddr(ip)[0]
        except Exception:
            return ""

    def _guess_device_type(self, ip: str, open_ports: List[int],
                            hostname: str) -> tuple:
        h = hostname.lower()
        if any(k in h for k in ["router", "r1", "r2", "r3", "gns", "cisco"]):
            return "cisco_ios", "Cisco"
        if any(k in h for k in ["switch", "sw", "nexus"]):
            return "cisco_nxos", "Cisco"
        if any(k in h for k in ["juniper", "junos", "j1"]):
            return "juniper_junos", "Juniper"
        if any(k in h for k in ["arista", "eos"]):
            return "arista_eos", "Arista"
        if 22 in open_ports and 443 not in open_ports:
            return "cisco_ios", "Unknown"
        if 23 in open_ports:
            return "cisco_ios_telnet", "Unknown"
        return "linux", "Unknown"


# ── Fix command extractor ─────────────────────────────────────────────────────

def _extract_fix_commands(ai_text: str) -> List[str]:
    """Parse AI response and extract [EXEC] and [CONFIG] tagged commands."""
    cmds = []
    for line in ai_text.splitlines():
        line = line.strip()
        if line.startswith("[EXEC]") or line.startswith("[CONFIG]"):
            cmds.append(line)
        elif re.match(r'^\d+\.\s+(no |ip |interface |router |service )', line, re.I):
            cmds.append(f"[CONFIG] {line.split('.', 1)[1].strip()}")
    return cmds


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine_instance: Optional[DeviceDiscoveryEngine] = None
_engine_lock = threading.Lock()

def get_discovery_engine() -> DeviceDiscoveryEngine:
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = DeviceDiscoveryEngine()
                _engine_instance.start()
    return _engine_instance
