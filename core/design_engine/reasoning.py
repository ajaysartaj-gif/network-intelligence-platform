"""
AI Design Engine — reasoning (LLM-backed, Principal-Architect persona)
=====================================================================
The only place the LLM is used. Prompts frame the model as a Principal Network
Architect that recommends ARCHITECTURES (never vendor CLI, never config, never
troubleshooting). All calls return parsed, normalized Python.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List

AiCall = Callable[[str], str]
_ARCHITECT = ("You are a Principal Network Architect. You design scalable, resilient, "
              "secure, vendor-independent architectures. You NEVER write device CLI, you "
              "NEVER produce device configuration, and you NEVER troubleshoot — you reason "
              "about architecture, technologies and trade-offs only.\n\n")


def _json(text: str) -> Any:
    if not text:
        return None
    t = re.sub(r"^```(?:json)?", "", text.strip()).strip()
    t = re.sub(r"```$", "", t).strip()
    for cand in (t, _bal(t, "{", "}"), _bal(t, "[", "]")):
        if cand:
            try:
                return json.loads(cand)
            except Exception:
                continue
    return None


def _bal(s: str, o: str, c: str) -> str:
    i = s.find(o)
    if i == -1:
        return ""
    d = 0
    for j in range(i, len(s)):
        if s[j] == o:
            d += 1
        elif s[j] == c:
            d -= 1
            if d == 0:
                return s[i:j + 1]
    return ""


def _lst(x: Any) -> List[dict]:
    if isinstance(x, list):
        return [i for i in x if isinstance(i, dict)]
    if isinstance(x, dict):
        for v in x.values():
            if isinstance(v, list):
                return [i for i in v if isinstance(i, dict)]
    return []


class DesignReasoner:
    def __init__(self, ai: AiCall) -> None:
        self.ai = ai

    def summarize(self, query: str) -> dict:
        p = (_ARCHITECT + "Summarize this request into a business summary and a technical "
             "summary.\n\nREQUEST: " + query +
             '\n\nSTRICT JSON: {"business_summary": "...", "technical_summary": "..."}')
        return _json(self.ai(p) or "") or {}

    def requirements(self, query: str) -> List[dict]:
        p = (_ARCHITECT + "Extract normalized requirements (business, technical, operational, "
             "security, compliance, performance, availability, growth). Infer reasonable ones "
             "and mark them as assumptions where not stated.\n\nREQUEST: " + query +
             '\n\nSTRICT JSON list: [{"kind": "", "detail": ""}]')
        return _lst(_json(self.ai(p) or ""))

    def constraints(self, query: str) -> List[dict]:
        p = (_ARCHITECT + "Identify design constraints (budget, technology, vendor, operational, "
             "compliance, geographical, latency, power, space, migration). If none stated, return "
             "the most likely constraints as assumptions.\n\nREQUEST: " + query +
             '\n\nSTRICT JSON list: [{"kind": "", "detail": ""}]')
        return _lst(_json(self.ai(p) or ""))

    def assess_existing(self, query: str, capabilities: List[str]) -> dict:
        caps = ", ".join(capabilities) if capabilities else "unknown"
        p = (_ARCHITECT + "Assess the existing/brownfield network implied by the request. Note "
             "bottlenecks and technical debt. If greenfield, say so.\n\n"
             f"REQUEST: {query}\nDISCOVERED CAPABILITIES: {caps}\n\n"
             'STRICT JSON: {"summary": "", "bottlenecks": [], "technical_debt": []}')
        return _json(self.ai(p) or "") or {}

    def generate_options(self, query: str, requirements: List[dict],
                        constraints: List[dict], min_options: int = 3) -> List[dict]:
        p = (_ARCHITECT + f"Generate at least {min_options} DISTINCT architecture options. Never "
             "only one. For each: architecture narrative, technologies, advantages, disadvantages, "
             "assumptions, risks, and 0-1 estimates for cost (higher=cheaper), performance, "
             "scalability, availability, security, operational_simplicity, future_readiness, "
             "vendor_independence. Vendor-neutral technology names only; no device CLI.\n\n"
             f"REQUEST: {query}\nREQUIREMENTS: {json.dumps(requirements)}\n"
             f"CONSTRAINTS: {json.dumps(constraints)}\n\n"
             'STRICT JSON list: [{"name": "", "architecture": "", "technologies": [], '
             '"advantages": [], "disadvantages": [], "assumptions": [], "risks": [], '
             '"scores": {"cost": 0.0, "performance": 0.0, "scalability": 0.0, '
             '"availability": 0.0, "security": 0.0, "operational_simplicity": 0.0, '
             '"future_readiness": 0.0, "vendor_independence": 0.0}}]')
        return _lst(_json(self.ai(p) or ""))

    def technologies(self, query: str) -> List[str]:
        p = (_ARCHITECT + "Recommend suitable networking technologies for this design "
             "(protocol/architecture names only, vendor-neutral).\n\nREQUEST: " + query +
             '\n\nSTRICT JSON: {"technologies": []}')
        d = _json(self.ai(p) or "") or {}
        return list(d.get("technologies", []))

    def capacity(self, query: str, requirements: List[dict]) -> List[dict]:
        p = (_ARCHITECT + "Estimate capacity planning dimensions (bandwidth, cpu, memory, "
             "routing_scale, address_utilization, growth). Use ranges/assumptions if numbers "
             "are absent.\n\n"
             f"REQUEST: {query}\nREQUIREMENTS: {json.dumps(requirements)}\n\n"
             'STRICT JSON list: [{"dimension": "", "current": "", "projected": "", "headroom": ""}]')
        return _lst(_json(self.ai(p) or ""))

    def risks(self, recommended_name: str, architecture: str) -> List[dict]:
        p = (_ARCHITECT + "Identify risks for the recommended architecture (spof, operational, "
             "security, migration, performance, vendor, business) with severity.\n\n"
             f"RECOMMENDED: {recommended_name}\nARCHITECTURE: {architecture}\n\n"
             'STRICT JSON list: [{"kind": "", "detail": "", "severity": "low|medium|high"}]')
        return _lst(_json(self.ai(p) or ""))

    def migration(self, recommended_name: str, existing_summary: str) -> dict:
        p = (_ARCHITECT + "Produce a migration strategy to the recommended architecture with "
             "phases, per-phase validation + rollback + downtime, and success criteria.\n\n"
             f"RECOMMENDED: {recommended_name}\nEXISTING: {existing_summary}\n\n"
             'STRICT JSON: {"strategy": "", "success_criteria": "", "phases": [{"order": 1, '
             '"name": "", "actions": "", "validation": "", "rollback": "", "downtime": ""}]}')
        return _json(self.ai(p) or "") or {}

    def operational(self, recommended_name: str) -> List[str]:
        p = (_ARCHITECT + "List operational recommendations (monitoring, automation, day-2) for "
             "the recommended architecture.\n\nRECOMMENDED: " + recommended_name +
             '\n\nSTRICT JSON: {"operational_recommendations": []}')
        d = _json(self.ai(p) or "") or {}
        return list(d.get("operational_recommendations", []))

    def documentation(self, query: str, recommended_name: str, architecture: str) -> dict:
        p = (_ARCHITECT + "Generate concise design documentation: high-level design, low-level "
             "design outline, decision log, and future recommendations.\n\n"
             f"REQUEST: {query}\nRECOMMENDED: {recommended_name}\nARCHITECTURE: {architecture}\n\n"
             'STRICT JSON: {"high_level": "", "low_level": "", "decision_log": "", '
             '"future_recommendations": []}')
        return _json(self.ai(p) or "") or {}

    def rationale(self, recommended_name: str, matrix: List[dict]) -> str:
        p = (_ARCHITECT + "In 2-3 sentences, explain WHY this option is recommended over the "
             "others, referencing the balance of scalability, resiliency, operational simplicity, "
             "security and future growth (not cost or performance alone).\n\n"
             f"RECOMMENDED: {recommended_name}\nSCORES: {json.dumps(matrix)}")
        return (self.ai(p) or "").strip()
