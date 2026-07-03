"""
Troubleshooting Engine — reasoning (LLM-backed)
===============================================
The ONLY place the language model is used. Each function makes one structured
call and returns parsed Python. The engine stays in control of state, memory,
confidence and stopping — the model just reasons about network facts.

All prompts are protocol-agnostic and contain NO hardcoded commands or IPs;
concrete commands come from the model grounded on the supplied context (which the
engine fills from the platform's RAG / CommandResolver).
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List

AiCall = Callable[[str], str]


# ── robust JSON extraction ──────────────────────────────────────────────────────
def _extract_json(text: str) -> Any:
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    # try whole thing, then first balanced object/array
    for candidate in (t, _first_balanced(t, "{", "}"), _first_balanced(t, "[", "]")):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def _first_balanced(s: str, open_c: str, close_c: str) -> str:
    start = s.find(open_c)
    if start == -1:
        return ""
    depth = 0
    for i in range(start, len(s)):
        if s[i] == open_c:
            depth += 1
        elif s[i] == close_c:
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return ""


def _as_list(x: Any) -> List[dict]:
    if isinstance(x, list):
        return [i for i in x if isinstance(i, dict)]
    if isinstance(x, dict):
        for v in x.values():
            if isinstance(v, list):
                return [i for i in v if isinstance(i, dict)]
    return []


class Reasoner:
    def __init__(self, ai_call: AiCall) -> None:
        self.ai = ai_call

    # 1. Hypothesis Manager — generate candidate root causes
    def generate_hypotheses(self, objective: str, grounding: str,
                            evidence_summary: str, existing: List[str],
                            max_new: int = 4) -> List[dict]:
        ctx_block = ("CONTEXT:\n" + grounding + "\n") if grounding else ""
        ev_block = ("EVIDENCE SO FAR:\n" + evidence_summary + "\n") if evidence_summary else ""
        seen_block = ("ALREADY CONSIDERED (do not repeat):\n- " + "\n- ".join(existing) + "\n") if existing else ""
        prompt = (
            "You are a CCIE-level network diagnostician. Propose candidate ROOT CAUSES "
            "for the problem below. Do not propose fixes yet. Think about what could "
            "cause the symptom, then list distinct, testable hypotheses.\n\n"
            f"OBJECTIVE: {objective}\n"
            f"{ctx_block}{ev_block}{seen_block}"
            f"\nReturn STRICT JSON only — a list of up to {max_new} objects:\n"
            '[{"statement": "<one-sentence root cause>", '
            '"rationale": "<why plausible>", '
            '"discriminating_signals": ["<observable that would confirm/deny it>"], '
            '"prior": <0.05-0.4 initial plausibility>}]\n'
            "No prose, no markdown — JSON array only."
        )
        return _as_list(_extract_json(self.ai(prompt) or ""))[:max_new]

    # 2/7. Diagnostic + Command Planner — next commands with max diagnostic value
    def plan_commands(self, objective: str, active_hypotheses: List[dict],
                     grounding: str, already_run: List[str],
                     devices: List[str]) -> List[dict]:
        hyp_block = "\n".join(
            f"- [{h['id']}] {h['statement']} (confidence {h['confidence']:.0%})"
            for h in active_hypotheses
        )
        ctx_block = ("PLATFORM CONTEXT:\n" + grounding + "\n") if grounding else ""
        run_block = ("ALREADY RUN (forbidden to repeat):\n" + ", ".join(already_run) + "\n") if already_run else ""
        prompt = (
            "Choose the NEXT read-only diagnostic command(s) that will reduce the most "
            "uncertainty — ideally each command discriminates between multiple hypotheses. "
            "Use ONLY non-disruptive show/display commands. Never propose debug/clear/reload/"
            "configure/test. Do NOT propose any command already run.\n\n"
            f"OBJECTIVE: {objective}\n"
            f"DEVICES (ip): {', '.join(devices)}\n"
            f"ACTIVE HYPOTHESES:\n{hyp_block}\n"
            f"{ctx_block}{run_block}"
            "\nReturn STRICT JSON only — a list of up to 3 objects, best first:\n"
            '[{"device": "<ip or \'all\'>", "command": "<show ...>", '
            '"purpose": "<what it reveals>", "tests_hypotheses": ["<hyp id>"], '
            '"value": <0-1 expected information gain>}]\n'
            "JSON array only."
        )
        return _as_list(_extract_json(self.ai(prompt) or ""))

    # 9. Result Analyzer — output → facts + per-hypothesis impact
    def analyze(self, command: str, device: str, output: str,
                active_hypotheses: List[dict]) -> dict:
        hyp_block = "\n".join(f"- [{h['id']}] {h['statement']}" for h in active_hypotheses)
        prompt = (
            "Interpret this device output. Extract structured FACTS, and for EACH active "
            "hypothesis state whether the output supports, contradicts, or is neutral to it, "
            "with a strength 0-1. Be strict: only 'support' when the output genuinely raises "
            "the hypothesis; only 'contradict' when it genuinely lowers it.\n\n"
            f"DEVICE: {device}\nCOMMAND: {command}\n"
            f"OUTPUT:\n{output[:4000]}\n\n"
            f"ACTIVE HYPOTHESES:\n{hyp_block}\n\n"
            "Return STRICT JSON only:\n"
            '{"facts": [{"subject": "<e.g. ospf.neighbor or interface.Gi0/0.mtu>", '
            '"attribute": "<e.g. state|value>", "value": "<observed value>"}], '
            '"impacts": [{"hypothesis_id": "<id>", "effect": "support|contradict|neutral", '
            '"weight": <0-1>, "reason": "<short>"}]}\n'
            "JSON object only."
        )
        obj = _extract_json(self.ai(prompt) or "")
        if not isinstance(obj, dict):
            return {"facts": [], "impacts": []}
        obj.setdefault("facts", [])
        obj.setdefault("impacts", [])
        return obj

    # 12. Fix Generator — minimal remediation for a confirmed cause
    def generate_fix(self, root_cause: str, objective: str,
                    evidence_summary: str, grounding: str) -> dict:
        ev_block = ("EVIDENCE:\n" + evidence_summary + "\n") if evidence_summary else ""
        ctx_block = ("CONTEXT:\n" + grounding + "\n") if grounding else ""
        prompt = (
            "A root cause has been confirmed by evidence. Produce the MINIMUM safe "
            "configuration change to remediate it, plus a rollback. Explain briefly why it "
            "addresses THIS root cause. Non-disruptive, least-change; no debug/clear/reload.\n\n"
            f"OBJECTIVE: {objective}\nCONFIRMED ROOT CAUSE: {root_cause}\n"
            f"{ev_block}{ctx_block}"
            "\nReturn STRICT JSON only:\n"
            '{"config_commands": ["(on <dev>) <cmd>"], '
            '"rollback_commands": ["(on <dev>) <cmd>"], '
            '"explanation": "<why this fixes the root cause>"}\n'
            "JSON object only."
        )
        obj = _extract_json(self.ai(prompt) or "")
        return obj if isinstance(obj, dict) else {}

    # 13. Verification Planner — confirm the fix worked
    def plan_verification(self, root_cause: str, fix_commands: List[str]) -> dict:
        prompt = (
            "Given the confirmed root cause and the fix about to be applied, list the "
            "read-only commands that will CONFIRM the issue is resolved after the change, "
            "and the observable success criteria. Read-only only.\n\n"
            f"ROOT CAUSE: {root_cause}\nFIX:\n- " + "\n- ".join(fix_commands) + "\n\n"
            "Return STRICT JSON only:\n"
            '{"commands": ["<show ...>"], "success_criteria": "<what output proves resolution>"}\n'
            "JSON object only."
        )
        obj = _extract_json(self.ai(prompt) or "")
        return obj if isinstance(obj, dict) else {}

    def phrase_objective(self, query: str) -> str:
        prompt = (
            "Restate this network troubleshooting request as a single precise objective "
            "sentence (no preamble):\n\n" + query
        )
        return (self.ai(prompt) or query).strip().split("\n")[0][:200]
