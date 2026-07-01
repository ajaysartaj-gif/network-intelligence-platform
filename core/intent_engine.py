"""
core/intent_engine.py
=====================
NetBrain AI — Enterprise Network Intent Engine
-----------------------------------------------
Converts plain-English operator requests into autonomous network actions.

Pipeline:
  1. classify_intent()   — understand WHAT the operator wants
  2. plan_diagnostics()  — decide WHICH commands to run on WHICH devices
  3. execute_plan()      — SSH to devices, collect real output
  4. analyze_results()   — AI root-cause analysis on real data
  5. propose_fix()       — if config change needed, generate commands + rollback

Supports enterprise scenarios:
  - Reachability failures (ping, trace, path analysis)
  - Routing protocol issues (OSPF, BGP, EIGRP, static)
  - Interface / physical layer problems
  - ACL / firewall blocking
  - Performance issues (CPU, memory, bandwidth, QoS)
  - VLAN / STP / switching problems
  - DHCP / DNS / NTP service failures
  - Multi-device topology correlation

Usage from app.py:
  from core.intent_engine import IntentEngine
  engine = IntentEngine(call_ai_fn, approved_devices)
  result = engine.handle(user_query, target_device)
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("NetBrain.IntentEngine")

# ── Optional Netmiko ──────────────────────────────────────────────────────────
try:
    from netmiko import ConnectHandler
    NETMIKO_OK = True
except ImportError:
    NETMIKO_OK = False

# ── Knowledge & Verification layers (Phases 1-4) ──────────────────────────────
try:
    from core.knowledge import (
        CitationTracker,
        ConfidenceLevel,
        KnowledgeEntry,
        detect_vendor,
        detect_platform,
        get_orchestrator,
    )
    from core.verification import (
        DeviceVersion,
        parse_show_version,
        get_validator,
    )
    KNOWLEDGE_OK = True
except ImportError as _ki:
    logger.warning(f"Knowledge layer unavailable: {_ki}")
    KNOWLEDGE_OK = False


# ═══════════════════════════════════════════════════════════════════════════════
# Intent categories
# ═══════════════════════════════════════════════════════════════════════════════

INTENT_DIAGNOSTIC   = "diagnostic"    # read-only: show, ping, trace, why, check
INTENT_CONFIG       = "config"        # change: add, remove, enable, configure
INTENT_CONCEPT      = "concept"       # explain, what is, how does
INTENT_REACHABILITY = "reachability"  # can X reach Y, path analysis


# Keyword maps for local intent classification (fast pre-check before AI)
_DIAGNOSTIC_KEYWORDS = {
    "why", "check", "verify", "show", "status", "debug", "diagnose",
    "health", "down", "up", "issue", "problem", "not working", "failing",
    "stuck", "flapping", "ospf", "bgp", "eigrp", "interface", "neighbor",
    "adjacency", "session", "route", "error", "drop", "loss", "latency",
    "cpu", "memory", "log", "syslog", "what", "is there", "are there",
}

_REACHABILITY_KEYWORDS = {
    "reach", "ping", "traceroute", "trace", "path", "connectivity",
    "can't connect", "cannot connect", "unreachable", "no route",
    "between", "from", "to", "source", "destination",
}

_CONFIG_KEYWORDS = {
    "configure", "config", "add", "remove", "delete", "enable", "disable",
    "set", "fix", "apply", "deploy", "change", "update", "modify",
    "redistribute", "advertise", "block", "allow", "permit", "deny",
    "create", "shut", "no shut", "shutdown", "restart", "clear",
}

_CONCEPT_KEYWORDS = {
    "explain", "what is", "how does", "what does", "tell me about",
    "describe", "difference between", "meaning of",
}


# ═══════════════════════════════════════════════════════════════════════════════
# NO static command library — AI generates all commands dynamically.
# The AI reasons about each question from scratch and decides which commands
# to run based on its CCIE-level knowledge of the protocol/issue at hand.
# This is the difference between an if-else lookup and real intelligence.
# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DeviceResult:
    """SSH output collected from one device."""
    ip: str
    hostname: str
    commands_run: List[str] = field(default_factory=list)
    outputs: Dict[str, str] = field(default_factory=dict)   # cmd → output
    error: Optional[str] = None
    connected: bool = False


@dataclass
class DiagnosticPlan:
    """An AI-generated plan listing what will run on which devices, awaiting human approval."""
    reasoning: str = ""                              # WHY these commands
    commands_per_device: Dict[str, List[str]] = field(default_factory=dict)  # ip → cmd list
    hypothesis: str = ""                             # AI's current hypothesis
    expected_outcome: str = ""                       # What AI expects to find
    query: str = ""
    devices: List[Dict[str, str]] = field(default_factory=list)  # [{ip, hostname, type}]
    round_index: int = 1                             # agentic diagnostic round (1-based)


@dataclass
class IntentResult:
    """Full result from one intent cycle."""
    intent: str                          # diagnostic / config / concept / reachability
    scenario: str                        # ospf / bgp / reachability / general …
    query: str
    device_results: List[DeviceResult] = field(default_factory=list)
    analysis: str = ""                   # AI root-cause analysis
    fix_commands: List[str] = field(default_factory=list)    # [CONFIG]/[EXEC] tagged (merged, legacy)
    commands_per_device: Dict[str, List[str]] = field(default_factory=dict)  # ip -> tagged cmds (grounded per device)
    verify_commands: List[str] = field(default_factory=list)  # post-deploy checks (e.g. show ip ospf neighbor)
    fix_explanation: str = ""
    rollback_commands: List[str] = field(default_factory=list)
    needs_approval: bool = False
    plain_answer: str = ""               # for concept questions
    plan: Optional[DiagnosticPlan] = None      # plan awaiting human approval
    plan_pending: bool = False                 # True when waiting for human
    next_plan: Optional[DiagnosticPlan] = None  # agentic follow-up round, awaiting approval
    needs_followup: bool = False               # True when the analysis was inconclusive
    round_index: int = 1                       # which diagnostic round produced this result
    max_rounds: int = 4                        # cap on autonomous diagnostic rounds
    trace: List[Dict[str, Any]] = field(default_factory=list)  # per-round autonomous reasoning trace
    autonomous: bool = False                   # produced by the autonomous loop
    applied: bool = False                      # fix was auto-applied
    verified: bool = False                     # post-fix verification passed
    reverted: bool = False                     # auto-rolled back after failed verify
    citations_md: str = ""                     # rendered citation block (markdown)
    validation_md: str = ""                    # rendered command validation block
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# Intent Engine
# ═══════════════════════════════════════════════════════════════════════════════

class IntentEngine:
    """
    Enterprise network intent engine.
    Accepts plain-English queries, autonomously runs diagnostics via SSH,
    and returns AI-powered root-cause analysis + fix recommendations.
    """

    def __init__(
        self,
        ai_call: Callable[[str], str],
        approved_devices: Optional[List[Any]] = None,   # DiscoveredDevice list
    ):
        self.ai_call = ai_call
        self.approved_devices = approved_devices or []

    # ── Public entry point ────────────────────────────────────────────────────

    def propose_plan(
        self,
        query: str,
        devices: List[Any],
        session_output: str = "",
        session_diagnosis: str = "",
    ) -> IntentResult:
        """
        STAGE 1: AI thinks about the question and proposes a diagnostic plan.
        Returns IntentResult with plan_pending=True. NO commands are executed.

        The human reviews the plan and then calls execute_plan() to proceed.
        """
        query = (query or "").strip()
        if not query:
            r = IntentResult(intent="concept", scenario="general", query=query)
            r.plain_answer = "Please ask a question."
            return r

        intent, scenario = self._classify(query)
        result = IntentResult(intent=intent, scenario=scenario, query=query)

        try:
            # Concept questions don't need a plan — answer directly
            if intent == INTENT_CONCEPT:
                result.plain_answer = self._answer_concept(query)
                return result

            # Config requests need approval too, but for config commands not diagnostics
            if intent == INTENT_CONFIG:
                primary = devices[0] if devices else None
                self._handle_config(result, query, primary, session_output,
                                    all_devices=devices)
                return result

            # DIAGNOSTIC / REACHABILITY — generate plan, do NOT execute
            plan = self._ai_generate_plan(query, devices, scenario,
                                          session_output, session_diagnosis)
            result.plan = plan
            result.plan_pending = True

            # ── Phase 1-3: Enrich plan with knowledge citations ─────────
            if KNOWLEDGE_OK and devices:
                try:
                    tracker = self._lookup_citations_for_plan(plan, devices)
                    result.citations_md = tracker.format_command_badges()
                except Exception as ce:
                    logger.debug(f"Citation lookup failed: {ce}")

        except Exception as exc:
            logger.error(f"[IntentEngine] propose_plan() error: {exc}", exc_info=True)
            result.error = str(exc)

        return result

    def execute_plan(
        self,
        plan: DiagnosticPlan,
        all_devices: List[Any],
    ) -> IntentResult:
        """
        STAGE 2: After human approves the plan, run commands and analyse.
        """
        # Rebuild scenario from plan
        intent, scenario = self._classify(plan.query)
        result = IntentResult(intent=intent, scenario=scenario, query=plan.query)
        result.plan = plan
        result.round_index = getattr(plan, "round_index", 1)

        try:
            # Map device IPs in the plan back to device objects
            ip_to_dev = {d.ip: d for d in all_devices}

            for ip, cmds in plan.commands_per_device.items():
                dev = ip_to_dev.get(ip)
                if not dev:
                    continue
                # DEFENSE-IN-DEPTH: never run debug/monitor/clear/reload/test, even
                # if one slipped into the plan. Diagnostics are show/display only.
                safe_cmds = [c for c in cmds if not self.is_dangerous(c)]
                blocked = [c for c in cmds if self.is_dangerous(c)]
                if blocked:
                    logger.warning("Blocked dangerous commands on %s: %s", ip, blocked)
                if not safe_cmds:
                    continue
                dr = self._ssh_collect(dev, safe_cmds)
                result.device_results.append(dr)

            # AI now does deep analysis with REAL output from ALL devices
            analysis_prompt = self._build_deep_analysis_prompt(plan, result)
            result.analysis = self.ai_call(analysis_prompt) or "AI unavailable."

            # ── Agentic decision: fix / next-round / done ────────────────────
            if "APPROVAL_REQUIRED" in result.analysis:
                result.needs_approval = True
                result.fix_commands, result.fix_explanation, result.rollback_commands = (
                    self._extract_fix_from_analysis(result.analysis)
                )
                result.analysis = result.analysis.split("APPROVAL_REQUIRED")[0].strip()

                # ── Phase 4: Validate fix commands before showing approval ──
                if KNOWLEDGE_OK and result.fix_commands and all_devices:
                    try:
                        result.validation_md = self._validate_fix_commands(
                            result.fix_commands, all_devices, result.device_results,
                        )
                    except Exception as ve:
                        logger.debug(f"Validation failed: {ve}")

            elif "NEXT_STEP_REQUIRED" in result.analysis:
                # inconclusive — keep going autonomously (approval-gated), up to max_rounds
                next_cmds = self._parse_next_commands(result.analysis, plan, all_devices)
                result.analysis = result.analysis.split("NEXT_STEP_REQUIRED")[0].strip()
                if result.round_index < result.max_rounds and next_cmds:
                    result.needs_followup = True
                    result.next_plan = self._build_followup_plan(plan, result, next_cmds)
                else:
                    result.analysis += (
                        f"\n\n⚠️ Reached the diagnostic round limit "
                        f"({result.max_rounds}) without a conclusive root cause. "
                        "Consider widening device scope or capturing `debug` output manually."
                        if result.round_index >= result.max_rounds else
                        "\n\n⚠️ The analysis was inconclusive but no concrete next command "
                        "could be derived. Please refine the question or add devices.")
            else:
                # DIAGNOSIS_COMPLETE (or untagged) — strip any stray tag text
                result.analysis = result.analysis.replace("DIAGNOSIS_COMPLETE", "").strip()

        except Exception as exc:
            logger.error(f"[IntentEngine] execute_plan() error: {exc}", exc_info=True)
            result.error = str(exc)

        return result

    # ── Agentic follow-up helpers ──────────────────────────────────────────────

    def _parse_next_commands(
        self,
        analysis: str,
        plan: DiagnosticPlan,
        all_devices: List[Any],
    ) -> Dict[str, List[str]]:
        """Parse [NEXT] (on <device>) <cmd> lines into {ip: [cmds]}.

        Maps the "(on R1)" token to a device IP by matching hostname or IP. A line
        with no recognizable device, or addressed to 'all', fans out to every
        device that was in the prior plan.
        """
        # name/ip → ip lookup from the devices we actually have
        name_to_ip: Dict[str, str] = {}
        for d in all_devices:
            ip = getattr(d, "ip", "")
            if ip:
                name_to_ip[ip.lower()] = ip
                hn = (getattr(d, "hostname", "") or "").lower()
                if hn:
                    name_to_ip[hn] = ip
        plan_ips = list(plan.commands_per_device.keys()) or [
            getattr(d, "ip", "") for d in all_devices if getattr(d, "ip", "")]

        out: Dict[str, List[str]] = {}
        for raw in analysis.splitlines():
            line = raw.strip()
            if "[NEXT]" not in line:
                continue
            body = line.split("[NEXT]", 1)[1].strip()
            target_ips = list(plan_ips)
            m = re.match(r"\(on\s+([^)]+)\)\s*(.*)", body, re.IGNORECASE)
            if m:
                tok = m.group(1).strip().lower()
                body = m.group(2).strip()
                if tok in ("all", "all devices", "every device"):
                    target_ips = list(plan_ips)
                elif tok in name_to_ip:
                    target_ips = [name_to_ip[tok]]
                else:
                    # token might be an ip substring or partial hostname
                    match = [ip for key, ip in name_to_ip.items() if tok in key]
                    target_ips = match or list(plan_ips)
            cmd = body.strip().strip("`").strip()
            if not cmd:
                continue
            for ip in target_ips:
                out.setdefault(ip, [])
                if cmd not in out[ip]:
                    out[ip].append(cmd)
        return out

    def _build_followup_plan(
        self,
        prior_plan: DiagnosticPlan,
        result: IntentResult,
        next_cmds: Dict[str, List[str]],
    ) -> DiagnosticPlan:
        """Wrap the parsed next-step commands into an approval-ready plan."""
        round_index = getattr(prior_plan, "round_index", 1) + 1
        # short hypothesis line lifted from the analysis (best-effort)
        hyp = ""
        for key in ("ROOT CAUSE", "Root cause", "INCONCLUSIVE", "hypothesis"):
            idx = result.analysis.find(key)
            if idx != -1:
                hyp = result.analysis[idx:idx + 200].split("\n")[0]
                break
        return DiagnosticPlan(
            reasoning=(f"Round {round_index}: the previous round was inconclusive. "
                       "Running targeted follow-up commands to distinguish the remaining "
                       "candidate root causes before proposing any fix."),
            commands_per_device=next_cmds,
            hypothesis=hyp or "Narrowing down the remaining candidate root causes.",
            expected_outcome=("These commands should expose the discriminating value "
                              "(e.g. an MTU or timer mismatch) that confirms the cause."),
            query=prior_plan.query,
            devices=prior_plan.devices,
            round_index=round_index,
        )

    def handle(
        self,
        query: str,
        primary_device: Optional[Any] = None,
        session_output: str = "",
        session_diagnosis: str = "",
    ) -> IntentResult:
        """
        Legacy single-stage entry. Use propose_plan() + execute_plan() instead
        for human-in-the-loop workflows.
        """
        query = (query or "").strip()
        if not query:
            result = IntentResult(intent="concept", scenario="general", query=query)
            result.plain_answer = "Please ask a question."
            return result

        intent, scenario = self._classify(query)
        result = IntentResult(intent=intent, scenario=scenario, query=query)

        try:
            if intent == INTENT_CONCEPT:
                result.plain_answer = self._answer_concept(query)

            elif intent == INTENT_CONFIG:
                self._handle_config(result, query, primary_device, session_output)

            else:
                self._handle_diagnostic(
                    result, query, primary_device,
                    session_output, session_diagnosis,
                )

        except Exception as exc:
            logger.error(f"[IntentEngine] handle() error: {exc}", exc_info=True)
            result.error = str(exc)

        return result

    # ── AI Plan generation ───────────────────────────────────────────────────

    def _ai_generate_plan(
        self,
        query: str,
        devices: List[Any],
        scenario: str,
        session_output: str,
        session_diagnosis: str,
    ) -> DiagnosticPlan:
        """
        Ask AI to think through the question and propose a diagnostic plan.
        AI reasons from scratch — no hardcoded command library.
        AI decides hypothesis, expected outcome, and exact commands per device.
        """
        dev_list_str = "\n".join(
            f"  - {d.hostname or d.ip}  IP={d.ip}  type={d.device_type}"
            for d in devices
        )

        # Optional prior session context (login output etc.)
        prior_ctx = ""
        if session_output:
            prior_ctx += f"\n\nPRIOR LOGIN OUTPUT (interfaces/routes/CDP):\n{session_output[:1500]}"
        if session_diagnosis:
            prior_ctx += f"\n\nPRIOR AI DIAGNOSIS:\n{session_diagnosis[:500]}"

        # ── RAG-FIRST grounding: your runbooks/incidents/topology BEFORE the LLM's priors ──
        grounding = self._ground(query, devices)
        if grounding:
            prior_ctx += "\n\n" + grounding

        plan_prompt = (
            "You are NetBrain AI — a CCIE-level network engineer (R&S, SP, Security, Data Center).\n"
            "You have deep knowledge of every Cisco IOS / IOS-XE / NX-OS / IOS-XR show command, "
            "including OSPF, BGP, EIGRP, IS-IS, MPLS, LDP, RSVP, VPLS, EVPN, VXLAN, GRE, IPSec, "
            "DMVPN, NAT, PAT, NAT-PT, QoS, STP, VTP, HSRP, VRRP, GLBP, AAA, ACLs, NetFlow, SNMP, "
            "and all hardware platform diagnostics.\n\n"

            "An operator has asked a network question. You must reason about the problem from "
            "FIRST PRINCIPLES and propose a diagnostic plan. There is NO predefined command library — "
            "you decide every command based on your own CCIE expertise.\n\n"

            f"OPERATOR QUESTION:\n{query}\n\n"
            f"SCOPE — devices selected by operator (only these can be touched):\n{dev_list_str}"
            f"{prior_ctx}\n\n"

            "THINK STEP BY STEP:\n"
            "1. What is the operator really asking? What's the protocol/feature/layer involved?\n"
            "2. What is your most likely hypothesis given the symptoms?\n"
            "3. What specific commands on which specific devices will prove or disprove it?\n"
            "4. If it's a protocol with peers (OSPF, BGP, EIGRP, IS-IS, LDP, HSRP, IPSec…) — "
            "   you MUST run commands on BOTH/ALL peers and compare. Single-device output is useless.\n"
            "5. For protocols/features you decide are involved, choose the MOST DIAGNOSTIC commands "
            "   for the symptom — not just generic 'show ip route'. For example: for IPSec phase-1 "
            "   failure, `show crypto isakmp sa` and `show crypto isakmp policy` matter more than "
            "   `show ip route`. For MPLS LDP, `show mpls ldp neighbor detail` matters more than "
            "   `show ip ospf`. Use your real CCIE judgment.\n"
            "6. Adapt to the device type (router/L3 switch/L2 switch/firewall) — use the right "
            "   command set for each platform.\n\n"

            "OUTPUT FORMAT (strict — no other text):\n\n"
            "--- HYPOTHESIS ---\n"
            "<1-2 sentence specific hypothesis about the root cause>\n\n"
            "--- REASONING ---\n"
            "<2-4 sentences: why these specific commands will reveal the root cause; mention which "
            "values/states you'll compare across devices>\n\n"
            "--- EXPECTED OUTCOME ---\n"
            "<what specific values/states would confirm vs reject the hypothesis>\n\n"
            "--- COMMANDS ---\n"
            "<MANDATORY: produce ONE [DEVICE: <ip>] block PER device in scope. The exact IPs "
            "to use are listed in the SCOPE section above. If scope has 2 devices, you MUST "
            "produce 2 [DEVICE:] blocks. If scope has 5 devices, you MUST produce 5 blocks. "
            "DO NOT skip any device. Format:>\n"
            "[DEVICE: <ip-from-scope>]\n"
            "<command 1>\n"
            "<command 2>\n"
            "[DEVICE: <next-ip-from-scope>]\n"
            "<command 1>\n"
            "<command 2>\n"
            "...\n\n"

            "RULES:\n"
            "- Use exact Cisco IOS / IOS-XE syntax (no abbreviations the parser may not accept).\n"
            "- Keep commands minimal — only what's needed to prove/disprove the hypothesis.\n"
            "- Use the EXACT IP addresses from the SCOPE section as the [DEVICE: ...] identifier — "
            "NEVER use hostnames like 'R1' or 'R2', always use the IP.\n"
            "- For protocol issues (OSPF/BGP/EIGRP/HSRP/IPSec/LDP), both peers need the SAME "
            "diagnostic commands so values can be compared side-by-side.\n"
            "- Do NOT include any text outside the four marked sections."
        )

        raw = self.ai_call(plan_prompt) or ""
        plan = self._parse_plan_response(raw, query, devices)
        return plan

    def _parse_plan_response(
        self,
        raw: str,
        query: str,
        devices: List[Any],
    ) -> DiagnosticPlan:
        """Parse the AI's plan response into a DiagnosticPlan."""
        plan = DiagnosticPlan(
            query=query,
            devices=[
                {
                    "ip": d.ip,
                    "hostname": d.hostname or d.ip,
                    "type": d.device_type or "cisco_ios",
                }
                for d in devices
            ],
        )

        def section(name: str) -> str:
            marker = f"--- {name} ---"
            if marker not in raw:
                return ""
            after = raw.split(marker, 1)[1]
            # Stop at the next "--- ... ---"
            next_marker = re.search(r"\n---\s+\w+\s+---", after)
            return (after[:next_marker.start()] if next_marker else after).strip()

        plan.hypothesis        = section("HYPOTHESIS") or "Investigating root cause"
        plan.reasoning         = section("REASONING")  or "Running diagnostic commands"
        plan.expected_outcome  = section("EXPECTED OUTCOME") or ""

        # Parse [DEVICE: ip] blocks
        cmd_section = section("COMMANDS")
        # Build a set of valid IPs in scope (for validation)
        scope_ips = {d.ip for d in devices}
        # Build hostname → IP map (in case AI returns hostname instead of IP)
        hostname_to_ip = {(d.hostname or "").lower(): d.ip for d in devices if d.hostname}

        if cmd_section:
            blocks = re.split(r"\[DEVICE:\s*([^\]]+)\]", cmd_section)
            # Result: ['', dev1, cmds1, dev2, cmds2, ...]
            for i in range(1, len(blocks), 2):
                raw_dev = blocks[i].strip()
                cmd_text = blocks[i + 1] if i + 1 < len(blocks) else ""
                cmds = [
                    line.strip()
                    for line in cmd_text.splitlines()
                    if line.strip() and not line.strip().startswith("#")
                ]
                if not cmds:
                    continue

                # Normalize identifier — accept IP, hostname, or "R1 (ip)" style
                resolved_ip = None
                if raw_dev in scope_ips:
                    resolved_ip = raw_dev
                else:
                    # Try hostname match
                    if raw_dev.lower() in hostname_to_ip:
                        resolved_ip = hostname_to_ip[raw_dev.lower()]
                    else:
                        # Try to extract an IP from the string (e.g. "R1 192.168.96.130")
                        ip_match = re.search(r"\d+\.\d+\.\d+\.\d+", raw_dev)
                        if ip_match and ip_match.group(0) in scope_ips:
                            resolved_ip = ip_match.group(0)

                if resolved_ip:
                    plan.commands_per_device[resolved_ip] = cmds

        # ── ENFORCE: every device in scope MUST have commands ───────────────
        # If AI dropped any device from the plan, we ASK AI AGAIN with an
        # explicit pointer to the missing devices. No static auto-fill, no
        # hardcoded substitution — AI decides what each device needs.
        if plan.commands_per_device:
            missing = [d for d in devices if d.ip not in plan.commands_per_device]
            if missing:
                self._ai_complete_missing_devices(plan, missing, raw)

        # If AI completely failed to give commands for any device
        if not plan.commands_per_device:
            plan.reasoning = (
                "⚠️ AI did not generate any device-specific commands. "
                "Please rephrase your question with more detail "
                "(e.g. include the protocol or symptom you're observing). "
                "Original AI response:\n\n" + (raw[:1500] if raw else "(empty)")
            )

        return plan

    def _ai_complete_missing_devices(
        self,
        plan: "DiagnosticPlan",
        missing_devices: List[Any],
        original_response: str,
    ) -> None:
        """
        AI's first plan missed some devices in scope.
        Ask AI again — explicitly — what commands to run on the missing devices.
        No static fallback. AI decides everything.
        """
        existing_cmds_view = "\n".join(
            f"[DEVICE: {ip}]\n" + "\n".join(cmds)
            for ip, cmds in plan.commands_per_device.items()
        )
        missing_list = "\n".join(
            f"  - {d.hostname or d.ip}  IP={d.ip}  type={d.device_type}"
            for d in missing_devices
        )

        retry_prompt = (
            "You are NetBrain AI — a CCIE-level network engineer.\n"
            "Your previous diagnostic plan was incomplete. You proposed commands "
            "for some devices but missed others that the operator selected.\n\n"
            f"OPERATOR QUESTION: {plan.query}\n\n"
            f"YOUR CURRENT PLAN:\n{existing_cmds_view}\n\n"
            f"DEVICES YOU FORGOT (still in scope, MUST be covered):\n{missing_list}\n\n"
            "TASK: For EACH missing device above, list the diagnostic commands "
            "you want to run on it. Use your own reasoning — what commands "
            "best fit each device's role and the operator's question?\n\n"
            "OUTPUT FORMAT (strict):\n"
            "[DEVICE: <ip-from-missing-list>]\n"
            "<command 1>\n"
            "<command 2>\n"
            "[DEVICE: <next-missing-ip>]\n"
            "<command 1>\n"
            "...\n\n"
            "RULES:\n"
            "- Use exact IP addresses from the missing list, NEVER hostnames.\n"
            "- Use exact Cisco IOS / IOS-XE syntax.\n"
            "- Output ONLY [DEVICE:] blocks. No headers, no commentary."
        )

        retry_raw = self.ai_call(retry_prompt) or ""

        # Parse the retry response — same parser logic
        scope_ips = {d.ip for d in missing_devices}
        hostname_to_ip = {
            (d.hostname or "").lower(): d.ip
            for d in missing_devices if d.hostname
        }

        blocks = re.split(r"\[DEVICE:\s*([^\]]+)\]", retry_raw)
        added: List[str] = []
        for i in range(1, len(blocks), 2):
            raw_dev = blocks[i].strip()
            cmd_text = blocks[i + 1] if i + 1 < len(blocks) else ""
            cmds = [
                line.strip()
                for line in cmd_text.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            if not cmds:
                continue

            resolved_ip = None
            if raw_dev in scope_ips:
                resolved_ip = raw_dev
            elif raw_dev.lower() in hostname_to_ip:
                resolved_ip = hostname_to_ip[raw_dev.lower()]
            else:
                ip_match = re.search(r"\d+\.\d+\.\d+\.\d+", raw_dev)
                if ip_match and ip_match.group(0) in scope_ips:
                    resolved_ip = ip_match.group(0)

            if resolved_ip and resolved_ip not in plan.commands_per_device:
                plan.commands_per_device[resolved_ip] = cmds
                added.append(resolved_ip)

        # Track which devices AI still couldn't address even on retry
        still_missing = [d for d in missing_devices if d.ip not in plan.commands_per_device]
        if still_missing:
            names = ", ".join(d.hostname or d.ip for d in still_missing)
            plan.reasoning += (
                f"\n\n⚠️ AI was unable to propose commands for: {names}. "
                "These devices will be skipped. Please clarify your question or "
                "rephrase to include these devices explicitly."
            )

    # ── Deep analysis prompt (CCIE-level) ────────────────────────────────────

    def _build_deep_analysis_prompt(
        self,
        plan: DiagnosticPlan,
        result: IntentResult,
    ) -> str:
        """Build CCIE-grade analysis prompt with cross-device correlation."""
        sections: List[str] = []
        for dr in result.device_results:
            if dr.error and not dr.connected:
                sections.append(f"=== {dr.hostname} ({dr.ip}) — SSH FAILED: {dr.error} ===")
                continue
            block = [f"=== {dr.hostname} ({dr.ip}) ==="]
            for cmd, out in dr.outputs.items():
                block.append(f"\n$ {cmd}\n{out}")
            sections.append("\n".join(block))
        all_output = "\n\n".join(sections) if sections else "(no output)"

        grounding = self._ground(plan.query, [
            type("D", (), {"ip": dr.ip, "hostname": dr.hostname, "device_type": "cisco_ios"})()
            for dr in result.device_results])
        grounding_block = ("\n\n" + grounding + "\n") if grounding else ""

        prompt = (
            "You are NetBrain AI — a CCIE-level network engineer.\n"
            "You proposed a hypothesis and ran diagnostic commands. Now ANALYZE the results.\n\n"
            f"OPERATOR QUESTION: {plan.query}\n\n"
            f"YOUR INITIAL HYPOTHESIS: {plan.hypothesis}\n"
            f"YOUR EXPECTED OUTCOME: {plan.expected_outcome}\n"
            f"{grounding_block}\n"
            f"LIVE ROUTER OUTPUT FROM ALL DEVICES:\n\n{all_output}\n\n"
            "Analyze the output and reply in this EXACT compact format. Be terse — a "
            "network engineer must grasp it in seconds. Do NOT restate commands or paste "
            "output. Keep everything before the action tag under ~120 words.\n\n"
            "VERDICT: <HEALTHY|PROBLEM|INCONCLUSIVE>\n"
            "FINDINGS:\n"
            "- [CRIT|WARN|OK] <one short factual finding, include the specific value>\n"
            "  (2-4 findings maximum, most important first)\n"
            "ROOT_CAUSE: <one sentence — the precise cause, or 'unconfirmed'>\n"
            "IMPACT: <one short sentence>\n\n"
            "Then choose EXACTLY ONE action and end with its tag:\n"
            "(a) A config change is needed → list [CONFIG] (on <dev>) <cmd> lines, then a line "
            "'--- ROLLBACK ---' followed by [ROLLBACK] (on <dev>) <cmd> lines, then end with: "
            "APPROVAL_REQUIRED\n"
            "(b) You need MORE read-only checks → list [NEXT] (on <dev>) <command> lines, then end "
            "with: NEXT_STEP_REQUIRED\n"
            "(c) Healthy / no change required → end with: DIAGNOSIS_COMPLETE\n\n"
            "HARD SAFETY RULES (non-negotiable):\n"
            "- NEVER propose `debug`, `clear`, `reload`, `test`, or any disruptive command. "
            "Diagnostics use ONLY non-disruptive `show`/`display` commands.\n"
            "- For protocol issues, compare the discriminating values across peers (MTU, network "
            "type, timers, area, authentication, subnet/mask) and name the precise mismatch in "
            "ROOT_CAUSE. Different Router-IDs are NORMAL — never call that a fault.\n"
            f"   (Round {plan.round_index} of {result.max_rounds}; prefer a conclusion over another round.)"
        )
        return prompt

    # ── Intent classification ─────────────────────────────────────────────────

    def _classify(self, query: str) -> Tuple[str, str]:
        """Return (intent, scenario) without calling AI — fast keyword match."""
        q = query.lower()

        # Concept check first (very specific phrases)
        if any(kw in q for kw in _CONCEPT_KEYWORDS):
            return INTENT_CONCEPT, "general"

        # Reachability
        if any(kw in q for kw in _REACHABILITY_KEYWORDS) and (
            "reach" in q or "ping" in q or "connect" in q or "path" in q
        ):
            return INTENT_REACHABILITY, "reachability"

        # Config
        if any(kw in q for kw in _CONFIG_KEYWORDS):
            return INTENT_CONFIG, self._detect_scenario(q)

        # Default: diagnostic
        return INTENT_DIAGNOSTIC, self._detect_scenario(q)

    def _detect_scenario(self, q: str) -> str:
        """Map query to a scenario key for command selection."""
        for scenario in ("ospf", "bgp", "eigrp", "vlan", "acl",
                         "dhcp", "nat", "performance", "interface"):
            if scenario in q:
                return scenario
        if any(kw in q for kw in ("route", "routing", "prefix", "subnet")):
            return "routing"
        if any(kw in q for kw in ("reach", "ping", "connect", "path", "trace")):
            return "reachability"
        if any(kw in q for kw in ("cpu", "memory", "load", "slow", "high")):
            return "performance"
        return "general"

    # ── Diagnostic handler ────────────────────────────────────────────────────

    def _handle_diagnostic(
        self,
        result: IntentResult,
        query: str,
        primary_device: Optional[Any],
        session_output: str,
        session_diagnosis: str,
    ) -> None:
        """
        Legacy single-stage diagnostic — kept for backward compat with old
        handle() entry. Internally uses AI plan generation now.
        """
        # Build the device list (primary + others for reachability)
        devices_to_poll: List[Any] = []
        if primary_device:
            devices_to_poll.append(primary_device)
        if result.intent == INTENT_REACHABILITY and self.approved_devices:
            for d in self.approved_devices:
                if primary_device and d.ip == primary_device.ip:
                    continue
                devices_to_poll.append(d)
        if not devices_to_poll:
            devices_to_poll = list(self.approved_devices)

        # Let AI generate the plan (no static library)
        plan = self._ai_generate_plan(
            query, devices_to_poll, result.scenario,
            session_output, session_diagnosis,
        )
        result.plan = plan

        ip_to_dev = {d.ip: d for d in devices_to_poll}
        for ip, cmds in plan.commands_per_device.items():
            dev = ip_to_dev.get(ip)
            if not dev or not cmds:
                continue
            dr = self._ssh_collect(dev, cmds)
            result.device_results.append(dr)

        # CCIE-grade analysis on real output
        analysis_prompt = self._build_deep_analysis_prompt(plan, result)
        result.analysis = self.ai_call(analysis_prompt) or "AI unavailable."

        if "APPROVAL_REQUIRED" in result.analysis:
            result.needs_approval = True
            result.fix_commands, result.fix_explanation, result.rollback_commands = (
                self._extract_fix_from_analysis(result.analysis)
            )
            result.analysis = result.analysis.split("APPROVAL_REQUIRED")[0].strip()

    # ── Config handler ────────────────────────────────────────────────────────

    def _read_device_facts(self, device: Any) -> str:
        """
        Read a device's REAL interface/IP state so config generation is
        grounded in what's actually on the box (not a generic guess). Uses
        the same robust SSH→Telnet connection layer as topology discovery.
        Returns the raw 'show ip interface brief' (+ OSPF state) text, or ""
        on failure (caller degrades to ungrounded generation).
        """
        try:
            from core.topology.discovery import _establish_connection, _base_platform
            from core.topology.credentials import resolve_device_credentials
            u, p, sec = resolve_device_credentials(device.ip)
            base = _base_platform(getattr(device, "device_type", ""))
            conn, _ = _establish_connection(device, base, u, p, sec)
            try:
                conn.enable()
            except Exception:
                pass
            out = []
            for cmd in ("show ip interface brief", "show ip protocols"):
                try:
                    out.append(f"=== {cmd} ===\n" + conn.send_command(cmd, read_timeout=20))
                except Exception:
                    pass
            conn.disconnect()
            return "\n".join(out)
        except Exception as exc:
            logger.debug(f"_read_device_facts failed for {device.ip}: {exc}")
            return ""

    def _rag_context_for(self, query: str) -> str:
        """Pull grounding context from the RAG knowledge base (runbooks/incidents)
        so generation is informed by curated knowledge, not just the LLM's priors."""
        if not KNOWLEDGE_OK:
            return ""
        try:
            hits = get_orchestrator().rag_query(query, top_k=3)
            if not hits:
                return ""
            blocks = [f"[{h.source} · {h.title}]\n{h.text[:500]}" for h in hits]
            return "RELEVANT KNOWLEDGE (from your runbooks/past incidents):\n" + "\n---\n".join(blocks)
        except Exception as exc:
            logger.debug(f"RAG context lookup failed: {exc}")
            return ""

    def _vendor_doc_context(self, query: str, devices: List[Any]) -> str:
        """Supplement grounding with vendor docs / MCP when RAG has no strong hit."""
        if not KNOWLEDGE_OK:
            return ""

        from core.knowledge.vendor_router import supported_vendors

        contexts: List[str] = []
        seen_vendors = set()

        # Use vendors from the selected devices first, but allow broader vendor
        # coverage if no device-specific vendor is detected.
        vendor_candidates: List[str] = []
        for device in devices:
            vendor = detect_vendor(getattr(device, "device_type", None))
            if vendor and vendor != "unknown" and vendor not in seen_vendors:
                seen_vendors.add(vendor)
                vendor_candidates.append(vendor)

        if not vendor_candidates:
            vendor_candidates = supported_vendors()

        for vendor in vendor_candidates:
            platform = None
            if devices:
                platform = detect_platform(getattr(devices[0], "device_type", None))
            try:
                entry = get_orchestrator().lookup(vendor, query, platform)
                if not entry or entry.citation.confidence == ConfidenceLevel.UNVERIFIED:
                    continue
                url = entry.citation.source_url or ""
                title = entry.citation.source_title or entry.citation.source_name
                snippet = (entry.description or "").strip()[:1200]
                if snippet:
                    contexts.append(
                        f"[{vendor.upper()} DOC/MCP] {title}{' — ' + url if url else ''}\n{snippet}"
                    )
            except Exception as exc:
                logger.debug(f"Vendor doc/MCP context lookup failed for {vendor}: {exc}")

        return "VENDOR DOCUMENTS / MCP CONTEXT:\n" + "\n\n".join(contexts) if contexts else ""

    # ── RAG-FIRST grounding: enterprise knowledge + topology before any LLM call ──
    def _ground(self, query: str, devices: List[Any]) -> str:
        """Assemble grounding for the model: RAG + vendor docs/MCP + live topology."""
        parts: List[str] = []
        rag = self._rag_context_for(query)
        if rag:
            parts.append(rag)

        vendor_docs = self._vendor_doc_context(query, devices)
        if vendor_docs:
            parts.append(vendor_docs)

        topo = self._topology_facts(devices)
        if topo:
            parts.append(topo)
        return "\n\n".join(parts)

    def _topology_facts(self, devices: List[Any]) -> str:
        """Neighbor/adjacency facts from the platform Knowledge Graph (best-effort).
        Lets the agent reason about the OTHER end of an adjacency, not just the
        devices the operator happened to select."""
        try:
            from core.knowledge_graph import KnowledgeGraph  # reused, not new
            kg = KnowledgeGraph()
        except Exception:
            return ""
        lines: List[str] = []
        for d in devices:
            ip = getattr(d, "ip", "")
            if not ip:
                continue
            try:
                deps = kg.get_dependencies(ip) or []
                if deps:
                    lines.append(f"{getattr(d,'hostname','') or ip} is adjacent to: {', '.join(map(str, deps))}")
            except Exception:
                continue
        return ("LIVE TOPOLOGY (from the knowledge graph):\n" + "\n".join(lines)) if lines else ""

    # ── Command safety classifier — the enabler for read-only autonomy ─────────
    # Commands that MUST NEVER be auto-run, even though they don't change config.
    # debug/monitor can flood the CPU and take a router down under load; test/clear/
    # reload are disruptive. These are blocked from autonomous execution outright.
    DANGEROUS_VERBS = ("debug", "undebug", "u all", "monitor", "test", "clear",
                       "reload", "terminal monitor", "tclsh", "send", "verify /")
    READ_VERBS = ("show", "ping", "traceroute", "trace", "display", "dir", "more",
                  "who", "terminal length")
    WRITE_MARKERS = ("configure", "conf t", "interface ", "ip ", "no ", "shutdown",
                     "no shutdown", "clear ", "reload", "write", "copy ", "erase",
                     "delete", "crypto ", "router ", "switchport", "vlan ", "boot ",
                     "username ", "snmp-server", "line ", "logging ", "ntp ", "hostname ")

    @staticmethod
    def _normalize_cmd(command: str) -> str:
        """Strip internal routing markers ([CONFIG]/[EXEC]/[NEXT]/[ROLLBACK] and
        '(on R1)') as PREFIXES — not as characters — then lower-case. (Using
        str.lstrip on a marker string would wrongly strip individual letters,
        which previously let 'clear' slip through as 'lear'.)"""
        import re
        c = (command or "").strip()
        c = re.sub(r"^\[(exec|config|rollback|next)\]\s*", "", c, flags=re.I)
        c = re.sub(r"^\(on [^)]+\)\s*", "", c, flags=re.I)
        return c.strip().lower()

    @classmethod
    def is_dangerous(cls, command: str) -> bool:
        c = cls._normalize_cmd(command)
        return bool(c) and c.startswith(cls.DANGEROUS_VERBS)

    @classmethod
    def is_read_only(cls, command: str) -> bool:
        c = cls._normalize_cmd(command)
        if not c:
            return False
        # HARD BLOCK: debug/monitor/test/clear/reload are NEVER auto-runnable
        if cls.is_dangerous(c):
            return False
        if c.startswith(cls.READ_VERBS):
            # 'show' et al never mutate state
            return True
        # anything that looks like config-mode or a mutating exec is NOT read-only
        if any(m in c for m in cls.WRITE_MARKERS):
            return False
        # default-deny: unknown verbs are treated as NOT read-only (safe)
        return False

    @classmethod
    def _filter_read_only(cls, cmds_per_device: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """Keep ONLY read-only commands for autonomous execution. Dangerous
        commands (debug/monitor/clear/reload/test) are dropped — never auto-run."""
        out: Dict[str, List[str]] = {}
        for ip, cmds in cmds_per_device.items():
            safe = [c for c in cmds if cls.is_read_only(c)]
            if safe:
                out[ip] = safe
        return out

    # ── Autonomous diagnostic loop ─────────────────────────────────────────────
    # HARDCODED POLICY (intentional — this is an invariant, not a command):
    # the human is ALWAYS in the loop for any WRITE/mutating action. Read-only
    # diagnostics may run autonomously under operator oversight (visible trace +
    # kill switch); configuration changes are NEVER applied without explicit human
    # approval. Commands themselves are never hardcoded — only this policy is.
    REQUIRE_HUMAN_APPROVAL_FOR_WRITES = True

    def run_autonomous(
        self,
        query: str,
        devices: List[Any],
        *,
        max_rounds: int = 4,
        auto_fix: bool = True,
        scenario: str = "general",
        stop_flag: Optional[Callable[[], bool]] = None,
        on_round: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> IntentResult:
        """Full read-only autonomy: the agent plans, runs READ-ONLY diagnostics
        itself (no per-round gate), analyses, and keeps going until it reaches a
        root cause or the round cap. When a fix is found and auto_fix=True, it is
        applied with guardrails (validate → apply → verify → auto-rollback).
        """
        intent, scen = self._classify(query)
        result = IntentResult(intent=intent, scenario=scen or scenario, query=query,
                              autonomous=True, max_rounds=max_rounds)
        session_diagnosis = ""
        plan: Optional[DiagnosticPlan] = None

        for rnd in range(1, max_rounds + 1):
            if stop_flag and stop_flag():
                result.analysis += "\n\n🛑 Stopped by operator."
                return result

            # 1) PLAN (RAG-grounded). First round from the query; later rounds from
            #    the AI's own NEXT_STEP commands.
            if plan is None:
                plan = self._ai_generate_plan(query, devices, result.scenario, "", session_diagnosis)
                plan.round_index = rnd
            # 2) SAFETY: keep ONLY read-only commands for autonomous execution
            plan.commands_per_device = self._filter_read_only(plan.commands_per_device)
            if not plan.commands_per_device:
                result.analysis += "\n\n(no read-only commands proposed — nothing to auto-run)"
                break

            # 3) EXECUTE read-only commands ourselves (no human gate)
            round_result = self.execute_plan(plan, devices)
            # carry forward device output + analysis
            result.device_results = round_result.device_results
            result.analysis = round_result.analysis
            session_diagnosis = round_result.analysis[:800]

            entry = {
                "round": rnd,
                "hypothesis": plan.hypothesis,
                "commands": {ip: cmds for ip, cmds in plan.commands_per_device.items()},
                "analysis": round_result.analysis,
                "verdict": ("fix" if round_result.needs_approval else
                            "next" if round_result.needs_followup else "complete"),
            }
            result.trace.append(entry)
            if on_round:
                try:
                    on_round(entry)
                except Exception:
                    pass

            # 4) DECIDE
            if round_result.needs_approval and round_result.fix_commands:
                result.needs_approval = True
                result.fix_commands = round_result.fix_commands
                result.commands_per_device = round_result.commands_per_device
                result.fix_explanation = round_result.fix_explanation
                result.rollback_commands = round_result.rollback_commands
                result.verify_commands = round_result.verify_commands
                result.validation_md = round_result.validation_md
                # HUMAN-IN-THE-LOOP POLICY: a write is NEVER auto-applied while the
                # policy is on. The agent prepares + validates the fix and hands it
                # to the operator to approve. auto_fix can only deploy if policy is
                # explicitly disabled (e.g. a lab with REQUIRE_..._WRITES=False).
                if auto_fix and not self.REQUIRE_HUMAN_APPROVAL_FOR_WRITES:
                    self._auto_apply_fix(result, devices, original_query=query)
                else:
                    result.trace.append({"round": "fix",
                                         "awaiting_human": True,
                                         "fix_commands": result.fix_commands})
                return result

            if round_result.needs_followup and round_result.next_plan:
                plan = round_result.next_plan          # continue autonomously
                continue

            # DIAGNOSIS_COMPLETE / no fix needed
            return result

        result.analysis += (f"\n\n⚠️ Reached the {max_rounds}-round limit without a "
                            "conclusive fix. Escalating to a human.")
        return result

    # ── Guardrailed auto-fix: validate → apply → verify → auto-rollback ────────
    def _auto_apply_fix(self, result: IntentResult, devices: List[Any],
                        original_query: str = "") -> None:
        ip_to_dev = {d.ip: d for d in devices}
        # per-device config commands (grounded) or merged fix list
        per_dev = result.commands_per_device or {}
        applied_any = False
        for ip, dev in ip_to_dev.items():
            cfg = [c.replace("[CONFIG]", "").strip()
                   for c in per_dev.get(ip, result.fix_commands)
                   if "[CONFIG]" in c]
            cfg = [c for c in cfg if c and not self.is_read_only(c) or c]  # keep config lines
            cfg = [c.split("(on", 1)[0].strip() if "(on" in c else c for c in cfg]
            if not cfg:
                continue
            try:
                self._ssh_apply(dev, cfg)
                applied_any = True
                result.trace.append({"round": "fix", "device": ip, "applied": cfg})
            except Exception as e:
                result.trace.append({"round": "fix", "device": ip, "error": str(e)})
        result.applied = applied_any
        if not applied_any:
            return

        # VERIFY: re-run the verification commands and let the AI judge
        verify_cmds = result.verify_commands or [self._default_verify(original_query)]
        ok = True
        for ip, dev in ip_to_dev.items():
            dr = self._ssh_collect(dev, [c for c in verify_cmds if self.is_read_only(c)])
            joined = "\n".join(dr.outputs.values())
            verdict = self.ai_call(
                f"After applying a fix for '{original_query}', here is verification output "
                f"from {dev.hostname or ip}:\n{joined}\n\nIs the issue RESOLVED? "
                "Answer strictly RESOLVED or NOT_RESOLVED on the first line.") or ""
            if "NOT_RESOLVED" in verdict.upper():
                ok = False
        result.verified = ok

        # AUTO-ROLLBACK on failed verification
        if not ok and result.rollback_commands:
            for ip, dev in ip_to_dev.items():
                rb = [c.replace("[ROLLBACK]", "").strip() for c in result.rollback_commands
                      if "[ROLLBACK]" in c]
                rb = [c.split("(on", 1)[0].strip() if "(on" in c else c for c in rb]
                if rb:
                    try:
                        self._ssh_apply(dev, rb)
                    except Exception:
                        pass
            result.reverted = True

    def _default_verify(self, query: str) -> str:
        """Resolve a verification command for the query's intent — cache → RAG →
        MCP → grounded AI. No hardcoded command map."""
        try:
            from core.command_resolver import get_command_resolver
            res = get_command_resolver(ai_call=self.ai_call).resolve(
                f"verify the health of: {query}", phase="verify", n=1)
            if res.commands:
                return res.commands[0]
        except Exception as exc:
            logger.debug(f"verify resolve failed: {exc}")
        # last-resort grounded generation (still not a hardcoded command)
        gen = self.ai_call(
            f"Give ONLY the single most useful read-only Cisco IOS show command to "
            f"verify whether this is healthy: '{query}'. Return just the command.") or ""
        line = (gen.strip().splitlines() or [""])[0].strip("`").strip()
        return line if self.is_read_only(line) else ""

    def _ssh_apply(self, dev: Any, config_commands: List[str]) -> str:
        """Apply configuration via the same connection layer as _ssh_collect, but
        in config mode (send_config_set). Mutating — only called from the fix step.
        """
        if not NETMIKO_OK:
            raise RuntimeError("netmiko not installed")
        cfg = dict(
            device_type=getattr(dev, "device_type", "cisco_ios") or "cisco_ios",
            host=dev.ip, port=int(getattr(dev, "ssh_port", 22) or 22),
            username=os.environ.get("GNS3_SSH_USER", "admin"),
            password=os.environ.get("GNS3_SSH_PASS", "admin"),
            timeout=30, auth_timeout=30, fast_cli=False, global_delay_factor=2,
        )
        secret = os.environ.get("GNS3_SSH_SECRET", "")
        if secret:
            cfg["secret"] = secret
        conn = ConnectHandler(**cfg)
        try:
            try:
                conn.enable()
            except Exception:
                pass
            out = conn.send_config_set(config_commands, read_timeout=30)
            try:
                conn.save_config()
            except Exception:
                pass
            return out
        finally:
            try:
                conn.disconnect()
            except Exception:
                pass

    def _handle_config(
        self,
        result: IntentResult,
        query: str,
        primary_device: Optional[Any],
        session_output: str,
        all_devices: Optional[List[Any]] = None,
    ) -> None:
        """
        Generate config PER DEVICE, grounded in each device's REAL interfaces
        and informed by RAG knowledge. This is the intelligence layer: instead
        of pushing one generic command set to every router, it reads each
        router's actual subnets and writes commands that fit THAT router (e.g.
        an OSPF `network` statement per the interfaces the router really has),
        then proposes post-deploy verification so success is confirmed, not
        assumed.
        """
        devices = all_devices or ([primary_device] if primary_device else [])
        if not devices:
            result.fix_explanation = "No target devices."
            return

        rag_ctx = self._rag_context_for(query)
        merged: List[str] = []
        explanations: List[str] = []
        verify_set: set = set()

        for dev in devices:
            dev_name = getattr(dev, "hostname", "") or dev.ip
            dev_type = getattr(dev, "device_type", "cisco_ios") or "cisco_ios"
            facts = self._read_device_facts(dev)   # REAL interfaces/subnets for THIS device
            facts_block = (
                f"LIVE STATE of {dev_name} ({dev.ip}):\n{facts[:2500]}"
                if facts else
                f"(could not read live state of {dev_name}; generate only if safe without it)"
            )

            prompt = (
                "You are NetBrain AI — a CCIE-level network engineer configuring ONE router.\n\n"
                f"{facts_block}\n\n"
                + (f"{rag_ctx}\n\n" if rag_ctx else "")
                + f"OPERATOR REQUEST (applies to this router): {query}\n\n"
                "CRITICAL: Generate commands SPECIFIC to THIS router's real interfaces "
                "and subnets shown above. For routing protocols, the network/area "
                "statements MUST match the IP subnets THIS router actually has on its "
                "interfaces — do NOT copy a subnet that isn't on this device. If this "
                "router has no interface relevant to the request, say so and emit no "
                "config for it.\n\n"
                "RULES:\n"
                "1. Prefix each config-mode command with [CONFIG]\n"
                "2. Prefix each exec-mode command with [EXEC]\n"
                "3. After line '--- VERIFY ---', list [VERIFY]-prefixed show commands that "
                "confirm the change worked (e.g. [VERIFY] show ip ospf neighbor)\n"
                "4. After line '--- ROLLBACK ---', list [ROLLBACK]-prefixed undo commands\n"
                "5. After line '--- RISK ---', one-line risk assessment\n"
                "6. End with exactly: APPROVAL_REQUIRED\n\n"
                "Never include: reload, erase, write erase, delete, no ip routing, "
                "no line vty, hostname changes, credential changes.\n"
                "Use exact interface names and subnets from the live state above."
            )

            raw = self.ai_call(prompt) or ""
            cmds, expl, rb = self._extract_fix_from_analysis(raw)

            # Pull [VERIFY] commands
            for line in raw.splitlines():
                ls = line.strip()
                if ls.startswith("[VERIFY]"):
                    verify_set.add(ls.replace("[VERIFY]", "").strip())

            if cmds:
                result.commands_per_device[dev.ip] = cmds
                merged.extend(cmds)
                if rb:
                    result.rollback_commands.extend(rb)
                explanations.append(f"**{dev_name}** ({dev.ip}): {expl or 'config generated from live interfaces'}")
            else:
                explanations.append(f"**{dev_name}** ({dev.ip}): no applicable config (interfaces don't match request)")

        result.fix_commands = merged                      # legacy/merged view
        result.verify_commands = sorted(verify_set)
        result.needs_approval = bool(result.commands_per_device)
        result.fix_explanation = (
            "Per-device configuration (grounded in each router's real interfaces):\n\n"
            + "\n\n".join(explanations)
        )
        if rag_ctx:
            result.fix_explanation += "\n\n_Informed by RAG knowledge base._"

    # ── Concept handler ───────────────────────────────────────────────────────

    def _answer_concept(self, query: str) -> str:
        """Answer a pure conceptual question directly."""
        prompt = (
            "You are NetBrain AI — a CCIE-level network engineer.\n"
            f"Question: {query}\n\n"
            "Answer clearly and concisely. Use bullet points for lists. "
            "Include relevant Cisco IOS commands where applicable."
        )
        return self.ai_call(prompt) or "AI unavailable."

    # ── SSH collection ────────────────────────────────────────────────────────

    def _ssh_collect(
        self,
        dev: Any,
        commands: List[str],
    ) -> DeviceResult:
        """SSH into a device and run diagnostic commands. Returns DeviceResult."""
        dev_result = DeviceResult(
            ip=dev.ip,
            hostname=dev.hostname or dev.ip,
        )

        if not NETMIKO_OK:
            dev_result.error = "netmiko not installed"
            return dev_result

        cfg = dict(
            device_type=getattr(dev, "device_type", "cisco_ios") or "cisco_ios",
            host=dev.ip,
            port=int(getattr(dev, "ssh_port", 22) or 22),
            username=os.environ.get("GNS3_SSH_USER", "admin"),
            password=os.environ.get("GNS3_SSH_PASS", "admin"),
            timeout=30,
            auth_timeout=30,
            fast_cli=False,
            global_delay_factor=2,
        )
        secret = os.environ.get("GNS3_SSH_SECRET", "")
        if secret:
            cfg["secret"] = secret

        try:
            conn = ConnectHandler(**cfg)
            try:
                conn.enable()
            except Exception:
                pass

            dev_result.connected = True
            for cmd in commands:
                try:
                    out = conn.send_command(cmd, read_timeout=20)
                    dev_result.outputs[cmd] = out
                    dev_result.commands_run.append(cmd)
                except Exception as ce:
                    dev_result.outputs[cmd] = f"ERROR: {ce}"
                    dev_result.commands_run.append(cmd)

            try:
                conn.disconnect()
            except Exception:
                pass

        except Exception as ssh_err:
            dev_result.error = str(ssh_err)
            dev_result.connected = False

        return dev_result

    # ── Command selection ─────────────────────────────────────────────────────

    # ── Analysis prompt builder ───────────────────────────────────────────────

    # ── Fix command extractor ─────────────────────────────────────────────────

    def _extract_fix_from_analysis(
        self, raw: str
    ) -> Tuple[List[str], str, List[str]]:
        """
        Parse AI output into (fix_commands, explanation, rollback_commands).
        fix_commands are [CONFIG]/[EXEC] tagged.
        rollback_commands are plain IOS lines.
        """
        lines = raw.replace("APPROVAL_REQUIRED", "").strip().splitlines()
        fix_cmds: List[str] = []
        rollback_cmds: List[str] = []
        explanation_lines: List[str] = []
        in_rollback = False

        for line in lines:
            stripped = line.strip()
            if stripped == "--- ROLLBACK ---":
                in_rollback = True
                continue
            if stripped == "--- RISK ---":
                break  # stop before risk section
            if in_rollback:
                if stripped.startswith("[ROLLBACK]"):
                    rollback_cmds.append(stripped.replace("[ROLLBACK]", "").strip())
            elif stripped.startswith("[CONFIG]") or stripped.startswith("[EXEC]"):
                fix_cmds.append(stripped)
            else:
                explanation_lines.append(line)

        explanation = "\n".join(explanation_lines).strip()
        return fix_cmds, explanation, rollback_cmds

    # ── Phase 1-3: Citation enrichment ────────────────────────────────────────

    def _lookup_citations_for_plan(
        self,
        plan: "DiagnosticPlan",
        devices: List[Any],
    ) -> "CitationTracker":
        """
        For every command in the plan, look up its knowledge entry from the
        orchestrator (cache → web fetch → unverified fallback).
        """
        tracker = CitationTracker()
        orchestrator = get_orchestrator()

        # Collect unique commands per vendor/platform
        vendor_to_cmds: Dict[Tuple[str, str], List[str]] = {}
        for ip, cmds in plan.commands_per_device.items():
            dev = next((d for d in devices if d.ip == ip), None)
            if not dev:
                continue
            vendor   = detect_vendor(getattr(dev, "device_type", None))
            platform = detect_platform(getattr(dev, "device_type", None))
            key = (vendor, platform)
            for cmd in cmds:
                vendor_to_cmds.setdefault(key, []).append(cmd)

        # Look up in parallel per vendor batch
        for (vendor, platform), cmds in vendor_to_cmds.items():
            if vendor == "unknown":
                # No fetcher — mark all unverified
                for cmd in cmds:
                    tracker.add(cmd, KnowledgeEntry.unverified(vendor, cmd,
                        "Unknown vendor — cannot verify"))
                continue
            results = orchestrator.lookup_batch(vendor, cmds, platform)
            for cmd, entry in results.items():
                tracker.add(cmd, entry)

        return tracker

    # ── Phase 4: Command validation ───────────────────────────────────────────

    def _validate_fix_commands(
        self,
        fix_commands: List[str],
        devices: List[Any],
        device_results: List["DeviceResult"],
    ) -> str:
        """
        Validate proposed fix commands against device version + safety rules.
        Returns a markdown block with per-command validation badges.
        """
        validator = get_validator()

        # Parse device version from any 'show version' output we captured
        device_version_map: Dict[str, "DeviceVersion"] = {}
        for dr in device_results:
            ver = None
            # Try every output block for `show version` content
            for cmd, out in dr.outputs.items():
                if "show version" in cmd.lower() or out:
                    parsed = parse_show_version(out)
                    if parsed.vendor != "unknown":
                        ver = parsed
                        break
            # Fallback: detect from device_type
            if not ver:
                dev = next((d for d in devices if d.ip == dr.ip), None)
                if dev:
                    ver = DeviceVersion(
                        vendor=detect_vendor(getattr(dev, "device_type", None)),
                        platform=detect_platform(getattr(dev, "device_type", None)),
                    )
            if ver:
                device_version_map[dr.ip] = ver

        # Pick a representative version (first device with known vendor)
        primary_version = None
        for ver in device_version_map.values():
            if ver.vendor != "unknown":
                primary_version = ver
                break

        validation_result = validator.validate_batch(fix_commands, primary_version)
        summary = validation_result.summary()

        # Build markdown summary
        lines: List[str] = []
        lines.append(
            f"**🛡️ Command Validation:** "
            f"✅ {summary['ok']} ok · "
            f"⚠️ {summary['warn']} warn · "
            f"🚫 {summary['blocked']} blocked"
        )

        for cv in validation_result.per_command:
            badge = cv.badge()
            lines.append(f"  - {badge} &nbsp; `{cv.command}`")
            for finding in cv.findings:
                level_emoji = {"block": "🚫", "warning": "⚠️", "info": "ℹ️"}.get(finding.level, "•")
                lines.append(f"     {level_emoji} {finding.message}")

        if validation_result.has_blocked:
            lines.append("")
            lines.append(
                "🚫 **One or more commands are BLOCKED by safety policy. "
                "Deploy button will be disabled.**"
            )

        return "\n".join(lines)

    # ── Result formatter ──────────────────────────────────────────────────────

    @staticmethod
    def format_plan_for_chat(plan: DiagnosticPlan, citations_md: str = "") -> str:
        """Format a DiagnosticPlan for human review (Stage 1)."""
        cmd_lines = []
        for ip, cmds in plan.commands_per_device.items():
            host = next(
                (d["hostname"] for d in plan.devices if d["ip"] == ip),
                ip,
            )
            cmd_lines.append(f"**📍 {host} ({ip}):**")
            for c in cmds:
                cmd_lines.append(f"    `{c}`")
            cmd_lines.append("")

        citation_block = ""
        if citations_md:
            citation_block = (
                f"\n**📚 Knowledge Sources:**\n\n{citations_md}\n\n"
            )

        # Operator-facing card shows ONLY the proposed commands + the action
        # prompt. Hypothesis, reasoning, expected outcome, knowledge sources and
        # confidence are still computed in the backend (on `plan` / citations) but
        # are intentionally not rendered — they were noise on the GUI.
        return (
            f"**🔌 Proposed Diagnostic Commands:**\n\n"
            + "\n".join(cmd_lines)
            + f"\n⚠️ **Review the commands above. Click ✅ Run Plan to execute, or ❌ Cancel.**"
        )

    @staticmethod
    def format_for_chat(result: IntentResult, device_name: str = "") -> str:
        """
        Format an IntentResult into a markdown string for the chat UI.
        Called from app.py to render the response.
        """
        if result.error:
            return f"❌ **Error:** {result.error}"

        if result.intent == INTENT_CONCEPT:
            return result.plain_answer or "No answer generated."

        # Stage 1: plan pending human approval
        if result.plan_pending and result.plan:
            return IntentEngine.format_plan_for_chat(result.plan, result.citations_md)

        parts: List[str] = []

        # Read-only diagnostics run in the BACKGROUND — we do NOT dump raw output
        # to the operator (that's the wall-of-text problem). Show a one-line note
        # plus any connection failures, then a short colour-coded summary.
        ran = sum(len(dr.commands_run) for dr in result.device_results)
        ndev = len([dr for dr in result.device_results if dr.connected])
        for dr in result.device_results:
            if not dr.outputs and dr.error:
                parts.append(f"🔴 **{dr.hostname} ({dr.ip})** — SSH failed: `{dr.error}`")
        if ran:
            parts.append(
                f"<span style='color:#64748b;font-size:.8rem'>🔍 Ran {ran} read-only "
                f"check(s) on {ndev} device(s) in the background — summary below.</span>"
            )

        # AI analysis → rendered as a short, colour-coded summary (no raw output)
        if result.analysis:
            parts.append(IntentEngine._render_summary(result.analysis))

        # Config fix + validation
        if result.needs_approval and result.fix_commands:
            cmd_display = "\n".join(
                c.replace("[CONFIG]", "").replace("[EXEC]", "").strip()
                for c in result.fix_commands
            )
            fix_block = (
                "<div style='margin-top:.4rem;font-weight:600;color:#f59e0b'>"
                "⚙️ Proposed fix (awaiting your approval):</div>"
                f"```\n{cmd_display}\n```"
            )
            if result.validation_md:
                fix_block += f"\n\n{result.validation_md}"
            fix_block += "\n\n⚠️ **Use ✅ Deploy in the action strip to apply, or ❌ Cancel.**"
            parts.append(fix_block)

        return "\n\n".join(parts) if parts else result.analysis or "No result."

    @staticmethod
    def _render_summary(analysis: str) -> str:
        """Turn the model's compact VERDICT/FINDINGS/ROOT_CAUSE/IMPACT block into a
        short, colour-coded HTML summary. Falls back to trimmed text if the model
        didn't follow the format. Never shows raw command output."""
        import re
        text = analysis or ""
        for tag in ("APPROVAL_REQUIRED", "NEXT_STEP_REQUIRED", "DIAGNOSIS_COMPLETE"):
            text = text.replace(tag, "")
        verdict = ""
        m = re.search(r"VERDICT:\s*([A-Z]+)", text, re.I)
        if m:
            verdict = m.group(1).upper()
        findings = re.findall(r"-\s*\[(CRIT|WARN|OK)\]\s*(.+)", text, re.I)
        rc = re.search(r"ROOT_CAUSE:\s*(.+)", text, re.I)
        im = re.search(r"IMPACT:\s*(.+)", text, re.I)
        if not (verdict or findings or rc):
            return text.strip()[:800]      # model didn't comply — show trimmed text only

        vcolor = {"PROBLEM": "#f87171", "HEALTHY": "#34d399",
                  "INCONCLUSIVE": "#fbbf24"}.get(verdict, "#93c5fd")
        vlabel = {"PROBLEM": "⛔ PROBLEM", "HEALTHY": "✅ HEALTHY",
                  "INCONCLUSIVE": "🟡 INCONCLUSIVE"}.get(verdict, verdict or "RESULT")
        html = [f"<div style='font-weight:700;color:{vcolor};font-size:1rem'>{vlabel}</div>"]
        sev = {"CRIT": ("#f87171", "🔴"), "WARN": ("#fbbf24", "🟡"), "OK": ("#34d399", "🟢")}
        if findings:
            html.append("<ul style='margin:.35rem 0 .2rem 0;padding-left:1.1rem'>")
            for s, f in findings[:4]:
                c, dot = sev.get(s.upper(), ("#93c5fd", "🔹"))
                html.append(f"<li style='color:{c};margin:.12rem 0'>{dot} {f.strip()}</li>")
            html.append("</ul>")
        if rc:
            html.append(f"<div style='margin:.2rem 0'>🎯 <b>Root cause:</b> "
                        f"<span style='color:#e2e8f0'>{rc.group(1).strip()}</span></div>")
        if im:
            html.append(f"<div style='margin:.15rem 0;color:#94a3b8'>📉 <b>Impact:</b> "
                        f"{im.group(1).strip()}</div>")
        return "".join(html)
