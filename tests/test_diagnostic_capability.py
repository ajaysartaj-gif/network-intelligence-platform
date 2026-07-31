"""Shape tests for the Diagnostic Capability Framework's data model."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.diagnostics.capability import (
    DiagnosticActionSpec, DiagnosticCapability, Precondition, PreconditionKind,
)


def test_precondition_kind_has_the_fixed_generic_vocabulary():
    assert {k.value for k in PreconditionKind} == {"cpu_below", "memory_below", "logging_buffered"}


def test_capability_carries_every_field_the_framework_requires():
    cap = DiagnosticCapability(
        technology="ospf", action="adjacency_debug", description="x",
        safety_level="low", preconditions=[Precondition(kind=PreconditionKind.CPU_BELOW, threshold=50.0)],
        max_duration_s=10, expected_evidence="neighbor state transitions",
    )
    assert cap.technology == "ospf"
    assert cap.requires_governance is True  # default
    assert cap.preconditions[0].kind == PreconditionKind.CPU_BELOW


def test_action_spec_defaults_are_ios_wide_not_per_technology():
    spec = DiagnosticActionSpec(enable_commands=["debug ip ospf adj"])
    assert spec.disable_command == "undebug all"
    assert spec.verify_command == "show debugging"
    assert spec.enable_commands == ["debug ip ospf adj"]
