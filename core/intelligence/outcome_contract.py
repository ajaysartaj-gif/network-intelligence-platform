"""
core/intelligence/outcome_contract.py
=====================================
The outcome-guaranteed execution engine — fully AI-driven.

The failure pattern this kills: the tool runs commands and ASSUMES the goal
was met (wrong subnets, verified too early, dumped instead of interpreted,
didn't persist). World-class automation inverts that: define the intended
END STATE, then PROVE the system reached it, and refuse to claim success
without proof.

Nothing here is hardcoded per protocol. There is no list of "OSPF -> check
FULL" or "save -> write memory". Instead, for ANY change the AI itself:

  1. DERIVES the post-conditions (the assertions that must all be true for
     the intent to be satisfied), each with the show command that tests it.
     Persistence is always one of them for a state-changing intent — the AI
     is instructed to include it — so "forgot write memory" becomes
     impossible by construction, for every protocol, every vendor.

  2. INTERPRETS each verification output and returns a verdict (pass / fail /
     pending) with a reason — reading the evidence, not grepping for a
     keyword. "Routing Information Sources is empty -> not converged yet"
     is a judgement the model makes, not a string match.

The engine is a pure harness: it asks the AI what success means, runs the
checks the AI specifies (re-polling while any are 'pending', because
convergence isn't instant), asks the AI to judge the results, and reports a
per-assertion contract. All intelligence lives in the model; the engine only
orchestrates and proves.

Vendor/protocol agnostic by design: swap OSPF for BGP, IOS for Junos, and
nothing here changes — the AI derives different post-conditions.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("NetBrain.Intelligence.OutcomeContract")

# AI interface reused from the rest of the tool: prompt -> text.
AiCall = Callable[[str], str]
# Runs a show/exec command on a device, returns output: (command) -> text.
CommandRunner = Callable[[str], str]


class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    PENDING = "pending"   # not yet — convergence in progress, worth re-polling
    UNKNOWN = "unknown"


@dataclass
class PostCondition:
    """One assertion that must be true for the intent to be satisfied."""
    key: str                      # short id, e.g. "persisted", "adjacency"
    description: str              # human-readable intent, AI-authored
    check_command: str           # show command that produces evidence
    verdict: Verdict = Verdict.UNKNOWN
    reason: str = ""             # AI's interpretation of the evidence
    evidence: str = ""           # raw command output (kept for the log)


@dataclass
class ContractResult:
    intent: str
    device: str
    conditions: List[PostCondition] = field(default_factory=list)
    satisfied: bool = False
    summary: str = ""

    def to_log(self) -> str:
        lines = [f"Outcome contract for «{self.intent}» on {self.device}: "
                 f"{'✅ SATISFIED' if self.satisfied else '❌ NOT satisfied'}"]
        for c in self.conditions:
            mark = {"pass": "✅", "fail": "❌", "pending": "⏳", "unknown": "❔"}.get(c.verdict.value, "❔")
            lines.append(f"  {mark} {c.description} — {c.reason or c.verdict.value}")
        if self.summary:
            lines.append(f"  ↳ {self.summary}")
        return "\n".join(lines)


def _extract_json(text: str) -> Optional[object]:
    """Pull the first JSON value out of an LLM reply (tolerates fences/prose)."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    blob = fenced.group(1) if fenced else text
    # find the outermost [...] or {...}
    m = re.search(r"(\[.*\]|\{.*\})", blob, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        try:
            return json.loads(blob.strip())
        except Exception:
            return None


class OutcomeContractEngine:
    """AI derives post-conditions; engine runs & re-polls; AI interprets."""

    def __init__(self, ai_call: AiCall):
        self.ai_call = ai_call

    # ── 1. AI DERIVES the post-conditions for this intent ────────────────────
    def derive_post_conditions(
        self,
        intent: str,
        device_name: str,
        applied_commands: List[str],
        device_facts: str = "",
    ) -> List[PostCondition]:
        prompt = (
            "You are a CCIE-level network engineer defining how to PROVE a change "
            "succeeded on a router. Given the operator intent and the config that "
            "was applied, list the POST-CONDITIONS that must ALL be true for the "
            "change to be considered successful.\n\n"
            "Rules:\n"
            "- ALWAYS include a post-condition that the change is PERSISTED to "
            "startup-config (a running change that isn't saved is a failure). Use "
            "the correct show command to PROVE persistence on this platform.\n"
            "- Include functional post-conditions specific to the intent (e.g. for "
            "a routing protocol: adjacency/neighbor state, routes present, a stable "
            "router-id). Derive them from the intent, not a fixed list.\n"
            "- Each post-condition needs a single show command that produces the "
            "evidence to judge it.\n"
            "- Do NOT include configuration commands here — only verification shows.\n\n"
            f"INTENT: {intent}\n"
            f"DEVICE: {device_name}\n"
            f"APPLIED CONFIG:\n" + "\n".join(applied_commands) + "\n\n"
            + (f"DEVICE LIVE FACTS:\n{device_facts[:1500]}\n\n" if device_facts else "")
            + "Respond with ONLY a JSON array, each item: "
            '{"key":"short_id","description":"what must be true","check_command":"show ..."}. '
            "No prose, no code fences."
        )
        raw = self.ai_call(prompt) or ""
        data = _extract_json(raw)
        conditions: List[PostCondition] = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                cmd = str(item.get("check_command", "")).strip()
                if not cmd:
                    continue
                _desc = str(item.get("description", "")).strip()
                # Harden interface checks: rewrite description read-backs to an
                # authoritative, format-stable command (full interface name,
                # untruncated `description` line) so a correct description is
                # never reported "missing" due to name abbreviation/truncation.
                try:
                    from core.intelligence.config_synthesis.interface import normalize_check_command
                    cmd = normalize_check_command(cmd, _desc)
                except Exception:
                    pass
                conditions.append(PostCondition(
                    key=str(item.get("key", "cond"))[:40],
                    description=_desc or item.get("key", "condition"),
                    check_command=cmd,
                ))
        return conditions

    # ── 2. AI INTERPRETS one piece of evidence ───────────────────────────────
    def interpret(self, condition: PostCondition, output: str, intent: str,
                  applied_commands: Optional[List[str]] = None,
                  running_config: str = "", startup_config: str = "") -> PostCondition:
        # Deterministic guard first: a config-PRESENCE condition is proven (or
        # not) directly against the authoritative config we just applied —
        # feature-agnostic and normalised, so abbreviation/truncation/empty-output
        # can't manufacture a false "missing". Operational facts (sync, adjacency,
        # reachability) still defer to the model. Only ever short-circuits to PASS.
        try:
            from core.intelligence.config_synthesis.interface import general_precheck
            _pre = general_precheck(condition.description, condition.check_command,
                                    output, intent, applied_commands=applied_commands,
                                    running_config=running_config,
                                    startup_config=startup_config)
            if _pre == "pass":
                condition.evidence = output or ""
                condition.verdict = Verdict.PASS
                condition.reason = ("deterministically confirmed against authoritative "
                                    "running/startup-config (normalised)")
                return condition
        except Exception:
            pass
        prompt = (
            "You are a CCIE-level engineer judging whether a post-condition is met, "
            "by READING the command output (not keyword matching).\n\n"
            f"INTENT: {intent}\n"
            f"POST-CONDITION: {condition.description}\n"
            f"COMMAND: {condition.check_command}\n"
            f"OUTPUT:\n{(output or '(no output)')[:2500]}\n\n"
            "Decide the verdict:\n"
            "- pass: the condition is clearly satisfied by the evidence.\n"
            "- fail: the evidence shows it is NOT satisfied and won't become so "
            "by waiting (e.g. mismatch, missing config on far end).\n"
            "- pending: not satisfied YET but plausibly converging (e.g. an "
            "adjacency still coming up); worth re-checking shortly.\n"
            "Respond with ONLY JSON: "
            '{"verdict":"pass|fail|pending","reason":"one concise sentence citing the evidence"}.'
        )
        raw = self.ai_call(prompt) or ""
        data = _extract_json(raw)
        condition.evidence = output or ""
        if isinstance(data, dict):
            v = str(data.get("verdict", "unknown")).lower().strip()
            condition.verdict = {
                "pass": Verdict.PASS, "fail": Verdict.FAIL,
                "pending": Verdict.PENDING,
            }.get(v, Verdict.UNKNOWN)
            condition.reason = str(data.get("reason", "")).strip()
        else:
            condition.verdict = Verdict.UNKNOWN
            condition.reason = "could not parse interpretation"
        return condition

    # ── 3. Run the contract: check, re-poll pendings, judge ──────────────────
    def enforce(
        self,
        intent: str,
        device_name: str,
        applied_commands: List[str],
        run_command: CommandRunner,
        device_facts: str = "",
        converge_timeout_s: int = 45,
        poll_interval_s: int = 5,
    ) -> ContractResult:
        result = ContractResult(intent=intent, device=device_name)
        conditions = self.derive_post_conditions(
            intent, device_name, applied_commands, device_facts
        )
        if not conditions:
            result.summary = "AI did not derive any post-conditions; cannot prove outcome."
            result.satisfied = False
            return result
        result.conditions = conditions

        # Authoritative, full-fidelity config snapshots fetched ONCE. These let
        # config-PRESENCE conditions be proven deterministically against what we
        # actually applied — no LLM output-reading, immune to abbreviation /
        # truncation / empty-output. Operational checks still use their own
        # command output and the model.
        _running_cfg, _startup_cfg = "", ""
        try:
            _running_cfg = run_command("show running-config") or ""
        except Exception:
            _running_cfg = ""
        try:
            _startup_cfg = run_command("show startup-config") or ""
        except Exception:
            _startup_cfg = ""

        deadline = time.time() + max(0, converge_timeout_s)
        # Initial evaluation
        for cond in conditions:
            out = ""
            try:
                out = run_command(cond.check_command)
            except Exception as exc:
                out = f"(command error: {exc})"
            self.interpret(cond, out, intent, applied_commands=applied_commands,
                           running_config=_running_cfg, startup_config=_startup_cfg)

        # Re-poll only the PENDING ones until they resolve or we time out.
        while any(c.verdict == Verdict.PENDING for c in conditions) and time.time() < deadline:
            time.sleep(max(1, poll_interval_s))
            for cond in conditions:
                if cond.verdict != Verdict.PENDING:
                    continue
                out = ""
                try:
                    out = run_command(cond.check_command)
                except Exception as exc:
                    out = f"(command error: {exc})"
                self.interpret(cond, out, intent, applied_commands=applied_commands,
                               running_config=_running_cfg, startup_config=_startup_cfg)

        # Any remaining PENDING after timeout is treated as FAIL (didn't converge).
        for c in conditions:
            if c.verdict == Verdict.PENDING:
                c.verdict = Verdict.FAIL
                c.reason = (c.reason + " | did not converge within "
                            f"{converge_timeout_s}s").strip(" |")

        result.satisfied = all(c.verdict == Verdict.PASS for c in conditions)
        passed = sum(1 for c in conditions if c.verdict == Verdict.PASS)
        result.summary = (
            f"{passed}/{len(conditions)} post-conditions satisfied."
            if result.satisfied else
            f"{passed}/{len(conditions)} satisfied — "
            + "; ".join(f"{c.key}: {c.reason}" for c in conditions if c.verdict != Verdict.PASS)
        )
        return result
