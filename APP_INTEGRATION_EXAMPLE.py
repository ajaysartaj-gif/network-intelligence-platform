"""
APP_INTEGRATION_EXAMPLE.py
==========================
Shows exactly how to wire all 5 phases into your Streamlit app.py

This is a reference implementation. Copy-paste the relevant sections
into your app.py workspace.

Usage:
  1. Copy this file alongside app.py
  2. Import the functions shown below
  3. Adapt to your existing app structure
"""

import streamlit as st
from datetime import datetime
from typing import Optional

# Import the 5 phases
from core.semantic_intake import SemanticIntake
from core.remediation_executor import RemediationExecutor, RemediationPlan
from core.pattern_db import PatternDatabase
from core.prediction_forecaster import PatternPredictor, AutonomousDecisionMaker
from core.autonomous_troubleshooting import (
    AutonomousNetworkTroubleshooter,
    ExecutionPath,
    create_autonomous_troubleshooter,
)

# Import your existing systems
from core.ai_engine import ask_ai
from core.intent_engine import IntentEngine
from core.troubleshooting import TroubleshootingEngine
from core.orchestration_engine import OperationsOrchestrator


# ═══════════════════════════════════════════════════════════════════════════════
# INITIALIZATION (run once at app startup)
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_resource
def initialize_autonomous_troubleshooter(
    orchestrator: OperationsOrchestrator,
    intent_engine: IntentEngine,
    ts_engine: TroubleshootingEngine,
    approved_devices: list,
    topology_graph
) -> AutonomousNetworkTroubleshooter:
    """
    Initialize the autonomous troubleshooter with all 5 phases.

    This runs once and is cached in st.session_state.
    """
    troubleshooter = create_autonomous_troubleshooter(
        ai_call=ask_ai,
        troubleshoot_engine=ts_engine,
        ssh_collector=lambda dev, cmds: intent_engine._ssh_collect(dev, cmds),
        command_validator=lambda cmd: intent_engine.is_read_only(cmd) and not intent_engine.is_dangerous(cmd),
        approved_devices=approved_devices,
        topology=topology_graph,
    )

    st.success("✅ Autonomous troubleshooter initialized with all 5 phases")
    return troubleshooter


# ═══════════════════════════════════════════════════════════════════════════════
# STREAMLIT UI WORKSPACE
# ═══════════════════════════════════════════════════════════════════════════════

def render_autonomous_troubleshooting_workspace(
    orchestrator: OperationsOrchestrator,
    intent_engine: IntentEngine,
    ts_engine: TroubleshootingEngine,
    approved_devices: list,
    topology_graph
):
    """
    Complete Streamlit workspace for autonomous troubleshooting.

    Renders:
    - Problem input
    - Mode selection (Path A/B/C)
    - Execution flow
    - Results display
    """

    st.title("🤖 Autonomous Network Troubleshooting")
    st.markdown("""
    Describe your network problem in plain language. The system will:
    1. Classify the problem (scope, symptom, affected devices)
    2. Diagnose the root cause
    3. Generate a safe fix with rollback capability
    4. Learn from every incident for future reference
    """)

    # Initialize troubleshooter
    troubleshooter = initialize_autonomous_troubleshooter(
        orchestrator, intent_engine, ts_engine, approved_devices, topology_graph
    )

    # ── STEP 1: MODE SELECTION ────────────────────────────────────────────────
    st.header("1️⃣ Select Troubleshooting Mode")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("### 🤖 Autonomous (Path A)")
        st.caption("""
        • Predicts issues before they break
        • Auto-fixes known issues (confidence >85%)
        • Learns from every incident
        • Requires approval for unknown issues
        """)

    with col2:
        st.markdown("### 👨‍💼 On-Demand (Path B)")
        st.caption("""
        • You describe the problem
        • System diagnoses
        • You approve the fix
        • Safe execution with auto-rollback
        """)

    with col3:
        st.markdown("### 📚 Learning (Path C)")
        st.caption("""
        • Diagnose & store patterns
        • Next similar issue = instant context
        • Build confidence gradually
        • No automation, just learning
        """)

    mode = st.radio(
        "Choose mode:",
        options=["on_demand", "learning", "autonomous"],
        format_func=lambda x: {"on_demand": "Path B: On-Demand",
                               "learning": "Path C: Learning",
                               "autonomous": "Path A: Autonomous"}[x],
        index=0,  # Start with Path B (safest)
    )

    # ── STEP 2: PROBLEM DESCRIPTION ────────────────────────────────────────────
    st.header("2️⃣ Describe Your Problem")

    problem = st.text_area(
        "What's wrong with your network?",
        placeholder="e.g., 'Network is slow between NYC and SF' or 'Router can't reach AWS'",
        height=100,
    )

    if not problem:
        st.info("👈 Describe a problem above to get started")
        return

    # ── STEP 3: EXECUTE ───────────────────────────────────────────────────────
    st.header("3️⃣ Troubleshooting")

    if st.button("🔍 Start Troubleshooting", use_container_width=True):

        with st.spinner("🔄 Analyzing your network..."):

            # Telemetry for predictions (Path A only)
            telemetry_metrics = None
            if mode == "autonomous":
                try:
                    telemetry_metrics = orchestrator.telemetry.current_metrics
                except:
                    telemetry_metrics = None

            # Approval callback (interactive)
            def approval_callback(plan: RemediationPlan) -> bool:
                st.subheader("⏳ Awaiting Your Approval")
                st.info(f"**Root Cause**: {plan.root_cause}")
                st.info(f"**Explanation**: {plan.fix_explanation}")

                st.warning("**Fix Commands**:")
                st.code("\n".join(plan.fix_commands), language="bash")

                if plan.rollback_commands:
                    with st.expander("Rollback plan"):
                        st.code("\n".join(plan.rollback_commands), language="bash")

                col_yes, col_no = st.columns(2)
                with col_yes:
                    if st.button("✅ Approve & Apply", use_container_width=True):
                        return True
                with col_no:
                    if st.button("❌ Reject", use_container_width=True):
                        return False

                return False

            # Run troubleshooting
            try:
                session = troubleshooter.troubleshoot(
                    user_query=problem,
                    operation_mode=mode,
                    approval_callback=approval_callback if mode == "on_demand" else None,
                    telemetry_metrics=telemetry_metrics,
                )

                # ── RESULTS DISPLAY ──────────────────────────────────────────
                st.header("📊 Results")

                # Show predictions (Path A only)
                if session.predictions:
                    st.warning("🔮 **Predicted Issues**:")
                    for pred in session.predictions[:3]:
                        st.markdown(f"""
                        - **{pred.issue_description}**
                          - ETA: {pred.eta_minutes:.0f} minutes
                          - Confidence: {pred.confidence:.0%}
                          - Historical precedents: {pred.historical_precedents}
                        """)

                # Show diagnosis
                if session.root_cause:
                    st.success(f"✅ **Diagnosis**: {session.root_cause}")

                # Show execution result (Path A/B only)
                if session.execution_result:
                    result = session.execution_result

                    if result.outcome == "fixed":
                        st.success("✅ **Fix Applied Successfully**")
                        st.markdown(f"**Time to resolution**: {session.duration_seconds:.0f} seconds")
                    elif result.outcome == "degraded":
                        st.warning("⚠️ **Fix Did Not Work**")
                        st.markdown("Automatic rollback was triggered")
                    else:
                        st.error("❌ **Execution Error**")

                    # Show execution trace (expandable)
                    with st.expander("📋 Execution Details"):
                        st.json({
                            "status": result.status.value,
                            "pre_check_errors": result.pre_check_errors,
                            "execution_errors": result.execution_errors,
                            "post_check": result.post_check_result,
                            "rolled_back": result.rolled_back,
                        })

                # Show pattern recorded (Path C)
                if session.pattern_id:
                    st.info(f"📚 **Pattern recorded**: {session.pattern_id}")
                    st.markdown("This incident has been stored for future reference.")

                # ── FEEDBACK COLLECTION ──────────────────────────────────────
                st.header("💬 Feedback")

                feedback = st.text_input(
                    "Did this resolve your issue? Leave feedback:",
                    placeholder="e.g., 'Yes, network is back to normal' or 'No, still slow'"
                )

                if feedback and st.button("📤 Submit Feedback"):
                    if session.pattern_id:
                        troubleshooter.pattern_db.update_confidence(
                            session.pattern_id,
                            "fixed" if "yes" in feedback.lower() else "degraded",
                            operator_feedback=feedback
                        )
                    st.success("✅ Feedback recorded! System will learn from this.")

            except Exception as e:
                st.error(f"❌ Error during troubleshooting: {str(e)}")
                st.exception(e)

    # ── STEP 4: STATISTICS ────────────────────────────────────────────────────
    st.header("📈 System Statistics")

    try:
        stats = troubleshooter.get_stats()

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "Patterns Learned",
                stats["pattern_db"]["total_incidents"],
                help="Total incidents recorded and learned"
            )

        with col2:
            st.metric(
                "Success Rate",
                f"{stats['pattern_db']['avg_success_confidence']:.0%}",
                help="Average confidence of successful fixes"
            )

        with col3:
            st.metric(
                "Approved Devices",
                stats["approved_devices"],
                help="Number of managed network devices"
            )
    except:
        st.info("Statistics not yet available")


# ═══════════════════════════════════════════════════════════════════════════════
# HOW TO INTEGRATE INTO YOUR app.py
# ═══════════════════════════════════════════════════════════════════════════════

"""
STEP 1: Add import at top of app.py
    from APP_INTEGRATION_EXAMPLE import render_autonomous_troubleshooting_workspace

STEP 2: Add new workspace option
    # In your WORKSPACES list or workspace selector:
    WORKSPACES = [
        ("Net Ops", "⚡", "NOC Operations"),
        ...
        ("Autonomous TS", "🤖", "Autonomous Troubleshooting"),  # NEW
    ]

STEP 3: Add to workspace rendering logic
    # In your workspace content section (where you have if workspace == "dashboard":)

    elif workspace == "Autonomous TS":
        render_autonomous_troubleshooting_workspace(
            orchestrator=orchestrator,
            intent_engine=intent_engine,  # or however you access it
            ts_engine=ts_engine,
            approved_devices=approved_devices,
            topology_graph=topology_graph,
        )

STEP 4: Test
    streamlit run app.py
    Select "Autonomous TS" workspace
    Try a problem description

That's it! You now have all 5 phases running.
"""


if __name__ == "__main__":
    # For testing this file standalone (not typical)
    st.title("Autonomous Troubleshooting - Standalone Test")
    st.warning("This file is meant to be imported into app.py, not run standalone.")
    st.markdown("""
    See the docstring at the top for integration instructions.
    """)
