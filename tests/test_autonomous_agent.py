"""
Autonomous AI Assistant · Behavioral Tests
==========================================
These tests deliberately use THROWAWAY, RANDOM command tokens — never real
network commands — to prove the engine is command-agnostic. The point the tests
must guarantee: whatever the model emits today (OSPF) or tomorrow (BGP, MPLS, a
command that doesn't exist yet), the engine classifies it by STRUCTURE, runs
read-only work autonomously, and routes every WRITE through a human. No
troubleshooting knowledge is encoded here, because none should be encoded
anywhere.

Run: python -m tests.test_autonomous_agent
"""
from __future__ import annotations

import types
import uuid
from core.intent_engine import IntentEngine, DiagnosticPlan, DeviceResult


def _dev(ip, hn):
    return types.SimpleNamespace(ip=ip, hostname=hn, device_type="cisco_ios", ssh_port=22)


def _rand():
    return uuid.uuid4().hex[:6]


# ── 1) The classifier is STRUCTURAL, not a lookup table ──────────────────────
def test_read_only_is_decided_by_structure_not_a_command_list():
    ro = IntentEngine.is_read_only
    # ANY argument after a read verb → read-only (random args, not memorized commands)
    for verb in ("show", "ping", "traceroute", "display"):
        assert ro(f"{verb} {_rand()} {_rand()}"), verb
    # ANY string carrying a config/mutating marker → NOT read-only
    for marker in ("interface", "ip", "no", "clear", "write", "router", "crypto"):
        assert not ro(f"{marker} {_rand()}"), marker
    # an unknown verb the engine has never seen is treated as NOT read-only (safe default)
    assert not ro(f"{_rand()} {_rand()}")


def _engine(analysis_sequence, verify="RESOLVED"):
    """Build an engine whose 'AI' emits RANDOM commands — so passing the test
    cannot depend on any specific command string."""
    devices = [_dev("10.0.0.1", "R1"), _dev("10.0.0.2", "R2")]
    seq = {"i": 0}
    captured = {"ran": [], "applied": []}

    def fake_ai(prompt: str) -> str:
        if "Is the issue RESOLVED" in prompt:
            return verify
        out = analysis_sequence[min(seq["i"], len(analysis_sequence) - 1)]
        seq["i"] += 1
        return out

    eng = IntentEngine(ai_call=fake_ai, approved_devices=devices)
    # plan returns RANDOM read-only commands (only the read verb is fixed; args random)
    eng._ai_generate_plan = lambda q, d, sc, so, sd: DiagnosticPlan(
        query=q, commands_per_device={"10.0.0.1": [f"show {_rand()}"],
                                      "10.0.0.2": [f"show {_rand()}"]},
        devices=[{"ip": "10.0.0.1", "hostname": "R1"}, {"ip": "10.0.0.2", "hostname": "R2"}],
        round_index=1)

    def _collect(dev, cmds):
        captured["ran"] += list(cmds)
        return DeviceResult(ip=dev.ip, hostname=dev.hostname, commands_run=list(cmds),
                            outputs={c: "..." for c in cmds}, connected=True)
    eng._ssh_collect = _collect
    eng._ssh_apply = lambda dev, cmds: captured["applied"].extend(cmds) or "ok"
    return eng, devices, captured


# ── 2) Read-only autonomy + write ALWAYS gated by a human (policy) ───────────
def test_readonly_runs_autonomously_but_write_is_held_for_human():
    rid = _rand()
    analysis = [
        # round 1: inconclusive → propose a RANDOM read-only next command
        f"INCONCLUSIVE.\n[NEXT] (on R1) show {rid}\n[NEXT] (on R2) show {rid}\nNEXT_STEP_REQUIRED",
        # round 2: a fix is found — uses a RANDOM config token, not a real command
        f"ROOT CAUSE: found.\nFIX:\n[CONFIG] (on R2) ip {rid} {rid}\n"
        f"--- ROLLBACK ---\n[ROLLBACK] (on R2) no ip {rid}\nAPPROVAL_REQUIRED",
    ]
    eng, devices, cap = _engine(analysis, verify="RESOLVED")
    assert eng.REQUIRE_HUMAN_APPROVAL_FOR_WRITES is True      # hardcoded policy invariant

    res = eng.run_autonomous("any question at all", devices, max_rounds=4, auto_fix=True)

    # the read-only rounds ran with no human gate …
    assert res.autonomous
    assert [t["verdict"] for t in res.trace if "verdict" in t] == ["next", "fix"]
    assert cap["ran"]                                         # read-only commands executed
    assert all(IntentEngine.is_read_only(c) for c in cap["ran"])
    # … but the WRITE was NOT applied — it is held for a human
    assert res.needs_approval and res.fix_commands
    assert res.applied is False and cap["applied"] == []     # nothing written autonomously
    assert any(t.get("awaiting_human") for t in res.trace)


# ── 3) Policy can be disabled ONLY explicitly (e.g. a lab) → then it applies ─
def test_write_applies_only_when_policy_explicitly_disabled():
    rid = _rand()
    analysis = [f"ROOT CAUSE.\nFIX:\n[CONFIG] (on R2) ip {rid} {rid}\n"
                f"--- ROLLBACK ---\n[ROLLBACK] (on R2) no ip {rid}\nAPPROVAL_REQUIRED"]
    eng, devices, cap = _engine(analysis, verify="RESOLVED")
    eng.REQUIRE_HUMAN_APPROVAL_FOR_WRITES = False             # explicit opt-out

    res = eng.run_autonomous("any question", devices, max_rounds=2, auto_fix=True)
    assert res.applied and res.verified and cap["applied"]    # now (and only now) it writes


def _run_all():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"PASS {name}")
    print("\nALL AUTONOMOUS-AGENT TESTS PASSED")


if __name__ == "__main__":
    _run_all()
