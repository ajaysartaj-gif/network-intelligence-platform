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

# - Scapy (optional — used for real passive ICMP sniff) -
try:
    from scapy.all import sniff, IP, ICMP          # type: ignore
    SCAPY_OK = True
except Exception:
    SCAPY_OK = False

# - Netmiko (for AI-assisted SSH troubleshooting) -
try:
    from netmiko import ConnectHandler             # type: ignore
    NETMIKO_OK = True
except Exception:
    NETMIKO_OK = False


# -
# Data classes
# -

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
    # ── Site / inventory metadata (filled at approval time) ──
    region: str = ""              # "US" | "EMEA" | "APAC"
    country: str = ""
    city: str = ""
    site_name: str = ""

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


# -
# Discovery Engine
# -

class DeviceDiscoveryEngine:
    """
    Passive + active discovery of devices on the local network.

    Passive  : Sniffs ICMP echo-replies via scapy (if available), then verifies
               with an active ping from this host before queuing for approval.
    Active   : Reads the ARP table as hints only — each candidate must respond
               to ICMP from this tool or it is ignored.
    Poll loop: Runs in a background thread; Streamlit reads `pending_devices`.
               Only ICMP-reachable hosts appear in the approval list.
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

    # - Start / Stop -

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
            logger.info("Scapy not available — using ARP hints + ICMP verification.")
        self._probe_thread = threading.Thread(
            target=self._arp_probe_loop, daemon=True, name="DevDisc-Probe")
        self._probe_thread.start()

    def stop(self):
        self._running = False

    # - Scapy passive sniffer -

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

    # - ARP / probe fallback loop -

    def _arp_probe_loop(self):
        """Use ARP table entries as hints; only ICMP-reachable hosts are queued."""
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

    # - Register a discovered IP -

    def _register_ip(
        self,
        ip: str,
        mac: str = "",
        source: str = "ping",
        ping_rtt_ms: Optional[float] = None,
        require_ping: bool = True,
    ):
        """Classify and queue a newly discovered IP for approval.

        Only hosts that respond to ICMP from this tool are added to the
        pending approval list (unless require_ping=False and ping_rtt_ms is set).
        """
        # Filter non-device IPs before doing any work
        try:
            import ipaddress
            addr = ipaddress.ip_address(ip)
            if (addr.is_multicast          # 224.x.x.x – 239.x.x.x
                    or addr.is_loopback     # 127.x.x.x
                    or addr.is_link_local   # 169.254.x.x
                    or addr.is_unspecified  # 0.0.0.0
                    or str(addr).endswith(".0")
                    or str(addr).endswith(".255")):
                return
        except ValueError:
            return

        with self._lock:
            if ip in self._known:
                self._known[ip].last_seen = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if ping_rtt_ms is not None:
                    self._known[ip].ping_rtt_ms = ping_rtt_ms
                return   # already known

        # ICMP gate — ARP/scapy hints alone never enter the approval queue.
        if require_ping:
            if ping_rtt_ms is None:
                ping_rtt_ms = self._icmp_ping(ip)
            if ping_rtt_ms is None:
                logger.debug(f"Skipping {ip} ({source}): no ICMP reply from this host")
                return

        with self._lock:
            if ip in self._known:
                self._known[ip].last_seen = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if ping_rtt_ms is not None:
                    self._known[ip].ping_rtt_ms = ping_rtt_ms
                return

            logger.info(
                f"New device discovered: {ip} (via {source}, icmp ok, "
                f"{ping_rtt_ms:.0f}ms)"
            )

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
                ping_rtt_ms=ping_rtt_ms or 0.0,
                status="pending",
            )
            self._known[ip] = dev
            self._pending[ip] = dev

    # - Manual ping trigger (called from UI) -

    def ping_and_discover(self, ip: str) -> Optional[DiscoveredDevice]:
        """Actively ping an IP and register if reachable."""
        rtt = self._icmp_ping(ip)
        if rtt is not None:
            self._register_ip(ip, source="manual", ping_rtt_ms=rtt, require_ping=False)
            return self._known.get(ip)
        return None

    def scan_subnet(self, subnet_prefix: str = "192.168.0"):
        """Scan all .1–.254 hosts in a /24 subnet in background."""
        def _scan():
            for i in range(1, 255):
                ip = f"{subnet_prefix}.{i}"
                rtt = self._icmp_ping(ip, timeout=0.5)
                if rtt is not None:
                    self._register_ip(
                        ip, source="ping", ping_rtt_ms=rtt, require_ping=False,
                    )
        t = threading.Thread(target=_scan, daemon=True)
        t.start()

    # - Approval workflow -

    def approve_device(
        self,
        ip: str,
        approved_by: str = "admin",
        region: str = "",
        country: str = "",
        city: str = "",
        site_name: str = "",
    ) -> bool:
        with self._lock:
            dev = self._pending.get(ip)
            if not dev:
                return False

            # ── Enterprise inventory requirement: site metadata mandatory ──
            if not (region and country and city and site_name):
                logger.warning(
                    f"approve_device({ip}) rejected: missing site metadata "
                    f"(region={region!r}, country={country!r}, city={city!r}, "
                    f"site_name={site_name!r})"
                )
                return False

            dev.status = "approved"
            dev.approved_by = approved_by
            dev.region = region
            dev.country = country
            dev.city = city
            dev.site_name = site_name
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

            # Persist to disk immediately
            _save_device_state(self)

            # Seed the log store with an approval entry
            try:
                get_log_store().add_log(ip, {
                    "type": "approval",
                    "summary": f"Device approved by {approved_by}. Type: {dev.device_type}. "
                               f"Open ports: {dev.open_ports}. Source: {dev.source}. "
                               f"Site: {site_name}, {city}, {country}, {region}.",
                })
            except Exception:
                pass
            return True

    def reject_device(self, ip: str) -> bool:
        with self._lock:
            dev = self._pending.get(ip)
            if not dev:
                return False
            dev.status = "rejected"
            self._pending.pop(ip, None)
            _save_device_state(self)
            return True

    def disapprove_device(self, ip: str) -> bool:
        """Move an approved device back to the pending queue."""
        with self._lock:
            dev = self._approved.get(ip)
            if not dev:
                return False
            dev.status = "pending"
            dev.approved_by = ""
            self._approved.pop(ip, None)
            self._pending[ip] = dev
            _save_device_state(self)
            try:
                get_log_store().add_log(ip, {
                    "type": "disapproval",
                    "summary": "Device moved back to pending by admin.",
                })
            except Exception:
                pass
            logger.info(f"Device {ip} disapproved — moved to pending.")
            return True

    def start_login_session(self, ip: str,
                             credentials: Dict[str, str]) -> "TroubleshootSession":
        """SSH into device: ping → port → cipher-patch → login → show version → interfaces."""
        dev = self._known.get(ip)
        hostname = dev.hostname if dev else ip
        session = TroubleshootSession(device_ip=ip, device_hostname=hostname)
        self._sessions[ip] = session

        def _run():
            def step(name, ok, detail="", output=""):
                session.steps.append({
                    "name": name, "ok": ok,
                    "detail": detail, "output": output,
                    "ts": datetime.now().strftime("%H:%M:%S"),
                })

            dtype    = (dev.device_type if dev else "cisco_ios") or "cisco_ios"
            ssh_port = int(dev.ssh_port if dev else 22)

            # 1. Ping
            rtt = self._icmp_ping(ip)
            if rtt is None:
                step("Ping", False, f"{ip} unreachable"); session.status = "failed"; return
            step("Ping", True, f"RTT {rtt:.1f} ms")

            # 2. Port
            if not self._tcp_check(ip, ssh_port):
                step("SSH Port", False, f"Port {ssh_port} closed"); session.status = "failed"; return
            step("SSH Port", True, f"Port {ssh_port} open")

            # 4. Login
            if not NETMIKO_OK:
                step("Login", False, "netmiko not installed"); session.status = "failed"; return

            # Override telnet device_type if SSH port is open (router config has ip ssh version 2)
            if ssh_port == 22 and "telnet" in dtype:
                dtype = "cisco_ios"
                step("Device Type", True, "Auto-corrected to cisco_ios (SSH port 22 is open)")

            # Read credentials: explicit > env > default
            _user   = (credentials.get("username") or "").strip() or os.environ.get("GNS3_SSH_USER", "admin")
            _pass   = (credentials.get("password") or "").strip() or os.environ.get("GNS3_SSH_PASS", "admin")
            _secret = (credentials.get("enable_secret") or "").strip() or os.environ.get("GNS3_SSH_SECRET", "")

            conn = None
            try:
                from netmiko import ConnectHandler
                cfg = dict(
                    device_type=dtype,
                    host=ip,
                    port=ssh_port,
                    username=_user,
                    password=_pass,
                    timeout=30,
                    auth_timeout=30,
                    conn_timeout=15,
                    fast_cli=False,
                    global_delay_factor=2,
                )
                if _secret:
                    cfg["secret"] = _secret
                step("Connecting", True, f"Trying {dtype} — {_user}@{ip}:{ssh_port}")
                conn = ConnectHandler(**cfg)
                step("Login", True, f"Logged in as {_user}")
            except Exception as e:
                full_err = str(e).replace("\n", " ").strip()
                step("Login", False, f"{full_err}")
                session.status = "failed"
                return

            try:
                # 5. Hostname from show version
                ver = ""
                try:
                    ver = conn.send_command("show version", read_timeout=15)
                    m = re.search(r'^(\S+)\s+uptime', ver, re.MULTILINE | re.I)
                    if m:
                        session.device_hostname = m.group(1)
                        if dev: dev.hostname = m.group(1)
                        step("Hostname", True, f"Router: {session.device_hostname}")
                except Exception:
                    pass

                # 6. Prompt
                prompt = conn.find_prompt()
                step("Prompt", True, f"CLI: {prompt}")

                # 7. Interface brief + routing/neighbors for NetBrain topology analysis
                brief = conn.send_command("show ip interface brief", read_timeout=15)
                up   = brief.count(" up ")
                down = brief.count(" down ")
                step("Interfaces", True, f"{up} up / {down} down", output=brief)

                route = ""
                cdp = ""
                try:
                    route = conn.send_command("show ip route", read_timeout=15)
                except Exception:
                    pass
                try:
                    cdp = conn.send_command("show cdp neighbors", read_timeout=15)
                except Exception:
                    pass

                session.output = (
                    f"=== show version ===\n{ver}\n\n"
                    f"=== show ip interface brief ===\n{brief}\n\n"
                    f"=== show ip route ===\n{route}\n\n"
                    f"=== show cdp neighbors ===\n{cdp}"
                )
                session.ai_diagnosis = f"Login successful. Prompt: {prompt}"
                try:
                    get_log_store().add_log(ip, {"type": "manual_login",
                        "summary": f"Login OK as {cfg['username']}. Prompt: {prompt}. {up} up/{down} down."})
                except Exception:
                    pass
            finally:
                try: conn.disconnect()
                except Exception: pass
                session.status = "complete"
                session.completed_at = datetime.now().isoformat()

        threading.Thread(target=_run, daemon=True).start()
        return session

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

        # - Step 1: Ping -
        rtt = self._icmp_ping(ip)
        if rtt is None:
            step("Ping", False, f"{ip} not reachable")
            session.status = "failed"
            return
        step("Ping", True, f"RTT {rtt:.1f} ms")

        # - Step 2: Port check -
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

        # - Step 3: SSH login -
        if not NETMIKO_OK:
            step("SSH Login", False, "netmiko not installed")
            session.status = "failed"
            return

        # Override telnet device_type if SSH port is open
        if ssh_port == 22 and "telnet" in dtype:
            dtype = "cisco_ios"

        # Read credentials: explicit > env > default
        _user   = (creds.get("username") or "").strip() or os.environ.get("GNS3_SSH_USER", "admin")
        _pass   = (creds.get("password") or "").strip() or os.environ.get("GNS3_SSH_PASS", "admin")
        _secret = (creds.get("enable_secret") or "").strip() or os.environ.get("GNS3_SSH_SECRET", "")

        conn = None
        try:
            cfg: Dict[str, Any] = dict(
                device_type=dtype,
                host=ip,
                port=ssh_port,
                username=_user,
                password=_pass,
                timeout=30,
                auth_timeout=30,
                conn_timeout=15,
                fast_cli=False,
                global_delay_factor=2,
            )
            if _secret:
                cfg["secret"] = _secret
            conn = ConnectHandler(**cfg)
            step("SSH Login", True, f"Logged in as {_user}")
        except Exception as e:
            full_err = str(e).replace("\n", " ").strip()
            step("SSH Login", False, full_err)
            session.status = "failed"
            return

        try:
            # - Step 4: Gather diagnostics -
            ver_out = ""
            try:
                ver_out = conn.send_command("show version", read_timeout=15)
                m = re.search(r'^(\S+)\s+uptime\s+is', ver_out, re.MULTILINE | re.IGNORECASE)
                if m:
                    real_hostname = m.group(1).strip()
                    session.device_hostname = real_hostname
                    if dev:
                        dev.hostname = real_hostname
                    step("Hostname", True, f"Router name: {real_hostname}")
            except Exception:
                ver_out = ""

            diag_cmds = [
                "show version",
                "show logging | last 50",
                "show processes cpu sorted",
            ]
            raw_outputs: Dict[str, str] = {"show version": ver_out} if ver_out else {}
            for cmd in diag_cmds:
                if cmd == "show version" and ver_out:
                    session.commands_run.append(cmd)
                    continue   # already captured above
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

            # Save raw diagnostic output to log store immediately
            try:
                get_log_store().add_log(ip, {
                    "type": "ssh_diagnostics",
                    "summary": f"Collected {len(raw_outputs)} commands via SSH",
                    "commands": list(raw_outputs.keys()),
                    "output_chars": len(full_diag),
                })
            except Exception:
                pass

            # - Step 5: AI diagnosis -
            step("AI Analysis", True, "Sending diagnostics to AI...")

            # Include previous device history as context for better AI suggestions
            prior_context = ""
            try:
                prior_context = get_log_store().get_context_for_ai(ip)
            except Exception:
                pass

            diagnosis_prompt = (
                "You are a senior Cisco network engineer performing remote diagnostics.\n"
                f"Device IP: {ip}  Hostname: {session.device_hostname}\n\n"
                + (f"PRIOR HISTORY FOR THIS DEVICE:\n{prior_context}\n\n" if prior_context else "")
                + "CURRENT DIAGNOSTIC OUTPUT FROM THE DEVICE:\n\n"
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

            # - Step 6: Extract and apply fixes (only if approved) -
            fix_plan = _extract_fix_commands(session.ai_diagnosis)
            session.ai_fix_plan = "\n".join(fix_plan)

            if apply_fixes and fix_plan:
                step("Apply Fixes", True, f"Applying {len(fix_plan)} command(s)...")
                try:
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
                    # Log applied fixes
                    try:
                        get_log_store().add_log(ip, {
                            "type": "fix_applied",
                            "summary": f"Applied {len(fix_plan)} fix command(s)",
                            "commands": fix_plan,
                        })
                    except Exception:
                        pass
                except Exception as e:
                    step("Apply Fixes", False, str(e))
            elif fix_plan:
                step("Fixes Ready", True,
                     f"{len(fix_plan)} fix command(s) ready — awaiting approval")

            # Always save AI result to log store
            try:
                get_log_store().add_ai_result(
                    ip,
                    diagnosis=session.ai_diagnosis,
                    fix_plan=session.ai_fix_plan,
                    applied=session.fix_applied,
                )
            except Exception:
                pass

        finally:
            try:
                conn.disconnect()
            except Exception:
                pass
            session.status = "complete"
            session.completed_at = datetime.now().isoformat()

    def get_session(self, ip: str) -> Optional[TroubleshootSession]:
        return self._sessions.get(ip)

    def get_pending(self) -> List[DiscoveredDevice]:
        """Return all devices awaiting approval."""
        with self._lock:
            return list(self._pending.values())

    def get_approved(self) -> List[DiscoveredDevice]:
        """Return all approved devices."""
        with self._lock:
            return list(self._approved.values())

    def get_all(self) -> List[DiscoveredDevice]:
        """Return every known device (pending + approved + rejected)."""
        with self._lock:
            return list(self._known.values())

    def get_device(self, ip: str) -> Optional[DiscoveredDevice]:
        """Return a single device by IP, or None."""
        return self._known.get(ip)

    def approve_and_apply_fixes(self, ip: str, call_ai_fn,
                                 credentials: Dict[str, str]) -> TroubleshootSession:
        """Re-run troubleshoot with apply_fixes=True after user approves."""
        return self.start_ai_troubleshoot(ip, call_ai_fn, credentials, approved=True)

    # - Utilities -

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
        """
        Identify OEM + device type. Tries a live banner/version fingerprint
        first (reliable); falls back to hostname-keyword guessing only if
        the device can't be reached or doesn't expose a recognizable banner.
        """
        # ── Attempt 1: reliable banner-based detection ──
        if 22 in open_ports or 23 in open_ports:
            try:
                from core.device_inventory_meta import detect_oem_and_type
                username = os.environ.get("GNS3_SSH_USER", "")
                password = os.environ.get("GNS3_SSH_PASS", "")
                vendor, dtype, _banner = detect_oem_and_type(
                    ip,
                    ssh_port=22 if 22 in open_ports else 22,
                    telnet_port=23 if 23 in open_ports else 23,
                    username=username,
                    password=password,
                    timeout=6,
                )
                if dtype:
                    logger.info(f"Banner-detected {ip}: vendor={vendor} type={dtype}")
                    return dtype, vendor
            except Exception as exc:
                logger.debug(f"Banner detection failed for {ip}, falling back: {exc}")

        # ── Attempt 2: hostname-keyword fallback (weak signal) ──
        h = hostname.lower()
        if any(k in h for k in ["router", "r1", "r2", "r3", "gns", "cisco"]):
            return "cisco_ios", "Cisco"
        if any(k in h for k in ["switch", "sw", "nexus"]):
            return "cisco_nxos", "Cisco"
        if any(k in h for k in ["juniper", "junos", "j1"]):
            return "juniper_junos", "Juniper"
        if any(k in h for k in ["arista", "eos"]):
            return "arista_eos", "Arista"
        if any(k in h for k in ["aruba", "cx"]):
            return "aruba_os", "HPE Aruba"
        if any(k in h for k in ["palo", "pan"]):
            return "paloalto_panos", "Palo Alto"
        if any(k in h for k in ["forti"]):
            return "fortinet", "Fortinet"
        if 22 in open_ports and 443 not in open_ports:
            return "cisco_ios", "Unknown"
        if 23 in open_ports:
            return "cisco_ios_telnet", "Unknown"
        return "linux", "Unknown"


# - Fix command extractor -

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


# ══════════════════════════════════════════════════════════════════════════════
# Device Log Store — persists SSH output + AI suggestions to disk
# ══════════════════════════════════════════════════════════════════════════════

class DeviceLogStore:
    """
    Stores per-device logs (raw SSH output, AI diagnosis, fix history) in a
    local JSON file so AI always has context even across restarts.
    """

    def __init__(self, path: str = ".netbrain_device_logs.json"):
        self._path = path
        self._lock = threading.Lock()
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        try:
            if os.path.exists(self._path):
                with open(self._path) as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save(self):
        try:
            with open(self._path, "w") as f:
                json.dump(self._data, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"DeviceLogStore save failed: {e}")

    def add_log(self, ip: str, entry: Dict[str, Any]):
        """Append a log entry for a device."""
        with self._lock:
            if ip not in self._data:
                self._data[ip] = {"logs": [], "ai_history": [], "last_health": "unknown"}
            self._data[ip]["logs"].append({
                **entry,
                "ts": datetime.now().isoformat(),
            })
            # Keep last 50 entries per device
            self._data[ip]["logs"] = self._data[ip]["logs"][-50:]
            self._save()

    def add_ai_result(self, ip: str, diagnosis: str, fix_plan: str, applied: bool):
        """Store an AI diagnosis + fix result."""
        with self._lock:
            if ip not in self._data:
                self._data[ip] = {"logs": [], "ai_history": [], "last_health": "unknown"}
            self._data[ip]["ai_history"].append({
                "ts": datetime.now().isoformat(),
                "diagnosis": diagnosis[:3000],
                "fix_plan": fix_plan[:1000],
                "applied": applied,
            })
            # Extract health from diagnosis
            for line in diagnosis.splitlines():
                if line.startswith("HEALTH:"):
                    self._data[ip]["last_health"] = line.replace("HEALTH:", "").strip()
            self._data[ip]["ai_history"] = self._data[ip]["ai_history"][-20:]
            self._save()

    def get_context_for_ai(self, ip: str, max_chars: int = 4000) -> str:
        """Return a formatted context string for the AI prompt."""
        with self._lock:
            d = self._data.get(ip, {})
        if not d:
            return ""
        parts = []
        # Last health status
        health = d.get("last_health", "unknown")
        parts.append(f"Last known health: {health}")
        # Recent raw logs (last 5)
        logs = d.get("logs", [])[-5:]
        if logs:
            parts.append("\nRecent device logs:")
            for log in logs:
                parts.append(f"  [{log.get('ts','')}] {log.get('type','')} — {str(log.get('summary',''))[:200]}")
        # Last AI diagnosis
        ai_hist = d.get("ai_history", [])
        if ai_hist:
            last = ai_hist[-1]
            parts.append(f"\nPrevious AI diagnosis ({last.get('ts','')}):")
            parts.append(last.get("diagnosis", "")[:1500])
            if last.get("applied"):
                parts.append(f"\nPrevious fix applied: {last.get('fix_plan','')[:500]}")
        result = "\n".join(parts)
        return result[:max_chars]

    def get_all_logs(self, ip: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data.get(ip, {}))

    def get_all_devices(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data)


# ══════════════════════════════════════════════════════════════════════════════
# Persistent device state — survives Streamlit reruns and restarts
# ══════════════════════════════════════════════════════════════════════════════

import json

_STATE_FILE = ".netbrain_devices.json"


def _save_device_state(engine: "DeviceDiscoveryEngine"):
    """Write approved + pending devices to JSON so they survive restarts."""
    try:
        state = {
            "approved": {ip: d.to_dict() for ip, d in engine._approved.items()},
            "pending":  {ip: d.to_dict() for ip, d in engine._pending.items()},
            "known":    {ip: d.to_dict() for ip, d in engine._known.items()},
        }
        with open(_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        logger.warning(f"Could not save device state: {e}")


def _load_device_state(engine: "DeviceDiscoveryEngine"):
    """Restore devices from JSON on startup."""
    if not os.path.exists(_STATE_FILE):
        return
    try:
        with open(_STATE_FILE) as f:
            state = json.load(f)
        for ip, d in state.get("known", {}).items():
            dev = DiscoveredDevice(**{k: v for k, v in d.items()
                                      if k in DiscoveredDevice.__dataclass_fields__})
            engine._known[ip] = dev
        for ip, d in state.get("approved", {}).items():
            dev = engine._known.get(ip)
            if dev:
                dev.status = "approved"
                engine._approved[ip] = dev
        for ip, d in state.get("pending", {}).items():
            dev = engine._known.get(ip)
            if dev and dev.status == "pending":
                engine._pending[ip] = dev
        logger.info(f"Restored {len(engine._approved)} approved, "
                    f"{len(engine._pending)} pending devices from state file.")
    except Exception as e:
        logger.warning(f"Could not load device state: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Singleton — anchored to module level AND patchable from session_state
# ══════════════════════════════════════════════════════════════════════════════

_engine_instance: Optional["DeviceDiscoveryEngine"] = None
_log_store_instance: Optional[DeviceLogStore] = None
_engine_lock = threading.Lock()


def get_discovery_engine() -> "DeviceDiscoveryEngine":
    """
    Returns the singleton DeviceDiscoveryEngine.
    Module-level singleton survives Streamlit reruns within the same process.
    JSON state file ensures devices persist across full restarts.
    """
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                eng = DeviceDiscoveryEngine()
                _load_device_state(eng)   # restore from disk
                eng.start()
                _engine_instance = eng
    return _engine_instance


def get_log_store() -> DeviceLogStore:
    """Returns the singleton DeviceLogStore."""
    global _log_store_instance
    if _log_store_instance is None:
        with _engine_lock:
            if _log_store_instance is None:
                _log_store_instance = DeviceLogStore()
    return _log_store_instance
