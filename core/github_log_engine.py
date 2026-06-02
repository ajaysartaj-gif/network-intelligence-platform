import os
import subprocess
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


__all__ = ["GitHubLogEngine"]
