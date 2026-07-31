"""Regression for the technology-agnostic diagnostic runtime.

Generalizes what was previously tested against a single hardcoded OSPF/HSRP/
VRRP debug executor: every rule here is proven against TWO different
registered technologies (ospf, hsrp) via the SAME executor code path, to
confirm there is no technology-specific branch hiding anywhere.
"""
import dataclasses
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.diagnostics import executor as ex
from core.diagnostics import registry
from core.diagnostics.capability import Precondition, PreconditionKind

CPU_LOW = "CPU utilization for five seconds: 8%/2%; one minute: 10%; five minutes: 9%"
CPU_HIGH = "CPU utilization for five seconds: 73%/10%; one minute: 60%; five minutes: 50%"
MEM_LOW = "Total: 100000  Used: 30%  Free: 70%"
MEM_HIGH = "Total: 100000  Used: 91%  Free: 9%"
LOGGING_BUFFERED = "Buffered logging: level debugging, 37 messages logged, xml disabled"
LOGGING_DISABLED = "Buffered logging: disabled, filtering disabled"
NO_DEBUG_ACTIVE = ""
DEBUG_STILL_ON = "OSPF:\n  OSPF adjacency and flooding debugging is on"


def _run_commands_factory(responses):
    calls = []

    def _run(commands):
        calls.append(list(commands))
        return {c: responses.get(c, "") for c in commands}

    _run.calls = calls
    return _run


@pytest.fixture(params=["ospf", "hsrp"])
def technology(request):
    return request.param


def _capability_and_spec(technology):
    cap = registry.get_capability(technology)
    spec = registry.get_action_spec("ios-like", technology)
    return cap, spec


def _happy_responses(cap, spec):
    return {
        spec.cpu_check_command: CPU_LOW,
        spec.logging_check_command: LOGGING_BUFFERED,
        spec.verify_command: NO_DEBUG_ACTIVE,
    }


def test_cpu_precondition_refuses_when_already_elevated(technology):
    cap, spec = _capability_and_spec(technology)
    run = _run_commands_factory({spec.cpu_check_command: CPU_HIGH})
    result = ex.run_diagnostic(cap, spec, "10.0.0.1", run)
    assert result.refused
    assert "CPU" in result.refusal_reason
    assert all(spec.logging_check_command not in c for c in run.calls)  # never reached


def test_cpu_precondition_refuses_when_output_unparseable(technology):
    cap, spec = _capability_and_spec(technology)
    run = _run_commands_factory({spec.cpu_check_command: "garbage"})
    result = ex.run_diagnostic(cap, spec, "10.0.0.1", run)
    assert result.refused
    assert "could not parse" in result.refusal_reason


def test_logging_precondition_refuses_when_disabled(technology):
    cap, spec = _capability_and_spec(technology)
    run = _run_commands_factory({
        spec.cpu_check_command: CPU_LOW, spec.logging_check_command: LOGGING_DISABLED,
    })
    result = ex.run_diagnostic(cap, spec, "10.0.0.1", run)
    assert result.refused
    assert "buffered logging" in result.refusal_reason


def test_memory_precondition_is_a_generic_interpreter_not_a_technology_special_case():
    """MEMORY_BELOW isn't used by ospf/hsrp/vrrp today, but the SAME generic
    interpreter must handle it for any future capability that adds it --
    proving preconditions are a fixed vocabulary, not per-technology code."""
    cap, spec = _capability_and_spec("ospf")
    cap = dataclasses.replace(
        cap, preconditions=[Precondition(kind=PreconditionKind.MEMORY_BELOW, threshold=80.0)])
    run = _run_commands_factory({spec.memory_check_command: MEM_HIGH})
    result = ex.run_diagnostic(cap, spec, "10.0.0.1", run)
    assert result.refused
    assert "memory" in result.refusal_reason


def test_happy_path_enables_collects_and_cleans_up(monkeypatch, technology):
    monkeypatch.setattr(ex.time, "sleep", lambda s: None)
    cap, spec = _capability_and_spec(technology)
    run = _run_commands_factory(_happy_responses(cap, spec))

    result = ex.run_diagnostic(cap, spec, "10.0.0.1", run, duration_seconds=5)

    assert not result.refused
    assert result.cleanly_disabled is True
    assert result.started_at and result.ended_at
    assert [spec.disable_command, spec.verify_command] in run.calls
    assert list(spec.enable_commands) in run.calls


def test_cleanup_still_runs_when_collection_raises(monkeypatch, technology):
    monkeypatch.setattr(ex.time, "sleep", lambda s: None)
    cap, spec = _capability_and_spec(technology)
    responses = _happy_responses(cap, spec)

    def flaky_run(commands):
        if commands == list(spec.enable_commands):
            raise RuntimeError("SSH connection dropped mid-command")
        return {c: responses.get(c, "") for c in commands}

    result = ex.run_diagnostic(cap, spec, "10.0.0.1", flaky_run)

    assert "SSH connection dropped" in result.error
    assert result.cleanly_disabled is True  # cleanup still happened and verified clean
    assert result.ended_at


def test_cleanup_failure_is_recorded_not_swallowed(monkeypatch, technology):
    monkeypatch.setattr(ex.time, "sleep", lambda s: None)
    cap, spec = _capability_and_spec(technology)
    responses = _happy_responses(cap, spec)

    def flaky_cleanup(commands):
        if commands == [spec.disable_command, spec.verify_command]:
            raise RuntimeError("device unreachable")
        return {c: responses.get(c, "") for c in commands}

    result = ex.run_diagnostic(cap, spec, "10.0.0.1", flaky_cleanup)
    assert "cleanup failed" in result.error
    assert result.cleanly_disabled is False


def test_verify_detects_debugging_still_active():
    pattern = r"debugging is on"
    assert ex._verify_cleanly_disabled(NO_DEBUG_ACTIVE, pattern) is True
    assert ex._verify_cleanly_disabled(DEBUG_STILL_ON, pattern) is False


def test_duration_is_hard_capped_even_if_a_larger_value_is_requested(monkeypatch, technology):
    monkeypatch.setattr(ex.time, "sleep", lambda s: None)
    cap, spec = _capability_and_spec(technology)
    run = _run_commands_factory(_happy_responses(cap, spec))
    result = ex.run_diagnostic(cap, spec, "10.0.0.1", run, duration_seconds=999)
    assert result.requested_duration_s <= ex.MAX_DURATION_SECONDS


def test_refuses_when_action_spec_has_no_enable_commands():
    cap, _ = _capability_and_spec("ospf")
    from core.diagnostics.capability import DiagnosticActionSpec
    empty_spec = DiagnosticActionSpec(enable_commands=[])
    run = _run_commands_factory({})
    result = ex.run_diagnostic(cap, empty_spec, "10.0.0.1", run)
    assert result.refused
    assert run.calls == []
