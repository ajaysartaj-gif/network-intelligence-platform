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
        sigs = sorted({s for h in active_hypotheses for s in (h.get("discriminating_signals") or [])})
        sig_block = ("PROBE FOR THESE DISCRIMINATING SIGNALS FIRST — a command is only useful if "
                     "it reveals one of them; do NOT choose generic 'collect everything' commands:\n- "
                     + "\n- ".join(sigs) + "\n") if sigs else ""
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
            f"{sig_block}{ctx_block}{run_block}"
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

    # ── vendor-agnostic variants (used when a VendorGateway is present) ─────────
    def plan_operations(self, objective: str, active_hypotheses: List[dict],
                        grounding: str, already_run: List[str],
                        devices: List[str], operation_catalogue: List[str]) -> List[dict]:
        """Propose NORMALIZED operations (not vendor commands). The gateway/adapter
        turns the chosen operation into vendor syntax."""
        hyp_block = "\n".join(
            f"- [{h['id']}] {h['statement']} (confidence {h['confidence']:.0%})"
            for h in active_hypotheses)
        cat = ", ".join(operation_catalogue)
        sigs = sorted({s for h in active_hypotheses for s in (h.get("discriminating_signals") or [])})
        sig_block = ("PROBE FOR THESE DISCRIMINATING SIGNALS FIRST — pick the operation that "
                     "reveals one of them; do NOT choose a generic 'collect_evidence' sweep when "
                     "a targeted operation exists:\n- " + "\n- ".join(sigs) + "\n") if sigs else ""
        # Grounding (retrieved runbook / vendor guidance) was previously accepted
        # as a parameter and never used here — now it informs operation choice.
        ctx_block = ("RETRIEVED GUIDANCE (follow its investigation order):\n" + grounding + "\n") if grounding else ""
        run_block = ("ALREADY COLLECTED (do not repeat):\n" + ", ".join(already_run) + "\n") if already_run else ""
        prompt = (
            "Choose the NEXT normalized diagnostic OPERATION(s) that reduce the most "
            "uncertainty. Do NOT write vendor commands — only normalized operations and "
            "parameters. Prefer operations that discriminate between multiple hypotheses.\n\n"
            f"OBJECTIVE: {objective}\n"
            f"DEVICES (ip): {', '.join(devices)}\n"
            f"ACTIVE HYPOTHESES:\n{hyp_block}\n"
            f"{sig_block}{ctx_block}"
            f"KNOWN OPERATIONS (not exhaustive): {cat}\n"
            f"{run_block}"
            "\nReturn STRICT JSON only — up to 3 objects, best first:\n"
            '[{"device": "<ip or \'all\'>", "operation": "<operation name>", '
            '"params": {"protocol": "<optional>", "interface": "<optional>"}, '
            '"purpose": "<what it reveals>", "tests_hypotheses": ["<hyp id>"], '
            '"value": <0-1>}]\n'
            "JSON array only."
        )
        return _as_list(_extract_json(self.ai(prompt) or ""))

    def propose_intent(self, root_cause: str, objective: str,
                      evidence_summary: str, allowed_intents: Optional[List[str]] = None) -> dict:
        """Propose a vendor-NEUTRAL remediation intent. No vendor syntax."""
        ev = ("EVIDENCE:\n" + evidence_summary + "\n") if evidence_summary else ""
        allow = ""
        if allowed_intents:
            allow = ("\nChoose the intent name from this supported set (pick the closest fit): "
                     + ", ".join(allowed_intents) + "\n")
        prompt = (
            "Given the confirmed root cause, describe the remediation as a VENDOR-NEUTRAL "
            "INTENT — a short intent name plus parameters. Do NOT write any device command "
            "or vendor configuration; a vendor adapter will translate the intent.\n\n"
            f"OBJECTIVE: {objective}\nCONFIRMED ROOT CAUSE: {root_cause}\n{ev}{allow}"
            "\nReturn STRICT JSON only:\n"
            '{"name": "<snake_case intent, e.g. ignore_protocol_mtu>", '
            '"params": {"protocol": "<e.g. ospf>", "interface": "<optional>"}, '
            '"rationale": "<why this resolves the root cause>"}\n'
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

    def synthesize_answer(self, query: str, materials: List[Dict[str, str]]) -> str:
        """Synthesizes ONE short, coherent answer from the real material
        actually retrieved this session (RAG hits + vendor doc/MCP
        lookups) -- each claim attributed inline to which source backed
        it. Same shape as a search engine's own AI-overview answer (one
        synthesized paragraph citing "Vendor Docs +2", not a bare
        source list) -- the gap identified directly from a user's own
        Google AI Overview screenshot: multiple real sources synthesized
        into one cited answer, which this tool's grounding could already
        retrieve but never presented this way.

        Deliberately never invents a source: if `materials` is empty
        (nothing was actually retrieved this session), the caller should
        skip calling this at all -- there is nothing real to synthesize,
        and fabricating one would violate the same "never let something
        ungrounded look like a grounded conclusion" discipline the whole
        grounding/citation system already follows. Kept as a defensive
        check here too, not just at the call site."""
        if not materials:
            return ""
        numbered = "\n\n".join(
            f"[{i + 1}] Source: {m.get('source', '?')} — {m.get('title', '?')}\n{m.get('text', '')[:600]}"
            for i, m in enumerate(materials)
        )
        prompt = (
            "You are synthesizing ONE short, coherent answer from the numbered "
            "sources below, the way a search engine's AI overview does -- 2-4 "
            "sentences of plain prose, citing the source number inline in "
            "square brackets right after each claim it backs (e.g. \"NAT "
            "translates private addresses to public ones [1].\"). Only state "
            "what the sources actually say — never invent a source number "
            "that isn't listed, and never add a claim no source supports. If "
            "the sources disagree or don't cover the question, say so "
            "plainly instead of guessing.\n\n"
            f"QUESTION: {query}\n\nSOURCES:\n{numbered}\n\n"
            "Return the synthesized answer only — no preamble, no JSON, no "
            "restating the question."
        )
        return (self.ai(prompt) or "").strip()
