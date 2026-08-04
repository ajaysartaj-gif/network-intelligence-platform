"""
Network Copilot CLI v2

Engineer-friendly interface with context-aware comparison.
"""

import sys
from typing import Dict
from diagnostics.pipeline import DiagnosticPipeline, DiagnosticInput
from diagnostics.comparison import ContextAwareComparison, ComparisonContext
from diagnostics.comparisons.ospf import OSPFComparisonContext
from diagnostics.parsers.ospf import OSPFParser


def format_comparison_result(result) -> str:
    """Format comparison result for terminal display."""
    output = []

    output.append("\n" + "=" * 70)
    output.append("SIDE-BY-SIDE COMPARISON")
    output.append("=" * 70)

    output.append(f"\n{result.summary}\n")

    if result.relevant_differences:
        output.append("RELEVANT DIFFERENCES")
        output.append("─" * 70)

        for param in result.relevant_differences:
            match_symbol = "✅" if param.matches else "❌"
            output.append(f"\n{match_symbol} {param.name.upper()}")
            output.append(f"   {result.endpoint_a:15} {param.value_a}")
            output.append(f"   {result.endpoint_b:15} {param.value_b}")
            output.append(f"   Why it matters: {param.why_matters}")

    if result.hidden_parameters:
        output.append(f"\n\nHIDDEN (Not relevant to {result.context.value})")
        output.append("─" * 70)
        for param in sorted(result.hidden_parameters)[:10]:
            output.append(f"  × {param}")
        if len(result.hidden_parameters) > 10:
            output.append(f"  × ... and {len(result.hidden_parameters) - 10} more")

    output.append("\n" + "=" * 70)
    return "\n".join(output)


def run_ospf_with_comparison(problem_statement: str, show_commands: Dict[str, str]) -> str:
    """Run OSPF diagnostic with side-by-side comparison."""

    pipeline = DiagnosticPipeline()
    parser = OSPFParser()
    comparison = ContextAwareComparison()

    # Run diagnostic
    input_data = DiagnosticInput(
        problem_statement=problem_statement,
        show_commands=show_commands,
        protocol="ospf",
        vendor="cisco",
    )

    result = pipeline.diagnose(input_data)

    # Parse interfaces for comparison
    interfaces = {}
    if "show ip ospf interface" in show_commands:
        interfaces = parser.parse_show_ip_ospf_interface(
            show_commands["show ip ospf interface"]
        )

    config = None
    if "show running-config" in show_commands:
        config = parser.parse_running_config_ospf(
            show_commands["show running-config"]
        )

    # Show comparison if investigating neighbor issues
    output = []

    if problem_statement.lower() and "neighbor" in problem_statement.lower():
        if len(interfaces) >= 2:
            # Get first two interfaces for comparison
            interface_names = sorted(interfaces.keys())
            iface_a = interfaces[interface_names[0]]
            iface_b = interfaces[interface_names[1]] if len(interface_names) > 1 else None

            if iface_b:
                config_a, config_b = OSPFComparisonContext.neighbor_establishment(
                    iface_a, iface_b, None, None, config, config
                )

                comparison_result = comparison.compare(
                    endpoint_a=interface_names[0],
                    endpoint_b=interface_names[1],
                    config_a=config_a,
                    config_b=config_b,
                    context=ComparisonContext.NEIGHBOR_ESTABLISHMENT,
                )

                output.append(format_comparison_result(comparison_result))

    # Always show diagnostic result
    output.append("\n" + "=" * 70)
    output.append("ROOT CAUSE ANALYSIS")
    output.append("=" * 70)
    output.append(f"\n🎯 ROOT CAUSE")
    output.append(f"   {result.root_cause}")
    output.append(f"   Confidence: {result.confidence:.0%}")

    if result.evidence:
        output.append(f"\n📋 EVIDENCE")
        for ev in result.evidence:
            output.append(f"   {ev}")

    output.append(f"\n✅ RECOMMENDED FIX")
    output.append(f"   {result.recommended_fix}")

    if result.verification_commands:
        output.append(f"\n🔍 VERIFICATION COMMANDS")
        for cmd in result.verification_commands:
            output.append(f"   {cmd}")

    output.append("\n" + "=" * 70)

    return "\n".join(output)


def run_demo():
    """Run demo with sample data."""

    sample_neighbor_output = """Neighbor ID     Pri   State           Dead Time   Address         Interface
192.168.1.1       1   EXSTART/--      00:00:00    10.0.1.1        Gi0/0
192.168.1.2       1   FULL/BDR        00:00:35    10.0.2.1        Gi0/1
"""

    sample_interface_output = """Gi0/0 is up, line protocol is up
  Internet Address 10.0.1.2/24, Area 0, Attached via Interface Enable
  Process ID 1, Router ID 192.168.99.1, Network Type BROADCAST, Cost: 1
  Hello interval 10 sec, Dead interval 40 sec

Gi0/1 is up, line protocol is up
  Internet Address 10.0.2.2/24, Area 1, Attached via Interface Enable
  Process ID 1, Router ID 192.168.99.1, Network Type BROADCAST, Cost: 1
  Hello interval 10 sec, Dead interval 40 sec
"""

    sample_config = """router ospf 1
 router-id 192.168.99.1
 network 10.0.1.0 0.0.0.255 area 0
 network 10.0.2.0 0.0.0.255 area 1
"""

    show_commands = {
        "show ip ospf neighbor": sample_neighbor_output,
        "show ip ospf interface": sample_interface_output,
        "show running-config": sample_config,
    }

    print("\n🔄 Running demo diagnosis with context-aware comparison...\n")
    result = run_ospf_with_comparison(
        "OSPF neighbor stuck in EXSTART state",
        show_commands
    )
    print(result)


if __name__ == "__main__":
    run_demo()
