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

        try:
            # Map device IPs in the plan back to device objects
            ip_to_dev = {d.ip: d for d in all_devices}

            for ip, cmds in plan.commands_per_device.items():
                dev = ip_to_dev.get(ip)
                if not dev:
                    continue
                dr = self._ssh_collect(dev, cmds)
                result.device_results.append(dr)

            # AI now does deep analysis with REAL output from ALL devices
            analysis_prompt = self._build_deep_analysis_prompt(plan, result)
            result.analysis = self.ai_call(analysis_prompt) or "AI unavailable."

            # Extract any fix commands proposed
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

        except Exception as exc:
            logger.error(f"[IntentEngine] execute_plan() error: {exc}", exc_info=True)
            result.error = str(exc)

        return result

    # ── Legacy single-stage entry point (kept for compatibility) ───────────────

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

        prompt = (
            "You are NetBrain AI — a CCIE-level network engineer.\n"
            "You proposed a hypothesis and ran diagnostic commands. Now ANALYZE the results.\n\n"
            f"OPERATOR QUESTION: {plan.query}\n\n"
            f"YOUR INITIAL HYPOTHESIS: {plan.hypothesis}\n"
            f"YOUR EXPECTED OUTCOME: {plan.expected_outcome}\n\n"
            f"LIVE ROUTER OUTPUT FROM ALL DEVICES:\n\n{all_output}\n\n"
            "ANALYSIS TASK — be rigorous and specific:\n\n"
            "1. **VERIFY HYPOTHESIS**: State whether the output CONFIRMS or REJECTS your initial "
            "   hypothesis. Quote specific values from the output.\n\n"
            "2. **CROSS-DEVICE CORRELATION**: For protocol issues (OSPF/BGP/EIGRP), COMPARE "
            "   the relevant parameters across devices side-by-side. List mismatches explicitly:\n"
            "   - MTU on each interface\n"
            "   - OSPF network type (broadcast/point-to-point)\n"
            "   - Hello/Dead timers\n"
            "   - Area numbers\n"
            "   - Authentication\n"
            "   - Router IDs\n"
            "   For BGP: AS numbers, neighbor IPs, timers, password.\n\n"
            "3. **ROOT CAUSE**: State the EXACT root cause. Reference the precise mismatch "
            "   you found (e.g. \"R1 has MTU 1500 on Fa0/0 but R2 has MTU 1400 on Fa0/0\").\n"
            "   Do NOT propose generic fixes like 'change network type' without proving why.\n\n"
            "4. **IMPACT**: One line on what traffic/services are affected.\n\n"
            "5. **FIX**: ONLY if you have CONCLUSIVE evidence:\n"
            "   - List exact commands prefixed [CONFIG] or [EXEC]\n"
            "   - Specify which device each command targets: [CONFIG] (on R1) <cmd>\n"
            "   - Add rollback after: --- ROLLBACK ---\n"
            "   - Prefix rollback commands with [ROLLBACK]\n"
            "   - End with: APPROVAL_REQUIRED\n\n"
            "   If evidence is INCONCLUSIVE: say so and propose the NEXT diagnostic step. "
            "   Do NOT propose a fix you're not certain about.\n\n"
            "Be technical, precise, and reference specific values from the output."
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

        return (
            f"**🧠 AI Hypothesis:**\n{plan.hypothesis}\n\n"
            f"**📋 Reasoning:**\n{plan.reasoning}\n\n"
            f"**🎯 Expected Outcome:**\n{plan.expected_outcome}\n\n"
            f"**🔌 Proposed Diagnostic Commands:**\n\n"
            + "\n".join(cmd_lines)
            + citation_block
            + f"\n⚠️ **Review the plan above. Click ✅ Run Plan to execute, or ❌ Cancel.**"
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

        # Show commands + output per device
        for dr in result.device_results:
            if not dr.outputs and dr.error:
                parts.append(f"🔴 **{dr.hostname} ({dr.ip})** — SSH failed: `{dr.error}`")
                continue
            if dr.outputs:
                cmd_out_block = "\n".join(
                    f"$ {cmd}\n{out}" for cmd, out in dr.outputs.items()
                )
                parts.append(
                    f"**🔌 Live output from {dr.hostname} ({dr.ip}):**\n"
                    f"```\n{cmd_out_block}\n```"
                )

        # AI analysis
        if result.analysis:
            parts.append(f"**🧠 AI Analysis:**\n\n{result.analysis}")

        # Config fix + validation
        if result.needs_approval and result.fix_commands:
            # Display the commands cleanly, exactly as an engineer would enter
            # them. The [CONFIG]/[EXEC] markers are internal routing hints for
            # the deploy path (which mode each line runs in) -- they must NOT
            # leak into the display as a fake "cfg>" prompt, which looks broken
            # and confuses (real IOS shows "R2(config)#", never "cfg>").
            cmd_display = "\n".join(
                c.replace("[CONFIG]", "").replace("[EXEC]", "").strip()
                for c in result.fix_commands
            )
            fix_block = (
                f"**⚙️ Proposed Fix Commands:**\n"
                f"```\n{cmd_display}\n```"
            )
            if result.validation_md:
                fix_block += f"\n\n{result.validation_md}"
            fix_block += "\n\n⚠️ **Use ✅ Deploy in the action strip to apply, or ❌ Cancel.**"
            parts.append(fix_block)

        return "\n\n".join(parts) if parts else result.analysis or "No result."
