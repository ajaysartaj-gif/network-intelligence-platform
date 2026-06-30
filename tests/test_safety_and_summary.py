"""
AI Assistant · safety + concise summary (correcting existing behavior)
======================================================================
Locks two corrections requested by the operator:
  1) debug / monitor / test / clear / reload are NEVER auto-run.
  2) the chat shows a SHORT colour-coded summary, never raw command output.

Run: python -m tests.test_safety_and_summary
"""
from __future__ import annotations

import types
from core.intent_engine import IntentEngine, IntentResult, DiagnosticPlan, DeviceResult


def test_dangerous_commands_are_never_read_only():
    for cmd in ("debug ip ospf adj", "debug all", "undebug all", "monitor capture x",
                "test crash", "clear ip ospf process", "reload", "terminal monitor"):
        assert IntentEngine.is_dangerous(cmd), cmd
        assert not IntentEngine.is_read_only(cmd), cmd
    # ordinary read-only checks remain allowed
    for cmd in ("show ip ospf neighbor", "ping 1.1.1.1", "display interface"):
        assert IntentEngine.is_read_only(cmd) and not IntentEngine.is_dangerous(cmd)


def test_filter_drops_dangerous_keeps_show():
    out = IntentEngine._filter_read_only({
        "10.0.0.1": ["show ip ospf neighbor", "debug ip ospf adj", "monitor capture c"],
    })
    assert out["10.0.0.1"] == ["show ip ospf neighbor"]      # debug + monitor dropped


def test_execute_plan_blocks_debug_even_if_planned():
    dev = types.SimpleNamespace(ip="10.0.0.1", hostname="R1", device_type="cisco_ios")
    ran = {"cmds": []}

    def fake_ai(_):
        return "VERDICT: HEALTHY\nROOT_CAUSE: none\nIMPACT: none\nDIAGNOSIS_COMPLETE"

    eng = IntentEngine(ai_call=fake_ai, approved_devices=[dev])

    def _collect(d, cmds):
        ran["cmds"] += list(cmds)
        return DeviceResult(ip=d.ip, hostname=d.hostname, commands_run=list(cmds),
                            outputs={c: "..." for c in cmds}, connected=True)
    eng._ssh_collect = _collect

    plan = DiagnosticPlan(query="check ospf",
                          commands_per_device={"10.0.0.1": ["show ip ospf neighbor",
                                                            "debug ip ospf adj"]},
                          devices=[{"ip": "10.0.0.1", "hostname": "R1"}])
    eng.execute_plan(plan, [dev])
    assert "debug ip ospf adj" not in ran["cmds"]            # debug never executed
    assert "show ip ospf neighbor" in ran["cmds"]


def test_summary_is_short_and_colour_coded_no_raw_output():
    analysis = (
        "VERDICT: PROBLEM\n"
        "FINDINGS:\n"
        "- [CRIT] all neighbors DOWN/DROTHER, hellos not exchanged\n"
        "- [WARN] every router elects itself DR (no BDR)\n"
        "- [OK] timers and area match\n"
        "ROOT_CAUSE: L2 between peers is not passing OSPF hellos\n"
        "IMPACT: no OSPF routes learned between sites\n"
        "DIAGNOSIS_COMPLETE")
    html = IntentEngine._render_summary(analysis)
    assert "PROBLEM" in html and "Root cause" in html
    assert "#f87171" in html and "#34d399" in html          # red + green colour logic
    assert "show ip ospf" not in html                       # no raw command output
    assert "DIAGNOSIS_COMPLETE" not in html                 # internal tag stripped


def test_summary_falls_back_when_model_ignores_format():
    html = IntentEngine._render_summary("just some freeform text without tags")
    assert "freeform text" in html


def _run_all():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"PASS {name}")
    print("\nALL SAFETY + SUMMARY TESTS PASSED")


if __name__ == "__main__":
    _run_all()
