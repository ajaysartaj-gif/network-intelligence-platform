"""
AI Configuration Engine — reasoning (LLM-backed)
================================================
The only place the LLM is used. Every call returns parsed, normalized Python.
Prompts are vendor-neutral and contain NO vendor names, products or commands.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List

AiCall = Callable[[str], str]


def _extract(text: str) -> Any:
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


class ConfigReasoner:
    def __init__(self, ai: AiCall) -> None:
        self.ai = ai

    def phrase_goal(self, query: str) -> dict:
        p = ("Restate this network CONFIGURATION request as a precise objective and a "
             "single high-level category (free-form, e.g. routing/switching/security). "
             "No vendor names, no commands.\n\nREQUEST: " + query +
             '\n\nSTRICT JSON: {"objective": "...", "category": "..."}')
        return _extract(self.ai(p) or "") or {}

    def parse_intent(self, objective: str, provided: dict) -> dict:
        p = ("Convert the objective into NORMALIZED configuration intent. Extract "
             "technologies, protocols, services and deployment scope. Never output vendor "
             "commands. Use generic protocol/technology names only.\n\n"
             f"OBJECTIVE: {objective}\nKNOWN INPUTS: {json.dumps(provided)}\n\n"
             'STRICT JSON: {"technologies": [], "protocols": [], "services": [], '
             '"scope": [], "intents": [{"name": "<snake_case, e.g. configure_ospf_interface>", '
             '"params": {}, "rationale": ""}]}')
        return _extract(self.ai(p) or "") or {}

    def find_missing(self, objective: str, intents: List[dict], provided: dict) -> List[dict]:
        p = ("Identify MANDATORY inputs required to safely design this configuration that "
             "are NOT present. Never assume values. Ask focused follow-up questions.\n\n"
             f"OBJECTIVE: {objective}\nINTENTS: {json.dumps(intents)}\n"
             f"PROVIDED: {json.dumps(provided)}\n\n"
             'STRICT JSON list: [{"field": "<e.g. area|asn|vlan|ip_address>", '
             '"question": "<what to ask the user>", "required": true}]')
        return _lst(_extract(self.ai(p) or ""))

    def advise_technology(self, objective: str) -> List[dict]:
        p = ("Recommend suitable technologies/approaches with trade-offs and mark the best "
             "one. Vendor-neutral only.\n\n"
             f"OBJECTIVE: {objective}\n\n"
             'STRICT JSON list: [{"name": "", "rationale": "", "tradeoffs": "", '
             '"recommended": true|false}]')
        return _lst(_extract(self.ai(p) or ""))

    def analyze_dependencies(self, objective: str, intents: List[dict]) -> List[dict]:
        p = ("List configuration dependencies (interfaces, vrfs, vlans, routing, security, "
             "licensing, platform features, existing services). Generic only.\n\n"
             f"OBJECTIVE: {objective}\nINTENTS: {json.dumps(intents)}\n\n"
             'STRICT JSON list: [{"kind": "", "detail": ""}]')
        return _lst(_extract(self.ai(p) or ""))

    def validate_design(self, objective: str, intents: List[dict]) -> List[dict]:
        p = ("Review the logical design for architectural flaws BEFORE any configuration is "
             "generated. Report issues with severity.\n\n"
             f"OBJECTIVE: {objective}\nINTENTS: {json.dumps(intents)}\n\n"
             'STRICT JSON list: [{"name": "", "severity": "info|warn|critical", '
             '"passed": true|false, "detail": ""}]')
        return _lst(_extract(self.ai(p) or ""))

    def analyze_impact(self, objective: str, intents: List[dict]) -> dict:
        p = ("Predict operational impact (traffic, service, protocol reset, resource, "
             "downtime, performance). Generic.\n\n"
             f"OBJECTIVE: {objective}\nINTENTS: {json.dumps(intents)}\n\n"
             'STRICT JSON: {"factors": [], "downtime_expected": true|false, "summary": ""}')
        return _extract(self.ai(p) or "") or {}

    def mitigations(self, drivers: List[str], objective: str) -> List[str]:
        p = ("Given these risk drivers, recommend concise mitigation strategies.\n\n"
             f"OBJECTIVE: {objective}\nDRIVERS: {json.dumps(drivers)}\n\n"
             'STRICT JSON: {"mitigations": []}')
        d = _extract(self.ai(p) or "") or {}
        return list(d.get("mitigations", []))

    def best_practices(self, objective: str) -> List[str]:
        p = ("List operational best practices for this configuration WITHOUT changing the "
             "user's intent. Generic.\n\n"
             f"OBJECTIVE: {objective}\n\nSTRICT JSON: {{\"best_practices\": []}}")
        d = _extract(self.ai(p) or "") or {}
        return list(d.get("best_practices", []))

    def plan_steps(self, intents: List[dict]) -> List[dict]:
        p = ("Order these intents into an implementation workflow with prerequisites. Never "
             "output vendor configuration.\n\n"
             f"INTENTS: {json.dumps(intents)}\n\n"
             'STRICT JSON list: [{"order": 1, "description": "", "prerequisite": ""}]')
        return _lst(_extract(self.ai(p) or ""))

    def executive_summary(self, objective: str, risk_level: str, impact: str) -> str:
        p = ("Write a 2-3 sentence executive summary for approval of this configuration "
             "change. Plain business language.\n\n"
             f"OBJECTIVE: {objective}\nRISK: {risk_level}\nIMPACT: {impact}")
        return (self.ai(p) or "").strip()
