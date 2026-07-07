"""
Replay of the exact OSPF investigation through the REAL TroubleshootingEngine.

The SAME fake LLM and SAME device scenario are used for baseline and patched runs.
The fake reacts only to WHAT it is asked (prompt content) and to the hypothesis
ids the engine supplies — exactly as a real model would. Any difference in outcome
therefore comes from the engine code, not from feeding different answers.

Run on pristine HEAD  -> baseline (reproduces: near-tie, no fix).
Run after patches     -> resolved (fix generated).
"""
import json, re, sys, types
sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))

from core.troubleshooting.engine import TroubleshootingEngine, TSConfig


class Dev:
    def __init__(self, ip): self.ip = ip; self.hostname = ip; self.device_type = "cisco_ios"


DEVICES = [Dev("192.168.96.136"), Dev("192.168.21.2"), Dev("192.168.20.2")]


def fake_ai(prompt: str) -> str:
    p = prompt.lower()
    ids = re.findall(r"\[(hyp_[0-9a-f]+)\]", prompt)   # ids the engine put in the prompt

    if "restate this network troubleshooting request" in p:
        return "Determine why OSPF routes are absent from the routing table."

    if "propose candidate root causes" in p:
        # Two near-duplicate COARSE causes, both declaring their REAL discriminating
        # signals (network type + neighbor state) — never 'interface status'.
        return json.dumps([
            {"statement": "OSPF network type mismatch on the transit interface",
             "rationale": "type mismatch prevents adjacency/route exchange",
             "discriminating_signals": ["ospf network type", "ospf neighbor state"],
             "prior": 0.2},
            {"statement": "OSPF network type misconfiguration on the transit interface",
             "rationale": "wrong network type on the interface",
             "discriminating_signals": ["ospf network type", "ospf neighbor state"],
             "prior": 0.2},
        ])

    if "choose the next read-only diagnostic" in p:
        # If the planner now surfaces the discriminating signals (patched), target
        # them. Otherwise fall back to a generic interface probe (baseline).
        if "ospf network type" in p:
            return json.dumps([{"device": "all", "command": "show ip ospf interface",
                                "purpose": "read ospf network type + neighbor state",
                                "tests_hypotheses": ids, "value": 0.95}])
        return json.dumps([{"device": "all", "command": "show interfaces status",
                            "purpose": "interface status", "tests_hypotheses": ids, "value": 0.6}])

    if "interpret this device output" in p:
        if "show ip ospf interface" in p:
            # the REAL discriminating fact: a network-type mismatch (strong support)
            return json.dumps({
                "facts": [{"subject": "ospf.network_type", "attribute": "value", "value": "non-broadcast"}],
                "impacts": [{"hypothesis_id": i, "effect": "support", "weight": 0.95,
                             "reason": "ospf network type mismatch"} for i in ids]})
        # generic interface output: model asserts it "supports" BOTH causes — the
        # junk association that the gate must reject.
        return json.dumps({
            "facts": [{"subject": "interface.status", "attribute": "state", "value": "up"}],
            "impacts": [{"hypothesis_id": i, "effect": "support", "weight": 0.9,
                         "reason": "interface is up"} for i in ids]})

    if "produce the minimum safe configuration" in p:
        return json.dumps({
            "config_commands": ["(on all) interface Gi0/0", "(on all) ip ospf network broadcast"],
            "rollback_commands": ["(on all) no ip ospf network broadcast"],
            "explanation": "align OSPF network type on both ends"})

    if "list the read-only commands that will confirm" in p or "confirm the issue is resolved" in p:
        return json.dumps({"commands": ["show ip ospf neighbor", "show ip route ospf"],
                           "success_criteria": "neighbors FULL and OSPF routes present"})

    return "{}"


def fake_collect(device, cmds):
    return {c: f"[{device.ip}] simulated output for {c}" for c in cmds}


def main():
    eng = TroubleshootingEngine(
        ai_call=fake_ai, devices=DEVICES,
        collector=fake_collect,
        validator=lambda c: c.lower().startswith("show"),
        grounder=lambda q, d: "OSPF routing troubleshooting: verify neighbor state, then network type.",
        fix_validator=lambda cmds, alld, dr: "validated",
        config=TSConfig(max_steps=6),
    )
    rep = eng.run("OSPF routing table is not showing")
    s = rep.session
    ranked = s.ranked()
    print("STATUS      :", s.status.value)
    print("HYPOTHESES  :", len(s.hypotheses), "created;", len(ranked), "live")
    for h in ranked:
        print(f"   {h.confidence:>6.0%}  {h.statement}  (evidence={len(h.evidence_ids)})")
    print("FIX         :", "GENERATED" if s.fix and s.fix.config_commands else "NONE")
    if s.fix and s.fix.config_commands:
        for c in s.fix.config_commands:
            print("    +", c)
    print("VERIFICATION:", "present" if s.verification and s.verification.commands else "none")


if __name__ == "__main__":
    main()
