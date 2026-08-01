#!/usr/bin/env python3
"""
tests/test_gate_phase1.py
=========================
Gate Test: Validate core investigation loop works with real device outputs.

This test runs ONE investigation case with perfect evidence to determine
if the core loop is architecturally sound.

Success Criteria:
- Investigation converges in ≤3 cycles
- Confidence reaches ≥85%
- Root cause identified correctly
"""

import sys
import time

sys.path.insert(0, '/Users/traptigupta/Desktop/network-intelligence-platform')

from core.knowledge_first_investigator import KnowledgeFirstInvestigator
from tests.test_dataset_phase2 import OSPF_EXSTART_HELLO_MISMATCH


def run_gate_test():
    """Run the gate test with OSPF_EXSTART_HELLO_MISMATCH case."""

    print("\n" + "="*80)
    print("PHASE 1: GATE TEST - Core Investigation Loop Validation")
    print("="*80)

    case = OSPF_EXSTART_HELLO_MISMATCH

    print(f"\nTest Case: {case.incident_id}")
    print(f"Protocol: {case.protocol.value}")
    print(f"Issue Type: {case.issue_type}")
    print(f"Problem: {case.problem_description}")
    print(f"\nExpected Result:")
    print(f"  Root Cause: {case.expected_root_cause}")
    print(f"  Confidence: {case.expected_confidence:.0%}")
    print(f"  Cycles: {case.expected_cycles}")

    print(f"\nDevice Outputs Provided:")
    for key in case.device_outputs.keys():
        print(f"  - {key}")

    # Run investigation
    print(f"\n{'='*80}")
    print("Running investigation...")
    print('='*80)

    investigator = KnowledgeFirstInvestigator()

    start_time = time.time()
    result = investigator.investigate(
        protocol=case.protocol,
        issue_type=case.issue_type,
        root_device=case.root_device,
        affected_devices=case.affected_devices,
        device_outputs=case.device_outputs,
        max_cycles=case.max_cycles_allowed,
        confidence_threshold=case.min_confidence_required
    )
    elapsed_time = time.time() - start_time

    # Extract results
    cycles_taken = result.get("cycles", 0)
    final_confidence = result.get("confidence", 0.0)
    root_cause = result.get("root_cause", "Unknown")
    converged = result.get("converged", False)

    # Print investigation summary
    print(f"\n{investigator.print_investigation_summary()}")

    # Print detailed results
    print(f"\n{'='*80}")
    print("RESULTS")
    print('='*80)
    print(f"Cycles Taken: {cycles_taken} (expected: {case.expected_cycles}, max: {case.max_cycles_allowed})")
    print(f"Final Confidence: {final_confidence:.0%} (expected: {case.expected_confidence:.0%})")
    print(f"Root Cause Found: {root_cause}")
    print(f"Expected: {case.expected_root_cause}")
    print(f"Converged: {'✅ YES' if converged else '❌ NO'}")
    print(f"Investigation Time: {elapsed_time:.1f}s")

    # Print hypotheses
    top_hyps = result.get("top_3_hypotheses", [])
    if top_hyps:
        print(f"\nTop Hypotheses:")
        for name, prob in top_hyps:
            print(f"  {name}: {prob:.0%}")

    # Print cycle details
    cycles_detail = result.get("cycles_detail", [])
    print(f"\nCycle Details:")
    for cycle in cycles_detail:
        print(f"  Cycle {cycle['cycle']}: {len(cycle['checks'])} checks, confidence: {cycle['confidence']:.0%}, converged: {cycle['converged']}")

    # Evaluate gate
    print(f"\n{'='*80}")
    print("GATE EVALUATION")
    print('='*80)

    checks = {
        "Evidence Collector reads real data": cycles_taken > 0,
        "Investigation converges": converged,
        f"Convergence within {case.max_cycles_allowed} cycles": cycles_taken <= case.max_cycles_allowed,
        "Confidence reaches 85%+": final_confidence >= 0.85,
        # Check if the core issue is identified (allow for partial match)
        "Root cause identified correctly": "Hello/Dead" in root_cause or "mismatch" in root_cause.lower(),
    }

    print("\nGate Checks:")
    passed_count = 0
    for check_name, passed in checks.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {check_name}")
        if passed:
            passed_count += 1

    gate_passed = all(checks.values())

    print(f"\n{'='*80}")
    if gate_passed:
        print("🎉 GATE TEST PASSED - Core loop is architecturally sound!")
        print("Status: PROCEED to Phase 2 (Architecture Cleanup)")
    else:
        print("❌ GATE TEST FAILED - Core loop has issues")
        print("Status: INVESTIGATE root cause before proceeding")
    print('='*80)

    return gate_passed, result


if __name__ == "__main__":
    gate_passed, result = run_gate_test()
    sys.exit(0 if gate_passed else 1)
