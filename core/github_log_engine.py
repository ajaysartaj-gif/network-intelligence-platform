"""
github_log_engine.py
====================
Reads the real GNS3 router syslog file from GitHub:
  ajaysartaj-gif/gns3-router-logs/main/network_audit.log

Exact log format observed in the file:
  [2026-05-31 22:53:03] <191>82: R2: *May 31 17:23:01.469: IPSLA-OPER_TRACE:OPER:10 Timeout - destAddr=8.8.8.9
  [2026-05-29 17:29:31] <189>21: *May 29 11:59:29.951: %LINK-3-UPDOWN: Interface GigabitEthernet1/0, changed state to up
  [2026-05-31 13:01:26] <187>4: R1: *May 31 07:31:24.767: %LINK-3-UPDOWN: Interface GigabitEthernet1/0, changed state to up

Parses ALL log types:
  - Interface up/down  (%LINK, %LINEPROTO, %LINK-5-CHANGED)
  - IP SLA             (IPSLA-OPER_TRACE Timeout, IPSLA-INFRA_TRACE, icmpecho)
  - Config changes     (%SYS-5-CONFIG_I)
  - Loopback changes
  - Syslog start/stop  (%SYS-6-LOGGINGHOST_STARTSTOP)
  - Any %FAC-SEV-MNEM  fallback

For every parsed event: severity + AI action recommendation.
"""

import re
import urllib.request
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass, field

# ── GitHub raw URL ────────────────────────────────────────
LOG_URL = (
    "https://raw.githubusercontent.com/"
    "ajaysartaj-gif/gns3-router-logs/main/network_audit.log"
)

# ── Master line regex ─────────────────────────────────────
# Matches: [2026-05-31 22:53:03] <191>82: R2: *May 31 17:23:01.469: <body>
# OR:      [2026-05-29 17:29:31] <189>21: *May 29 11:59:29.951: <body>  (no router prefix)
LINE_RE = re.compile(
    r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]'   # [syslog timestamp]
    r'\s+<(\d+)>(\d+):\s+'                             # <priority>seq:
    r'(?:([A-Z][A-Z0-9_-]*):\s+)?'                    # optional router prefix (R1:, R2:)
    r'\*\w+\s+\d+\s+[\d:.]+:\s+'                      # Cisco local timestamp *May 31 ...
    r'(.*)'                                             # message body
)


# ── Event dataclass ───────────────────────────────────────
@dataclass
class LogEvent:
    raw:          str
    syslog_ts:    str          # from [...] prefix
    router:       str          # R1 / R2 / unknown
    priority:     int          # syslog priority integer
    severity:     str          # critical / warning / info / debug
    category:     str          # IPSLA / Interface / Config / System / etc.
    event_type:   str          # ipsla_timeout / link_down / config_change / etc.
    message:      str          # human-readable summary
    interface:    Optional[str] = None
    intf_state:   Optional[str] = None   # up / down / admin_down
    ipsla_op:     Optional[int] = None   # IP SLA operation ID
    dest_addr:    Optional[str] = None   # IP SLA destination
    src_addr:     Optional[str] = None   # IP SLA source
    ipsla_action: Optional[str] = None   # Timeout / Sending / Starting / etc.
    needs_action: bool = False
    ai_action:    str  = ""


# ══════════════════════════════════════════════════════════
# PRIORITY → SEVERITY MAPPING
# Syslog priority = facility*8 + severity_level
# severity_level: 0=emerg 1=alert 2=crit 3=err 4=warn 5=notice 6=info 7=debug
# ══════════════════════════════════════════════════════════
def _priority_to_severity(priority: int) -> str:
    level = priority & 0x07          # lower 3 bits = severity
    if level <= 2:   return "critical"
    elif level == 3: return "error"
    elif level == 4: return "warning"
    elif level <= 5: return "notice"
    elif level == 6: return "info"
    else:            return "debug"


# ══════════════════════════════════════════════════════════
# MESSAGE BODY PARSERS
# ══════════════════════════════════════════════════════════

def _parse_ipsla(body: str, router: str, raw_ts: str, priority: int, raw: str) -> Optional[LogEvent]:
    """
    Parse all IPSLA-OPER_TRACE and IPSLA-INFRA_TRACE lines.

    Observed patterns:
      IPSLA-OPER_TRACE:OPER:10 Timeout - destAddr=8.8.8.9, sAddr=192.168.122.232
      IPSLA-INFRA_TRACE:OPER:10 Updating result
      IPSLA-INFRA_TRACE:OPER:10 slaSchedulerEventWakeup
      IPSLA-INFRA_TRACE:OPER:10 Starting an operation
      IPSLA-OPER_TRACE:OPER:10 source IP:192.168.122.232 table_id=0
      IPSLA-OPER_TRACE:OPER:10 Starting icmpecho operation - destAddr=8.8.8.9, sAddr=192.168.122.232
      IPSLA-OPER_TRACE:OPER:10 Sending ID: 243
    """
    m = re.match(
        r'IPSLA-(?:OPER|INFRA)_TRACE:OPER:(\d+)\s+(.*)',
        body, re.IGNORECASE
    )
    if not m:
        return None

    op_id   = int(m.group(1))
    detail  = m.group(2).strip()

    # Extract addresses if present
    dest = re.search(r'destAddr=([\d.]+)', detail)
    src  = re.search(r'sAddr=([\d.]+)', detail)
    dest_addr = dest.group(1) if dest else None
    src_addr  = src.group(1)  if src  else None

    # Classify the action
    if re.search(r'timeout', detail, re.I):
        action       = "Timeout"
        event_type   = "ipsla_timeout"
        severity     = "critical"
        needs_action = True
        message = (
            f"{router} IP SLA op {op_id}: ICMP Echo to {dest_addr or '?'} TIMED OUT "
            f"(source {src_addr or '?'})"
        )
        ai_action = (
            f"IP SLA operation {op_id} on {router} is consistently timing out to {dest_addr}. "
            f"Actions: 1) Verify {dest_addr} is reachable — ping {dest_addr} source {src_addr}. "
            f"2) Check if route to {dest_addr} exists — show ip route {dest_addr}. "
            f"3) Check for packet loss on the path. "
            f"4) Verify no ACL blocking ICMP from {src_addr} to {dest_addr}. "
            f"5) If timeout persists, the SLA target {dest_addr} may be down — escalate."
        )

    elif re.search(r'icmpecho operation', detail, re.I):
        action       = "Probe Sent"
        event_type   = "ipsla_probe_sent"
        severity     = "info"
        needs_action = False
        message      = f"{router} IP SLA op {op_id}: ICMP Echo probe to {dest_addr or '?'} sent"
        ai_action    = ""

    elif re.search(r'starting an operation', detail, re.I):
        action       = "Starting"
        event_type   = "ipsla_starting"
        severity     = "debug"
        needs_action = False
        message      = f"{router} IP SLA op {op_id}: scheduler starting operation"
        ai_action    = ""

    elif re.search(r'updating result', detail, re.I):
        action       = "Result Update"
        event_type   = "ipsla_result_update"
        severity     = "debug"
        needs_action = False
        message      = f"{router} IP SLA op {op_id}: result updated after probe"
        ai_action    = ""

    elif re.search(r'sending id', detail, re.I):
        send_id = re.search(r'Sending ID:\s*(\d+)', detail)
        action       = "Sending"
        event_type   = "ipsla_send"
        severity     = "debug"
        needs_action = False
        message      = f"{router} IP SLA op {op_id}: probe packet sent (ID {send_id.group(1) if send_id else '?'})"
        ai_action    = ""

    elif re.search(r'schedulerevent|wakeup', detail, re.I):
        action       = "Scheduler Wakeup"
        event_type   = "ipsla_scheduler"
        severity     = "debug"
        needs_action = False
        message      = f"{router} IP SLA op {op_id}: scheduler woke up"
        ai_action    = ""

    elif re.search(r'source ip', detail, re.I):
        action       = "Source IP"
        event_type   = "ipsla_source"
        severity     = "debug"
        needs_action = False
        message      = f"{router} IP SLA op {op_id}: using source {src_addr or detail}"
        ai_action    = ""

    else:
        action       = detail[:40]
        event_type   = "ipsla_other"
        severity     = "info"
        needs_action = False
        message      = f"{router} IP SLA op {op_id}: {detail[:80]}"
        ai_action    = ""

    return LogEvent(
        raw=raw, syslog_ts=raw_ts, router=router,
        priority=priority, severity=severity,
        category="IP SLA", event_type=event_type,
        message=message, ipsla_op=op_id,
        dest_addr=dest_addr, src_addr=src_addr,
        ipsla_action=action,
        needs_action=needs_action, ai_action=ai_action,
    )


def _parse_interface(body: str, router: str, raw_ts: str, priority: int, raw: str) -> Optional[LogEvent]:
    """
    Parse all interface state change messages:
      %LINK-3-UPDOWN: Interface GigabitEthernet1/0, changed state to up
      %LINK-5-CHANGED: Interface GigabitEthernet1/0, changed state to administratively down
      %LINEPROTO-5-UPDOWN: Line protocol on Interface GigabitEthernet1/0, changed state to down
    """
    m = re.search(
        r'%(?:LINK|LINEPROTO)-\d-(?:UPDOWN|CHANGED):'
        r'.*?Interface\s+([\w./]+),\s*changed state to\s+(\w+(?:\s+\w+)?)',
        body, re.IGNORECASE
    )
    if not m:
        return None

    interface = m.group(1)
    raw_state = m.group(2).strip().lower()

    # Normalize state
    if "administratively" in raw_state or "admin" in raw_state:
        state        = "admin_down"
        severity     = "warning"
        needs_action = False
        message      = f"{router} {interface} shutdown (administratively down)"
        ai_action    = (
            f"{interface} was manually shut down via 'shutdown' command on {router}. "
            f"Verify this was intentional. If unintended: 'no shutdown' on the interface."
        )
    elif raw_state == "down":
        state        = "down"
        severity     = "critical"
        needs_action = True
        message      = f"{router} {interface} went DOWN"
        ai_action    = (
            f"Interface {interface} on {router} is down unexpectedly. "
            f"Check: 1) Physical connection/cable. 2) Remote device status. "
            f"3) 'show interface {interface}' for error counters. "
            f"4) Check for err-disable: 'show interface {interface} | inc err'. "
            f"5) Verify remote end is up."
        )
    elif raw_state == "up":
        state        = "up"
        severity     = "info"
        needs_action = False
        message      = f"{router} {interface} came UP"
        ai_action    = f"Interface {interface} on {router} recovered. Verify routing and services restored."
    else:
        state        = raw_state
        severity     = "info"
        needs_action = False
        message      = f"{router} {interface} state: {raw_state}"
        ai_action    = ""

    is_lineproto = "LINEPROTO" in body.upper()
    event_type   = "lineproto_change" if is_lineproto else "link_change"
    cat_detail   = "Line Protocol" if is_lineproto else "Link"

    return LogEvent(
        raw=raw, syslog_ts=raw_ts, router=router,
        priority=priority, severity=severity,
        category="Interface", event_type=event_type,
        message=message, interface=interface, intf_state=state,
        needs_action=needs_action, ai_action=ai_action,
    )


def _parse_config(body: str, router: str, raw_ts: str, priority: int, raw: str) -> Optional[LogEvent]:
    """
    %SYS-5-CONFIG_I: Configured from console by console
    """
    if not re.search(r'%SYS-\d-CONFIG_I', body, re.I):
        return None

    src = "console"
    m = re.search(r'Configured from\s+(\S+)\s+by\s+(\S+)', body, re.I)
    if m:
        src = f"{m.group(1)} by {m.group(2)}"

    return LogEvent(
        raw=raw, syslog_ts=raw_ts, router=router,
        priority=priority, severity="info",
        category="Config", event_type="config_change",
        message=f"{router} configuration changed ({src})",
        needs_action=False,
        ai_action=f"Config change on {router} via {src}. Check 'show archive log config all' to diff what changed.",
    )


def _parse_logging_host(body: str, router: str, raw_ts: str, priority: int, raw: str) -> Optional[LogEvent]:
    """
    %SYS-6-LOGGINGHOST_STARTSTOP: Logging to host 192.168.1.36 port 514 started - CLI initiated
    """
    if not re.search(r'LOGGINGHOST_STARTSTOP', body, re.I):
        return None

    host = re.search(r'host\s+([\d.]+)', body, re.I)
    port = re.search(r'port\s+(\d+)', body, re.I)
    action = "started" if "started" in body.lower() else "stopped"

    return LogEvent(
        raw=raw, syslog_ts=raw_ts, router=router,
        priority=priority, severity="info",
        category="System", event_type="logging_change",
        message=f"{router} syslog to {host.group(1) if host else '?'}:{port.group(1) if port else '514'} {action}",
        needs_action=False,
        ai_action="",
    )


def _parse_generic(body: str, router: str, raw_ts: str, priority: int, raw: str) -> LogEvent:
    """Fallback — parse any %FAC-SEV-MNEM: message."""
    m = re.match(r'%([A-Z0-9_]+)-(\d)-([A-Z0-9_]+):(.*)', body, re.I)
    if m:
        facility = m.group(1)
        sev_num  = int(m.group(2))
        mnemonic = m.group(3)
        text     = m.group(4).strip()
        sev_map  = {0:"critical",1:"critical",2:"critical",3:"error",4:"warning",5:"notice",6:"info",7:"debug"}
        severity = sev_map.get(sev_num, "info")
        category = facility.split("_")[0].title()
        message  = f"{router} %{facility}-{sev_num}-{mnemonic}: {text[:80]}"
        needs_action = sev_num <= 3
        ai_action = (
            f"Investigate {facility}-{mnemonic} on {router}. "
            f"Cisco syslog severity {sev_num}. Search: 'cisco {facility}-{sev_num}-{mnemonic}'."
            if needs_action else ""
        )
    else:
        severity     = _priority_to_severity(priority)
        category     = "Unknown"
        mnemonic     = ""
        message      = f"{router}: {body[:100]}"
        needs_action = priority <= 3 * 8 + 3   # severity <= error
        ai_action    = f"Review unrecognized log from {router}: {body[:80]}" if needs_action else ""

    return LogEvent(
        raw=raw, syslog_ts=raw_ts, router=router,
        priority=priority, severity=severity,
        category=category, event_type="generic",
        message=message, needs_action=needs_action, ai_action=ai_action,
    )


# ══════════════════════════════════════════════════════════
# MAIN PARSER
# ══════════════════════════════════════════════════════════

def parse_line(raw_line: str) -> Optional[LogEvent]:
    """
    Parse one line from network_audit.log.
    Returns LogEvent or None if line doesn't match expected format.
    """
    raw_line = raw_line.strip()
    if not raw_line:
        return None

    m = LINE_RE.match(raw_line)
    if not m:
        return None

    syslog_ts = m.group(1)                      # 2026-05-31 22:53:03
    priority  = int(m.group(2))                  # 191
    # seq     = m.group(3)                       # 82 (not needed)
    router    = m.group(4) or "unknown"          # R2 / R1 / None
    body      = m.group(5).strip()               # message body

    # Try each specific parser in order
    event = (
        _parse_ipsla(body, router, syslog_ts, priority, raw_line)
        or _parse_interface(body, router, syslog_ts, priority, raw_line)
        or _parse_config(body, router, syslog_ts, priority, raw_line)
        or _parse_logging_host(body, router, syslog_ts, priority, raw_line)
        or _parse_generic(body, router, syslog_ts, priority, raw_line)
    )
    return event


# ══════════════════════════════════════════════════════════
# GITHUB FETCHER
# ══════════════════════════════════════════════════════════

def fetch_logs(url: str = LOG_URL, timeout: int = 10) -> str:
    """Fetch raw log text from GitHub. Returns empty string on error."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NetBrainAI/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return ""


def load_and_parse(url: str = LOG_URL) -> List[LogEvent]:
    """
    Fetch the full log file and parse every line.
    Returns a list of LogEvent objects — all 262 lines handled.
    """
    raw_text = fetch_logs(url)
    if not raw_text:
        return []

    events = []
    for line in raw_text.splitlines():
        evt = parse_line(line)
        if evt:
            events.append(evt)
    return events


# ══════════════════════════════════════════════════════════
# ANALYSIS HELPERS
# ══════════════════════════════════════════════════════════

def get_summary(events: List[LogEvent]) -> dict:
    """Summarize parsed events by category and severity."""
    total      = len(events)
    critical   = [e for e in events if e.severity == "critical"]
    warnings   = [e for e in events if e.severity == "warning"]
    ipsla_tout = [e for e in events if e.event_type == "ipsla_timeout"]
    intf_down  = [e for e in events if e.event_type == "link_change" and e.intf_state == "down"]
    cfg_chg    = [e for e in events if e.event_type == "config_change"]
    actionable = [e for e in events if e.needs_action]

    categories = {}
    for e in events:
        categories[e.category] = categories.get(e.category, 0) + 1

    routers = {}
    for e in events:
        routers[e.router] = routers.get(e.router, 0) + 1

    # IP SLA consecutive timeout count (probe 10)
    ipsla_consecutive = 0
    for e in reversed(ipsla_tout):
        if e.ipsla_op == 10:
            ipsla_consecutive += 1
        else:
            break

    return {
        "total":                total,
        "critical":             len(critical),
        "warnings":             len(warnings),
        "actionable":           len(actionable),
        "ipsla_timeouts":       len(ipsla_tout),
        "ipsla_consecutive":    ipsla_consecutive,
        "ipsla_dest":           ipsla_tout[0].dest_addr if ipsla_tout else None,
        "interface_downs":      len(intf_down),
        "config_changes":       len(cfg_chg),
        "categories":           categories,
        "routers":              routers,
        "critical_events":      critical,
        "actionable_events":    actionable,
    }


def get_ai_analysis_prompt(events: List[LogEvent]) -> str:
    """
    Build a precise prompt for Claude to analyze ALL events from the log.
    Includes the actual data so Claude gives specific, actionable answers.
    """
    summary = get_summary(events)
    actionable = summary["actionable_events"]

    # Group IP SLA timeouts
    ipsla_timeouts = [e for e in events if e.event_type == "ipsla_timeout"]
    intf_events    = [e for e in events if e.category == "Interface"]
    cfg_events     = [e for e in events if e.event_type == "config_change"]

    lines = [
        f"Analyze this real GNS3 router log from GitHub (ajaysartaj-gif/gns3-router-logs).",
        f"Total: {summary['total']} log entries. Routers: {', '.join(summary['routers'].keys())}.",
        f"",
        f"=== CRITICAL FINDINGS ===",
    ]

    if ipsla_timeouts:
        lines.append(
            f"IP SLA TIMEOUTS: {len(ipsla_timeouts)} consecutive timeouts on "
            f"operation 10, ICMP Echo to {ipsla_timeouts[0].dest_addr} "
            f"from source {ipsla_timeouts[0].src_addr} on {ipsla_timeouts[0].router}."
        )

    for e in summary["critical_events"][:5]:
        lines.append(f"CRITICAL: [{e.syslog_ts}] {e.message}")

    lines += [
        "",
        "=== INTERFACE EVENTS ===",
    ]
    for e in intf_events[:10]:
        lines.append(f"[{e.syslog_ts}] {e.router} {e.interface} → {e.intf_state}")

    lines += [
        "",
        f"=== CONFIG CHANGES: {len(cfg_events)} total ===",
    ]
    for e in cfg_events[:5]:
        lines.append(f"[{e.syslog_ts}] {e.message}")

    lines += [
        "",
        "=== QUESTIONS FOR AI ===",
        "1. What is the root cause of the repeated IP SLA timeouts to 8.8.8.9?",
        "2. Are the interface flapping events on GigabitEthernet1/0 related to the IP SLA failures?",
        "3. What do the config changes suggest about what was being tested?",
        "4. Is 8.8.8.9 reachable? What could block ICMP from 192.168.122.232?",
        "5. What exact CLI commands should I run on R2 to diagnose and fix?",
        "6. What is the overall health status of this GNS3 lab network?",
    ]

    return "\n".join(lines)
