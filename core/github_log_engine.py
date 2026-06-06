import os
import subprocess
import re
from typing import List, Optional, Dict

from core.ai_engine import ask_ai

try:
    from netmiko import ConnectHandler
    NETMIKO_AVAILABLE = True
except Exception:
    NETMIKO_AVAILABLE = False


class GitHubLogEngine:
    """Simple engine to sync a GitHub repo of router logs, read files, analyze with AI,
    and optionally apply remediation commands to devices via Netmiko.
    """

    def __init__(self, repo: str = "https://github.com/ajaysartaj-gif/gns3-router-logs.git", local_path: str = "data/gns3-router-logs"):
        self.repo = repo
        self.local_path = local_path
        self.last_sync: Optional[str] = None

        # UI-friendly attributes expected by the Streamlit app
        self.raw_url = os.environ.get("GNS3_LOG_GITHUB_URL", "")
        self.default_device = os.environ.get("GNS3_LOG_DEFAULT_DEVICE", "R1")

        # Runtime status and recent events (simple parsed view)
        self._last_error: Optional[str] = None
        self._lines_parsed: int = 0
        self.recent_events: List[Dict] = []

    def sync_repo(self) -> str:
        os.makedirs(os.path.dirname(self.local_path), exist_ok=True)
        if not os.path.exists(self.local_path) or not os.listdir(self.local_path):
            # clone
            try:
                subprocess.run(["git", "clone", "--depth", "1", self.repo, self.local_path], check=True)
                self.last_sync = "cloned"
                return "cloned"
            except Exception as e:
                return f"clone_failed: {e}"
        else:
            # pull
            try:
                subprocess.run(["git", "-C", self.local_path, "pull"], check=True)
                self.last_sync = "pulled"
                return "pulled"
            except Exception as e:
                return f"pull_failed: {e}"

    def list_logs(self) -> List[str]:
        if not os.path.exists(self.local_path):
            return []
        out: List[str] = []
        for root, _, files in os.walk(self.local_path):
            for f in files:
                if f.lower().endswith(('.log', '.txt')) or 'log' in f.lower():
                    out.append(os.path.join(root, f))
        return sorted(out)

    def read_log(self, path: str) -> str:
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                return fh.read()
        except Exception as e:
            return f"read_error: {e}"

    def analyze_log(self, content: str) -> str:
        prompt = (
            "You are an expert network engineer. Analyze the following router/system log and: "
            "1) Summarize the key errors and probable root causes. "
            "2) Suggest safe diagnostic commands to run on the device. "
            "3) If appropriate, suggest safe remediation commands and note risk.\n\n"
        )
        prompt += "LOG:\n" + content[:15000]
        try:
            return ask_ai(prompt)
        except Exception as e:
            return f"ai_error: {e}"

    def propose_remediation_commands(self, analysis_text: str) -> List[str]:
        cmds: List[str] = []
        lower = analysis_text.lower()
        if 'interface' in lower:
            cmds.append('show interfaces status')
            cmds.append('show interfaces description')
        if 'bgp' in lower:
            cmds.append('show ip bgp summary')
            cmds.append('clear ip bgp *')
        if 'cpu' in lower or 'memory' in lower:
            cmds.append('show processes cpu | include CPU')
            cmds.append('show processes memory | include Processor')
        if 'authentication' in lower or 'login' in lower:
            cmds.append('show running-config | include username')
        if not cmds:
            cmds.append('show logging | tail 50')
        return cmds

    def apply_remediation(self, device: Dict[str, object], commands: List[str], dry_run: bool = True) -> Dict[str, object]:
        result = {
            'device': device.get('host', device.get('hostname', 'unknown')),
            'commands': commands,
            'dry_run': dry_run,
            'executed': False,
            'output': [],
            'error': None,
        }

        if dry_run:
            result['executed'] = False
            result['output'] = ['dry run: no commands executed']
            return result

        if not NETMIKO_AVAILABLE:
            result['error'] = 'netmiko_unavailable'
            return result

        try:
            conn = ConnectHandler(**device)
            if device.get('secret'):
                try:
                    conn.enable()
                except Exception:
                    pass

            outputs = []
            for cmd in commands:
                try:
                    out = conn.send_command(cmd, use_textfsm=False)
                    outputs.append(f"CMD: {cmd}\n{out}")
                except Exception as e:
                    outputs.append(f"CMD_ERR: {cmd} -> {e}")

            try:
                conn.disconnect()
            except Exception:
                pass

            result['executed'] = True
            result['output'] = outputs
            return result

        except Exception as e:
            result['error'] = str(e)
            return result

    # -- Compatibility helpers for the Streamlit UI ------------------
    def poll(self) -> None:
        """Fetch the configured raw URL (if present) and populate a very
        small `recent_events` view. This is intentionally lightweight and
        tolerant so the UI can call it without crashing.
        """
        self._last_error = None
        self._lines_parsed = 0
        self.recent_events = []

        if self.raw_url:
            try:
                import requests
                r = requests.get(self.raw_url, timeout=10)
                r.raise_for_status()
                text = r.text
                lines = [l for l in text.splitlines() if l.strip()]
                self._lines_parsed = len(lines)

                # regexes for interface names and state keywords
                iface_re = re.compile(r"\b(?:GigabitEthernet|FastEthernet|TenGigabitEthernet|TenGigE|Ethernet|Port-channel|Po|Gi|Fa|Eth|Te)[^\s,;:]*\b", re.I)
                state_re = re.compile(r"\b(administratively down|administratively up|changed state to up|changed state to down|line protocol is down|line protocol is up|is down|is up|went down|went up|down|up)\b", re.I)
                dev_re = re.compile(r"\b([A-Za-z0-9_\-]+):\s")

                # Parse last 50 non-empty lines (newest first)
                for ln in lines[-50:][::-1]:
                    parts = ln.split()
                    ts = ""
                    if parts:
                        # try to pick a reasonable timestamp token
                        if re.match(r"\d{2}:\d{2}:\d{2}", parts[0]) or re.match(r"[A-Za-z]{3}\s+\d{1,2}", ln):
                            ts = parts[0]

                    # device detection: look for 'hostname:' pattern, else default
                    mdev = dev_re.search(ln)
                    device = mdev.group(1) if mdev else self.default_device

                    # interface detection
                    iface_m = iface_re.search(ln)
                    interface = iface_m.group(0) if iface_m else None

                    # state detection
                    state_m = state_re.search(ln)
                    state = state_m.group(0) if state_m else None
                    state_norm = state.lower() if state else None

                    # actionable heuristic: interface down (but not administratively down)
                    actionable = False
                    if interface and state_norm:
                        if "down" in state_norm and "administratively" not in state_norm:
                            actionable = True

                    mnemonic = ln[:160]

                    self.recent_events.append({
                        "ts": ts,
                        "device": device,
                        "mnemonic": mnemonic,
                        "interface": interface,
                        "state": state,
                        "actionable": actionable,
                    })
            except Exception as e:
                self._last_error = str(e)
                self._lines_parsed = 0
                self.recent_events = []

    def status(self) -> Dict[str, object]:
        """Return a small status summary used by the UI."""
        open_ifaces = []
        try:
            open_ifaces = [e.get("interface") for e in self.recent_events if e.get("interface")]
        except Exception:
            open_ifaces = []
        return {
            "last_error": self._last_error,
            "lines_parsed": self._lines_parsed,
            "open_interfaces": list(filter(None, open_ifaces)),
        }


__all__ = ["GitHubLogEngine"]
