"""
Network Copilot CLI

Engineer-friendly interface for network diagnostics.
"""

import sys
from typing import Dict
from diagnostics.pipeline import DiagnosticPipeline, DiagnosticInput


def format_diagnostic_result(result) -> str:
    """Format diagnostic result for terminal display."""
    output = []

    output.append("\n" + "=" * 70)
    output.append("NETWORK COPILOT - DIAGNOSTIC RESULT")
    output.append("=" * 70)

    # Root Cause
    output.append(f"\n🎯 ROOT CAUSE")
    output.append(f"   {result.root_cause}")
    output.append(f"   Confidence: {result.confidence:.0%}")

    # Evidence
    if result.evidence:
        output.append(f"\n📋 EVIDENCE")
        for ev in result.evidence:
            output.append(f"   {ev}")

    # Missing Evidence
    if result.missing_evidence:
        output.append(f"\n❓ MISSING EVIDENCE")
        for ev in result.missing_evidence:
            output.append(f"   {ev}")

    # Recommended Fix
    output.append(f"\n✅ RECOMMENDED FIX")
    output.append(f"   {result.recommended_fix}")

    # Verification
    if result.verification_commands:
        output.append(f"\n🔍 VERIFICATION COMMANDS")
        for cmd in result.verification_commands:
            output.append(f"   {cmd}")

    # Rollback
    if result.rollback_procedure:
        output.append(f"\n↩️ ROLLBACK")
        output.append(f"   {result.rollback_procedure}")

    output.append("\n" + "=" * 70)
    return "\n".join(output)


def prompt_for_show_commands() -> Dict[str, str]:
    """Prompt engineer to paste show commands."""
    commands = {}

    print("\n" + "=" * 70)
    print("NETWORK COPILOT - OSPF DIAGNOSTIC")
    print("=" * 70)
    print("\nEnter show commands (one per section). Type 'END' when finished.\n")

    common_commands = [
        "show ip ospf neighbor",
        "show ip ospf interface",
        "show running-config | section ospf",
    ]

    for cmd in common_commands:
        print(f"Paste output from: {cmd}")
        print("(Paste text, then press Enter twice)")
        lines = []
        blank_count = 0

        while True:
            try:
                line = input()
            except EOFError:
                break

            if not line:
                blank_count += 1
                if blank_count >= 2:
                    break
            else:
                blank_count = 0
                lines.append(line)

        if lines:
            commands[cmd] = "\n".join(lines)
            print(f"✓ Captured {len(lines)} lines\n")

    return commands


def run_interactive():
    """Run interactive diagnostic."""
    pipeline = DiagnosticPipeline()

    # Get problem statement
    print("\nWhat's the network problem you're investigating?")
    print("Example: 'OSPF stuck in EXSTART' or 'Routes not appearing'")
    problem = input("> ").strip()

    if not problem:
        print("No problem statement provided.")
        return

    # Get show commands
    show_commands = prompt_for_show_commands()

    if not show_commands:
        print("No show command output provided.")
        return

    # Run diagnosis
    print("\n🔄 Analyzing...")
    input_data = DiagnosticInput(
        problem_statement=problem,
        show_commands=show_commands,
        protocol="ospf",
        vendor="cisco",
    )

    try:
        result = pipeline.diagnose(input_data)
        print(format_diagnostic_result(result))
    except Exception as e:
        print(f"\n❌ Error during diagnosis: {e}")
        import traceback
        traceback.print_exc()


def run_demo():
    """Run demo with sample data."""
    pipeline = DiagnosticPipeline()

    # Demo data
    sample_neighbor_output = """Neighbor ID     Pri   State           Dead Time   Address         Interface
192.168.1.1       1   EXSTART/--      00:00:00    10.0.1.1        Gi0/0
192.168.1.2       1   FULL/BDR        00:00:35    10.0.2.1        Gi0/1
"""

    sample_interface_output = """Gi0/0 is up, line protocol is up
  Internet Address 10.0.1.2/24, Area 0, Attached via Interface Enable
  Process ID 1, Router ID 192.168.99.1, Network Type BROADCAST, Cost: 1
  Hello interval 10 sec, Dead interval 40 sec

Gi0/1 is up, line protocol is up
  Internet Address 10.0.2.2/24, Area 0, Attached via Interface Enable
  Process ID 1, Router ID 192.168.99.1, Network Type BROADCAST, Cost: 1
  Hello interval 10 sec, Dead interval 40 sec
"""

    sample_config = """router ospf 1
 router-id 192.168.99.1
 network 10.0.1.0 0.0.0.255 area 0
 network 10.0.2.0 0.0.0.255 area 0
"""

    input_data = DiagnosticInput(
        problem_statement="OSPF neighbor stuck in EXSTART state",
        show_commands={
            "show ip ospf neighbor": sample_neighbor_output,
            "show ip ospf interface": sample_interface_output,
            "show running-config": sample_config,
        },
        protocol="ospf",
        vendor="cisco",
    )

    print("\n🔄 Running demo diagnosis...")
    result = pipeline.diagnose(input_data)
    print(format_diagnostic_result(result))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        run_demo()
    else:
        run_interactive()
