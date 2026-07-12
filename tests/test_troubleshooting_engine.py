"""Tests for the autonomous troubleshooting engine (no network / no real LLM)."""
import json
import re
import sys
import types
from pathlib import Path

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.troubleshooting import TroubleshootingEngine, TSConfig, ResolutionStatus
from core.troubleshooting.memory import ExecutedCommandsMemory, normalize_command


class Dev:
    def __init__(self, ip, hn):
        self.ip, self.hostname, self.device_type = ip, hn, "cisco_ios"


DEVICES = [Dev("10.0.0.1", "R1"), Dev("10.0.0.2", "R2"), Dev("10.0.0.3", "R3")]


def _hyp_id(prompt, needle):
    m = re.search(r"\[(hyp_[0-9a-f]+)\]\s*" + re.escape(needle), prompt)
    return m.group(1) if m else None


def make_ai(support_weight=0.4, mode="converge"):
    """Scripted model. `mode` = converge | neutral."""
    plan_cmds = ["show ip ospf interface", "show ip ospf neighbor detail",
                 "show interfaces", "show running-config ospf"]

    def ai(prompt: str) -> str:
        if "Restate this network troubleshooting" in prompt:
            return "Determine why OSPF adjacencies are not forming."
        if "candidate ROOT CAUSES" in prompt:
            return json.dumps([
                {"statement": "MTU mismatch between OSPF neighbors",
                 "rationale": "EXSTART is the classic MTU signature",
                 "discriminating_signals": ["interface MTU differs across peers"], "prior": 0.3},
                {"statement": "OSPF hello/dead timer mismatch",
                 "rationale": "timers can block adjacency", "prior": 0.2},
            ])
        if "NEXT read-only diagnostic command" in prompt:
            already = ""
            m = re.search(r"ALREADY RUN[^\n]*\n([^\n]*)", prompt)
            if m:
                already = m.group(1)
            out = []
            for i, c in enumerate(plan_cmds):
                if normalize_command(c) in already:
                    continue
                out.append({"device": "all", "command": c, "purpose": "diag",
                            "tests_hypotheses": [], "value": 0.9 - i * 0.1})
            return json.dumps(out[:3])
        if "Interpret this device output" in prompt:
            mtu = _hyp_id(prompt, "MTU mismatch between OSPF neighbors")
            timer = _hyp_id(prompt, "OSPF hello/dead timer mismatch")
            impacts = []
            if mode == "converge":
                if mtu:
                    impacts.append({"hypothesis_id": mtu, "effect": "support",
                                    "weight": support_weight, "reason": "MTU differs"})
                if timer:
                    impacts.append({"hypothesis_id": timer, "effect": "contradict",
                                    "weight": 0.5, "reason": "timers match"})
            # neutral mode: no impacts. silent mode: no facts either — simulates
            # the LLM reporting NOTHING interpretable, so engine.
            # _bind_compiled_signature_evidence (which reads session.observations,
            # not just LLM impacts) also has no observed state to act on.
            facts = ([] if mode == "silent" else
                    [{"subject": "ospf.neighbor", "attribute": "state", "value": "EXSTART"}])
            return json.dumps({
                "facts": facts,
                "impacts": impacts,
            })
        if "MINIMUM safe configuration" in prompt:
            return json.dumps({
                "config_commands": ["(on 10.0.0.1) ip ospf mtu-ignore"],
                "rollback_commands": ["(on 10.0.0.1) no ip ospf mtu-ignore"],
                "explanation": "Aligns OSPF MTU handling so adjacency can progress past EXSTART.",
            })
        if "CONFIRM the issue is resolved" in prompt:
            return json.dumps({"commands": ["show ip ospf neighbor"],
                               "success_criteria": "All neighbors reach FULL."})
        return ""
    return ai


def build_engine(ai, cfg=None):
    collector = lambda dev, cmds: {cmds[0]: "Neighbor 2.2.2.2 state EXSTART, MTU 1500"}
    return TroubleshootingEngine(
        ai_call=ai, devices=DEVICES,
        collector=collector,
        validator=lambda c: c.lower().strip().startswith("show"),
        grounder=lambda q, d: "",
        fix_validator=lambda cmds, ad, dr: "✅ 1 ok · 0 blocked",
        config=cfg or TSConfig(),
    )


def test_converges_to_fix_with_traceable_evidence():
    eng = build_engine(make_ai())
    report = eng.run("why do I see OSPF issues")
    s = report.session

    assert s.status == ResolutionStatus.RESOLVED_PENDING_APPROVAL, s.status
    top = s.top()
    assert top and "MTU" in top.statement
    assert top.confidence >= 0.8
    # traceability: the confirmed hypothesis cites the evidence that moved it
    assert top.evidence_ids, "root cause must be traceable to evidence"
    assert all(d.evidence_id for d in top.deltas)
    # fix is approval-gated (never auto-applied) and has rollback + verification
    assert s.fix and s.fix.config_commands and s.fix.rollback_commands
    assert s.verification and s.verification.commands
    print("[1] converge→fix, traceable, approval-gated: PASS")


def test_no_command_ever_repeats():
    eng = build_engine(make_ai())
    report = eng.run("ospf issue")
    seen = set()
    for c in report.session.executed:
        if c.reused:
            continue
        key = (c.device, normalize_command(c.command))
        assert key not in seen, f"command re-executed: {key}"
        seen.add(key)
    print("[2] no duplicate execution: PASS")


def test_confidence_only_moves_on_evidence():
    eng = build_engine(make_ai())
    report = eng.run("ospf issue")
    for h in report.session.hypotheses:
        for d in h.deltas:
            if d.effect.value == "support":
                assert d.log_odds_change > 0
            elif d.effect.value == "contradict":
                assert d.log_odds_change < 0
    print("[3] confidence rises on support, falls on contradiction: PASS")


def test_report_has_all_expected_fields():
    eng = build_engine(make_ai())
    d = eng.run("ospf issue").to_dict()
    for key in ["goal", "current_state", "active_hypotheses", "evidence_summary",
                "executed_commands", "next_best_command", "confidence_score",
                "likely_root_cause", "recommended_fix", "verification_plan",
                "final_resolution_status"]:
        assert key in d, f"missing output field: {key}"
    print("[4] structured report complete: PASS")


def test_escalates_instead_of_guessing():
    # Neither the LLM (mode="silent" → no facts, no impacts) NOR
    # deterministic extraction (no IP+state pattern in this output, so
    # core.knowledge.compiler.semantic_analyzer's neighbor extractor finds
    # nothing and engine._bind_compiled_signature_evidence has no observed
    # state to bind) contributes usable evidence here → engine must NOT
    # invent a root cause. build_engine()'s shared collector output
    # ("Neighbor 2.2.2.2 state EXSTART...") is deliberately NOT used for
    # this test: since the engine now also binds evidence from compiled
    # failure signatures against a deterministically-observed protocol
    # state (independent of the LLM), that canned output legitimately DOES
    # count as real evidence and would converge here — correctly, not a bug.
    collector = lambda dev, cmds: {cmds[0]: "GigabitEthernet0/0 is up, line protocol is up"}
    eng = TroubleshootingEngine(
        ai_call=make_ai(mode="silent"), devices=DEVICES,
        collector=collector,
        validator=lambda c: c.lower().strip().startswith("show"),
        grounder=lambda q, d: "",
        fix_validator=lambda cmds, ad, dr: "✅ 1 ok · 0 blocked",
        config=TSConfig(max_steps=5, patience=2),
    )
    s = eng.run("ospf issue").session
    assert s.status in (ResolutionStatus.ESCALATE, ResolutionStatus.LIKELY_CAUSE_PRESENT)
    assert s.fix is None, "must not fabricate a fix without sufficient evidence"
    print("[5] escalates rather than guessing: PASS")


def test_compiled_signature_converges_without_llm_impacts():
    # The compiled-signature evidence path is deterministic and independent
    # of the LLM's own impact judgments: even with mode="neutral" (LLM
    # reports the observed EXSTART fact but deliberately contributes zero
    # impacts), the observed state alone should let the matching compiled
    # signature (ExStart -> MTU mismatch) converge, since it's real,
    # directly-observed evidence, not an invented one.
    eng = build_engine(make_ai(mode="neutral"), cfg=TSConfig(max_steps=5, patience=2))
    s = eng.run("ospf issue").session
    assert s.status == ResolutionStatus.RESOLVED_PENDING_APPROVAL, s.status
    top = s.top()
    assert top and "MTU" in top.statement
    assert any(src.startswith("compiled failure signature") for src in s.knowledge_sources)
    print("[5b] compiled signature converges from observed state alone: PASS")


def test_record_ambiguous_outcome_feeds_recurring_failure_detection_for_escalate(monkeypatch):
    """Broadened learning gap: sessions that ESCALATE or stay at
    LIKELY_CAUSE_PRESENT never reach a human Confirm/Deny click on a
    deployed fix (core.copilot_engine._record_ts_outcome), so before this
    they were invisible to NetworkIntelligenceSupplyChain's
    recurring-failure detection even though "investigated repeatedly,
    never confirmed" is itself worth surfacing."""
    calls = []

    class _StubSupplyChain:
        def record_failed_resolution(self, intent, device, *, reason="", commands=None,
                                     site="", protocol="", operator=""):
            calls.append({"intent": intent, "device": device, "reason": reason, "protocol": protocol})
            return []

    import core.knowledge.compiler.supply_chain as sc_mod
    monkeypatch.setattr(sc_mod, "NetworkIntelligenceSupplyChain", _StubSupplyChain)

    from core.troubleshooting.models import Goal, Session

    eng = TroubleshootingEngine(ai_call=lambda p: "", devices=DEVICES)
    session = Session(goal=Goal(query="why is ospf stuck", objective="diagnose", devices=["10.0.0.1"]))
    session.status = ResolutionStatus.ESCALATE
    session.escalation_reason = "evidence was insufficient"

    eng._record_ambiguous_outcome(session)

    assert calls, "ESCALATE must record a failed-resolution event for recurrence detection"
    assert calls[0]["device"] == "10.0.0.1"
    assert calls[0]["reason"] == "evidence was insufficient"
    print("[6] ambiguous/escalated outcome feeds recurring-failure detection: PASS")


def test_record_ambiguous_outcome_is_a_noop_for_terminal_and_in_progress_states(monkeypatch):
    calls = []

    class _StubSupplyChain:
        def record_failed_resolution(self, *a, **k):
            calls.append((a, k))
            return []

    import core.knowledge.compiler.supply_chain as sc_mod
    monkeypatch.setattr(sc_mod, "NetworkIntelligenceSupplyChain", _StubSupplyChain)

    from core.troubleshooting.models import Goal, Session

    eng = TroubleshootingEngine(ai_call=lambda p: "", devices=DEVICES)
    for status in (ResolutionStatus.RESOLVED_PENDING_APPROVAL, ResolutionStatus.HEALTHY,
                   ResolutionStatus.IN_PROGRESS, ResolutionStatus.RESOLVED, ResolutionStatus.UNRESOLVED):
        session = Session(goal=Goal(query="q", objective="o", devices=["10.0.0.1"]))
        session.status = status
        eng._record_ambiguous_outcome(session)
    assert not calls, "must only fire for ESCALATE/LIKELY_CAUSE_PRESENT"
    print("[6b] ambiguous-outcome recording correctly skips non-ambiguous states: PASS")


def test_session_close_sets_terminal_resolution_status():
    from core.troubleshooting.models import Session

    resolved = Session()
    resolved.close(resolved=True)
    assert resolved.status == ResolutionStatus.RESOLVED

    unresolved = Session()
    unresolved.close(resolved=False)
    assert unresolved.status == ResolutionStatus.UNRESOLVED
    print("[6c] Session.close() sets the terminal status: PASS")


def test_ai_error_string_never_leaks_into_goal_objective_or_hypotheses():
    """Regression: app.py's plain-chat ai_call deliberately returns
    f"AI Error: {err}" as a visible string (so a human sees it inline in
    chat) rather than raising. Every reasoning.py call site does
    `self.ai(prompt) or <fallback>`, which treats ANY non-empty string as
    a real answer — so a transient API outage was silently overwriting
    session.goal.objective with the literal text "AI Error: Connection
    error." instead of falling back to the raw query, making a live
    outage indistinguishable from a real (garbage) AI response in the
    user-facing report."""
    from core.troubleshooting.reasoning import Reasoner

    def failing_ai(_prompt: str) -> str:
        return "AI Error: Connection error."

    r = Reasoner(failing_ai)
    assert r.ai("anything") == ""
    # phrase_objective's own fallback (`self.ai(prompt) or query`) must
    # therefore fall through to the real query, never the error string.
    objective = r.phrase_objective("why is ospf down")
    assert objective == "why is ospf down"
    assert "AI Error" not in objective


def test_ai_error_string_does_not_break_full_engine_run():
    collector = lambda dev, cmds: {cmds[0]: "GigabitEthernet0/0 is up, line protocol is up"}
    eng = TroubleshootingEngine(
        ai_call=lambda _p: "AI Error: Connection error.",
        devices=DEVICES,
        collector=collector,
        validator=lambda c: c.lower().strip().startswith("show"),
        grounder=lambda q, d: "",
        fix_validator=lambda cmds, ad, dr: "✅ 1 ok · 0 blocked",
        config=TSConfig(max_steps=3, patience=2),
    )
    s = eng.run("why is ospf down").session
    assert "AI Error" not in (s.goal.objective or "")
    assert s.goal.query == "why is ospf down"
    for h in s.hypotheses:
        assert "AI Error" not in h.statement
    print("[7] AI-error string never leaks into goal/hypotheses: PASS")


def test_memory_dedup_unit():
    m = ExecutedCommandsMemory()
    m.record("10.0.0.1", "show ip ospf neighbor", "out", "p")
    assert m.has("10.0.0.1", "SHOW  IP   OSPF neighbor")   # normalization
    assert not m.has("10.0.0.2", "show ip ospf neighbor")
    print("[6] command-memory dedup/normalize: PASS")


if __name__ == "__main__":
    test_converges_to_fix_with_traceable_evidence()
    test_no_command_ever_repeats()
    test_confidence_only_moves_on_evidence()
    test_report_has_all_expected_fields()
    test_escalates_instead_of_guessing()
    test_compiled_signature_converges_without_llm_impacts()
    test_memory_dedup_unit()
    print("\nALL TROUBLESHOOTING-ENGINE TESTS PASSED")
