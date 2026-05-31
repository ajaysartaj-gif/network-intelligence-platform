"""
GitHub Log Engine — ingests router syslog from a GitHub repository.

This is the bridge for the pipeline:

    GNS3 Router  →  Local syslog server  →  GitHub repo  →  THIS ENGINE  →  AutonomousMonitor

The local syslog server (syslog_server.py) appends Cisco IOS syslog lines to
`network_audit.log` in the gns3-router-logs repo and pushes on every interface /
config event.  A cloud-hosted Streamlit app cannot SSH into the GNS3 lab, so it
reads those logs from GitHub's raw endpoint instead, parses them into anomaly
dicts, and hands them to the existing detect → approve → fix → verify pipeline.

Design notes
------------
* Pure HTTP read (raw.githubusercontent.com) — no GitHub token required for a
  public repo.  Set GNS3_LOG_GITHUB_TOKEN to use the authenticated API for a
  private repo.
* Stateful interface tracking: an interface that went *down* and later came back
  *up* is NOT reported as an anomaly.  Only interfaces whose latest observed
  state is down / administratively-down surface as actionable anomalies.
* Idempotent: returns the current set of open anomalies every poll.  The
  AutonomousMonitor already de-duplicates by `device:type` signature, so it is
  safe to call every cycle.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    REQUESTS_AVAILABLE = False


# ── Defaults (point at the user's repo; override via env) ─────────────────────
DEFAULT_RAW_URL = (
    "https://raw.githubusercontent.com/"
    "ajaysartaj-gif/gns3-router-logs/main/network_audit.log"
)
DEFAULT_DEVICE = "R1"  # used when a log line carries no hostname token


# ── Line parser ───────────────────────────────────────────────────────────────
# Example lines:
#   [2026-05-29 17:29:31] <189>21: *May 29 11:59:29.951: %LINK-5-CHANGED: Interface GigabitEthernet1/0, changed state to administratively down
#   [2026-05-30 18:11:17] <189>16: R2: *May 30 12:41:17.115: %LINEPROTO-5-UPDOWN: Line protocol on Interface Loopback0, changed state to up

_WRAPPER_RE = re.compile(
    r"^\[(?P<ingest>[^\]]+)\]\s+"        # [2026-05-29 17:29:31]
    r"<(?P<pri>\d+)>(?P<seq>\d+):\s+"    # <189>21:
    r"(?P<rest>.*)$"
)

# Optional "R2:" hostname, then "*Mon DD HH:MM:SS.mmm:", then the %MNEMONIC.
_BODY_RE = re.compile(
    r"^(?:(?P<host>[A-Za-z0-9_.\-]+):\s+)?"          # optional hostname
    r"(?:\*?[A-Za-z]{3}\s+\d+\s+[\d:.]+:\s+)?"        # optional *May 29 11:59:29.951:
    r"%(?P<facility>[A-Z0-9_]+)-(?P<sev>\d)-(?P<mnemonic>[A-Z0-9_]+):\s*"
    r"(?P<msg>.*)$"
)

_IFACE_RE = re.compile(r"[Ii]nterface\s+(?P<iface>[A-Za-z0-9/.\-]+)")


@dataclass
class ParsedEvent:
    raw: str
    ingest_ts: str
    seq: int
    device: str
    facility: str
    severity_num: int
    mnemonic: str
    message: str
    interface: Optional[str] = None
    state: Optional[str] = None  # "up" | "down" | "admin_down" | None

    @property
    def is_interface_event(self) -> bool:
        return self.interface is not None and self.state is not None

    @property
    def is_config_event(self) -> bool:
        return self.mnemonic == "CONFIG_I"


def parse_line(line: str, default_device: str = DEFAULT_DEVICE) -> Optional[ParsedEvent]:
    """Parse one log line into a ParsedEvent, or None if it doesn't match."""
    line = line.rstrip("\n")
    if not line.strip():
        return None

    m = _WRAPPER_RE.match(line)
    if not m:
        return None

    body = _BODY_RE.match(m.group("rest").strip())
    if not body:
        return None

    device = body.group("host") or default_device
    msg = body.group("msg").strip()

    interface = None
    state = None
    iface_m = _IFACE_RE.search(msg)
    if iface_m:
        interface = iface_m.group("iface")
        low = msg.lower()
        if "administratively down" in low:
            state = "admin_down"
        elif "changed state to down" in low or low.endswith("to down"):
            state = "down"
        elif "changed state to up" in low or low.endswith("to up"):
            state = "up"

    return ParsedEvent(
        raw=line,
        ingest_ts=m.group("ingest"),
        seq=int(m.group("seq")),
        device=device,
        facility=body.group("facility"),
        severity_num=int(body.group("sev")),
        mnemonic=body.group("mnemonic"),
        message=msg,
        interface=interface,
        state=state,
    )


# ── Engine ─────────────────────────────────────────────────────────────────────
class GitHubLogEngine:
    """
    Fetches and parses router syslog from a GitHub repo, tracks interface state,
    and produces actionable anomaly dicts for the AutonomousMonitor.
    """

    def __init__(
        self,
        raw_url: Optional[str] = None,
        default_device: Optional[str] = None,
        timeout: int = 15,
    ):
        self.raw_url = raw_url or os.environ.get("GNS3_LOG_GITHUB_URL", DEFAULT_RAW_URL)
        self.default_device = default_device or os.environ.get(
            "GNS3_LOG_DEFAULT_DEVICE", DEFAULT_DEVICE
        )
        self.token = os.environ.get("GNS3_LOG_GITHUB_TOKEN", "").strip()
        self.timeout = timeout

        # (device, interface) → latest state ("up" | "down" | "admin_down")
        self._iface_state: Dict[Tuple[str, str], str] = {}
        # every device hostname ever seen in the log (e.g. R1, R2)
        self._devices_seen: set = set()
        # rolling feed of recently parsed events (newest first), for the UI
        self.recent_events: List[Dict[str, Any]] = []
        self._recent_actionable: List[Dict[str, Any]] = []
        self.last_poll_ts: Optional[str] = None
        self.last_error: Optional[str] = None
        self.total_lines_seen: int = 0

    # ── fetch ────────────────────────────────────────────────────────────────
    def _raw_to_api_url(self) -> Optional[str]:
        """Convert a raw.githubusercontent.com URL to the GitHub Contents API URL.
        The API is NOT served through the ~5-min CDN cache that makes raw URLs
        return stale logs, so it reflects new commits almost immediately."""
        m = re.match(
            r"https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)",
            self.raw_url or "",
        )
        if not m:
            return None
        owner, repo, branch, path = m.groups()
        return (f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
                f"?ref={branch}")

    def _fetch_raw(self) -> Optional[str]:
        if not REQUESTS_AVAILABLE:
            self.last_error = "requests library not available"
            return None

        # 1. Preferred: GitHub Contents API (uncached → no stale-log delay).
        api_url = self._raw_to_api_url()
        if api_url:
            try:
                headers = {
                    "Accept": "application/vnd.github.raw+json",
                    "Cache-Control": "no-cache",
                }
                if self.token:
                    headers["Authorization"] = f"token {self.token}"
                resp = requests.get(api_url, headers=headers, timeout=self.timeout)
                if resp.status_code == 200:
                    self.last_error = None
                    return resp.text
                # 403 with no token = rate-limited; fall through to raw.
            except Exception as e:
                logger.debug(f"[GITHUB-LOG] API fetch failed, falling back: {e}")

        # 2. Fallback: raw URL with a cache-busting query param.
        try:
            import time as _t
            bust = f"{'&' if '?' in self.raw_url else '?'}_cb={int(_t.time())}"
            headers = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
            if self.token:
                headers["Authorization"] = f"token {self.token}"
            resp = requests.get(self.raw_url + bust, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            self.last_error = None
            return resp.text
        except Exception as e:
            self.last_error = str(e)
            logger.debug(f"[GITHUB-LOG] fetch failed: {e}")
            return None

    # ── public API ─────────────────────────────────────────────────────────────
    def poll(self) -> List[Dict[str, Any]]:
        """
        Fetch the log, update interface state, and return the list of currently
        OPEN anomalies (interfaces that are down / admin-down right now).
        """
        text = self._fetch_raw()
        self.last_poll_ts = datetime.utcnow().isoformat()
        if text is None:
            return self._current_anomalies()

        events: List[ParsedEvent] = []
        for line in text.splitlines():
            ev = parse_line(line, self.default_device)
            if ev:
                events.append(ev)

        self.total_lines_seen = len(events)

        # Replay events in order to reconstruct current interface state.
        self._iface_state.clear()
        self._devices_seen.clear()
        self._recent_actionable = []
        # Mnemonics worth surfacing (neighbor flaps, hardware, high CPU, etc.).
        # These are diagnostic-class anomalies (operator visibility), not
        # auto-fixed unless a known safe remedy exists.
        NOTABLE = {
            "OSPF": ("ospf_event", "high"),
            "BGP": ("bgp_event", "high"),
            "DUAL": ("eigrp_event", "high"),       # EIGRP neighbor change
            "SYS-2": ("system_critical", "high"),
            "SYS-3": ("system_error", "medium"),
            "CPU": ("high_cpu", "high"),
            "OSPF_ADJ": ("ospf_adjacency", "high"),
        }
        for ev in events:
            self._devices_seen.add(ev.device)
            if ev.is_interface_event:
                self._iface_state[(ev.device, ev.interface)] = ev.state
                continue
            # Flag other notable syslog by facility/mnemonic keyword.
            tag = None
            for key, (atype, sev) in NOTABLE.items():
                if key in ev.facility or key in ev.mnemonic or key in f"{ev.facility}-{ev.severity_num}":
                    tag = (atype, sev)
                    break
            # Also treat any severity 0-2 (emerg/alert/crit) as notable.
            if tag is None and ev.severity_num <= 2 and ev.mnemonic != "CONFIG_I":
                tag = ("critical_syslog", "high")
            if tag:
                atype, sev = tag
                self._recent_actionable.append({
                    "device": ev.device,
                    "type": atype,
                    "severity": sev,
                    "description": f"{ev.facility}-{ev.severity_num}-{ev.mnemonic}: {ev.message[:120]}",
                    "interface": ev.interface or "",
                    "state": ev.state or "",
                    "source": "github_syslog",
                    "diagnostic_only": True,   # no canned fix; AI/operator handles
                })
        # De-duplicate actionable events by (device,type,description).
        seen = set()
        uniq = []
        for a in self._recent_actionable:
            k = (a["device"], a["type"], a["description"])
            if k not in seen:
                seen.add(k); uniq.append(a)
        self._recent_actionable = uniq[-10:]   # cap

        # Build the UI feed (newest first, capped).
        self.recent_events = [
            {
                "ts": ev.ingest_ts,
                "device": ev.device,
                "mnemonic": f"%{ev.facility}-{ev.severity_num}-{ev.mnemonic}",
                "interface": ev.interface,
                "state": ev.state,
                "message": ev.message,
                "actionable": bool(ev.interface and ev.state in ("down", "admin_down")),
            }
            for ev in reversed(events)
        ][:50]

        return self._current_anomalies()

    def _current_anomalies(self) -> List[Dict[str, Any]]:
        """Translate currently-down interfaces into anomaly dicts."""
        anomalies: List[Dict[str, Any]] = []
        for (device, iface), state in self._iface_state.items():
            if state not in ("down", "admin_down"):
                continue
            if state == "admin_down":
                desc = f"Interface {iface} on {device} was administratively shut down"
            else:
                desc = f"Interface {iface} on {device} is down (line protocol down)"
            anomalies.append({
                "device": device,
                "type": "interface_down",
                "severity": "high",
                "description": desc,
                "interface": iface,
                "state": state,
                "source": "github_syslog",
            })

        # Other actionable syslog events (neighbor flaps, high CPU, etc.).
        # These are surfaced as anomalies so the operator sees them; they are
        # diagnostic-class (no auto-fix command) unless a known remedy exists.
        for ev in getattr(self, "_recent_actionable", []):
            anomalies.append(ev)
        return anomalies

    # ── helpers for the UI ───────────────────────────────────────────────────
    def get_device_health(self) -> Dict[str, Dict[str, Any]]:
        """
        Return real devices seen in the log with their current health, derived
        purely from syslog. Used to populate the dashboard with live routers
        (e.g. R1, R2) instead of simulated devices.
        """
        health: Dict[str, Dict[str, Any]] = {}
        for device in sorted(self._devices_seen):
            down = [
                iface for (d, iface), s in self._iface_state.items()
                if d == device and s in ("down", "admin_down")
            ]
            health[device] = {
                "reachable": True,            # syslog reaching us implies the device is alive
                "down_interfaces": down,
                "interface_errors": len(down),
            }
        return health

    def status(self) -> Dict[str, Any]:
        open_ifaces = [
            f"{d}:{i} ({s})"
            for (d, i), s in self._iface_state.items()
            if s in ("down", "admin_down")
        ]
        return {
            "source_url": self.raw_url,
            "last_poll": self.last_poll_ts,
            "last_error": self.last_error,
            "lines_parsed": self.total_lines_seen,
            "open_interfaces": open_ifaces,
            "authenticated": bool(self.token),
        }


# ── self-test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    engine = GitHubLogEngine()
    anomalies = engine.poll()
    print("STATUS:", engine.status())
    print(f"\n{len(engine.recent_events)} events parsed; "
          f"{len(anomalies)} open anomalies:\n")
    for a in anomalies:
        print(" •", a["device"], a["interface"], "→", a["state"], "—", a["description"])
    if not anomalies:
        print(" (no interfaces currently down — all recovered)")
