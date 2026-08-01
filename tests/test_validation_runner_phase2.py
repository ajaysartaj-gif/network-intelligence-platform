"""
tests/test_validation_runner_phase2.py
========================================
Phase 2 Validation Runner

Tests the refactored investigation engine against historical incidents.
Measures: convergence, accuracy, knowledge usage, performance.
"""

import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Any

sys.path.insert(0, '/Users/traptigupta/Desktop/network-intelligence-platform')

from core.protocol_planner import Protocol
from core.knowledge_first_investigator import KnowledgeFirstInvestigator
from tests.test_dataset_phase2 import (
    HistoricalIncident,
    PHASE2_TEST_DATASET,
    get_easy_test_cases,
    get_medium_test_cases,
    get_hard_test_cases,
)


@dataclass
class ValidationResult:
    """Result of investigating one test case."""
    test_case_id: str
    expected_root_cause: str
    investigation_result: Dict[str, Any]

    # Metrics
    cycles_taken: int
    final_confidence: float
    root_cause_found: str
    accuracy: bool  # Root cause matches expected
    convergence: bool  # Confidence >= threshold
    investigation_time_sec: float

    # Additional metrics
    knowledge_used: bool
    gaps_detected: int
    evidence_collected_total: int

    # Pass/Fail
    passed: bool


class ValidationRunner:
    """Run validation tests on the investigation engine."""

    def __init__(self):
        self.investigator = KnowledgeFirstInvestigator()
        self.results: List[ValidationResult] = []

    def run_single_test(self, case_id: str, case: HistoricalIncident) -> ValidationResult:
        """Run a single test case."""

        print(f"\n{'='*70}")
        print(f"Testing: {case_id}")
        print(f"  Protocol: {case.protocol.value}")
        print(f"  Issue: {case.issue_type}")
        print(f"  Severity: {case.severity.value}")
        print(f"  Expected root cause: {case.expected_root_cause}")
        print(f"  Expected cycles: {case.expected_cycles}")
        print(f"  Max cycles allowed: {case.max_cycles_allowed}")

        # Run investigation
        start_time = time.time()

        result = self.investigator.investigate(
            protocol=case.protocol,
            issue_type=case.issue_type,
            root_device=case.root_device,
            affected_devices=case.affected_devices,
            device_outputs=case.device_outputs,
            max_cycles=case.max_cycles_allowed,
            confidence_threshold=case.min_confidence_required
        )

        investigation_time = time.time() - start_time

        # Extract metrics
        cycles_taken = result.get("cycles", 0)
        final_confidence = result.get("confidence", 0.0)
        root_cause_found = result.get("root_cause", "Unknown")
        converged = result.get("converged", False)

        # Check accuracy
        accuracy = self._check_accuracy(root_cause_found, case.expected_root_cause)

        # Count evidence collected
        total_evidence = result.get("total_evidence", 0)

        # Check if external knowledge was used
        knowledge_used = len(result.get("accumulated_knowledge", {})) > 0

        # Count gaps
        gaps_detected = 0
        for cycle in result.get("cycles_detail", []):
            if "gaps" in cycle:
                gaps_detected += len(cycle["gaps"])

        # Pass/Fail logic
        passed = self._evaluate_pass_fail(
            accuracy=accuracy,
            convergence=converged,
            cycles=cycles_taken,
            confidence=final_confidence,
            case=case
        )

        # Log results
        print(f"\n  Results:")
        print(f"    Cycles taken: {cycles_taken} (expected: {case.expected_cycles}, max: {case.max_cycles_allowed})")
        print(f"    Final confidence: {final_confidence:.0%}")
        print(f"    Root cause found: {root_cause_found}")
        print(f"    Expected: {case.expected_root_cause}")
        print(f"    Accuracy: {'✅ MATCH' if accuracy else '❌ MISMATCH'}")
        print(f"    Convergence: {'✅ YES' if converged else '❌ NO'}")
        print(f"    Investigation time: {investigation_time:.1f}s")
        print(f"    Evidence collected: {total_evidence}")
        print(f"    Knowledge used: {'✅ YES' if knowledge_used else '❌ NO'}")
        print(f"    Gaps detected: {gaps_detected}")
        print(f"    Status: {'✅ PASSED' if passed else '❌ FAILED'}")

        # Build result
        validation_result = ValidationResult(
            test_case_id=case_id,
            expected_root_cause=case.expected_root_cause,
            investigation_result=result,
            cycles_taken=cycles_taken,
            final_confidence=final_confidence,
            root_cause_found=root_cause_found,
            accuracy=accuracy,
            convergence=converged,
            investigation_time_sec=investigation_time,
            knowledge_used=knowledge_used,
            gaps_detected=gaps_detected,
            evidence_collected_total=total_evidence,
            passed=passed
        )

        self.results.append(validation_result)
        return validation_result

    def run_all_tests(self) -> List[ValidationResult]:
        """Run all test cases."""

        print("\n" + "="*70)
        print("PHASE 2 VALIDATION: INVESTIGATION ENGINE")
        print("="*70)

        for case_id, case in PHASE2_TEST_DATASET.items():
            self.run_single_test(case_id, case)

        return self.results

    def run_test_subset(self, case_ids: List[str]) -> List[ValidationResult]:
        """Run a subset of tests."""

        print("\n" + "="*70)
        print("PHASE 2 VALIDATION: INVESTIGATION ENGINE (SUBSET)")
        print("="*70)

        for case_id in case_ids:
            case = PHASE2_TEST_DATASET.get(case_id)
            if case:
                self.run_single_test(case_id, case)

        return self.results

    def _check_accuracy(self, found: str, expected: str) -> bool:
        """Check if found root cause matches expected."""

        # Normalize strings (case-insensitive, substring matching)
        found_lower = found.lower()
        expected_lower = expected.lower()

        # Check for keyword match
        keywords = ["hello", "dead", "interval", "mismatch", "area", "mtu", "as", "authentication"]

        for keyword in keywords:
            if keyword in expected_lower and keyword not in found_lower:
                return False

        return True

    def _evaluate_pass_fail(self, accuracy: bool, convergence: bool, cycles: int,
                           confidence: float, case: HistoricalIncident) -> bool:
        """Evaluate if test case passed."""

        # Must meet ALL criteria to pass
        if not accuracy:
            return False  # Root cause must match

        if not convergence:
            return False  # Must converge

        if cycles > case.max_cycles_allowed:
            return False  # Must not exceed max cycles

        if confidence < case.min_confidence_required:
            return False  # Must meet confidence threshold

        return True

    def generate_report(self) -> str:
        """Generate validation report."""

        report = "\n" + "="*70 + "\n"
        report += "PHASE 2 VALIDATION REPORT\n"
        report += "="*70 + "\n\n"

        if not self.results:
            report += "No test results to report\n"
            return report

        # Summary metrics
        total_tests = len(self.results)
        passed_tests = sum(1 for r in self.results if r.passed)
        accuracy_rate = sum(1 for r in self.results if r.accuracy) / total_tests * 100
        convergence_rate = sum(1 for r in self.results if r.convergence) / total_tests * 100

        avg_cycles = sum(r.cycles_taken for r in self.results) / total_tests
        avg_confidence = sum(r.final_confidence for r in self.results) / total_tests
        avg_time = sum(r.investigation_time_sec for r in self.results) / total_tests
        knowledge_usage_rate = sum(1 for r in self.results if r.knowledge_used) / total_tests * 100

        report += f"SUMMARY\n"
        report += f"─" * 70 + "\n"
        report += f"Total tests: {total_tests}\n"
        report += f"Passed: {passed_tests}/{total_tests} ({passed_tests/total_tests*100:.0f}%)\n"
        report += f"Failed: {total_tests - passed_tests}/{total_tests}\n\n"

        report += f"KEY METRICS\n"
        report += f"─" * 70 + "\n"
        report += f"Accuracy rate (root cause found): {accuracy_rate:.0f}%\n"
        report += f"Convergence rate: {convergence_rate:.0f}%\n"
        report += f"Average cycles taken: {avg_cycles:.1f}\n"
        report += f"Average final confidence: {avg_confidence:.0%}\n"
        report += f"Average investigation time: {avg_time:.1f}s\n"
        report += f"Knowledge usage rate: {knowledge_usage_rate:.0f}%\n\n"

        # Detailed results
        report += f"DETAILED RESULTS\n"
        report += f"─" * 70 + "\n"

        for result in self.results:
            status = "✅ PASS" if result.passed else "❌ FAIL"
            report += f"{result.test_case_id}: {status}\n"
            report += f"  Cycles: {result.cycles_taken} | "
            report += f"Confidence: {result.final_confidence:.0%} | "
            report += f"Time: {result.investigation_time_sec:.1f}s\n"
            report += f"  Accuracy: {result.accuracy} | "
            report += f"Convergence: {result.convergence} | "
            report += f"Knowledge: {result.knowledge_used}\n\n"

        # Success criteria validation
        report += f"SUCCESS CRITERIA VALIDATION\n"
        report += f"─" * 70 + "\n"

        criteria = {
            "80%+ convergence on known issues in ≤3 cycles": (
                sum(1 for r in self.results if r.convergence and r.cycles_taken <= 3) / total_tests * 100 >= 80
            ),
            "90%+ accuracy on root cause": accuracy_rate >= 90,
            "External knowledge used in 50%+ of cases": knowledge_usage_rate >= 50,
            "Average investigation time < 30 seconds": avg_time < 30,
        }

        for criterion, met in criteria.items():
            status = "✅ MET" if met else "❌ NOT MET"
            report += f"{criterion}: {status}\n"

        report += "\n" + "="*70 + "\n"

        return report


def run_phase2_validation():
    """Run Phase 2 validation."""

    runner = ValidationRunner()

    # Run all tests
    results = runner.run_all_tests()

    # Generate and print report
    report = runner.generate_report()
    print(report)

    return results, runner


if __name__ == "__main__":
    results, runner = run_phase2_validation()
