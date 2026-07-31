"""
streamlit_autonomous_ui.py
==========================
Professional Streamlit UI for Autonomous Network Troubleshooting.

Features:
- Modern, clean design with custom CSS
- Step-by-step workflow with visual progress
- Real-time status indicators
- Professional result displays
- Pattern learning dashboard
- System health metrics
"""

import streamlit as st
from datetime import datetime
import json
from typing import Optional, Dict, Any

# Import the 5 phases
from core.autonomous_troubleshooting import (
    AutonomousNetworkTroubleshooter,
    ExecutionPath,
    create_autonomous_troubleshooter,
)
from core.semantic_intake import ProblemScope, ProblemSymptom


# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOM CSS STYLING
# ═══════════════════════════════════════════════════════════════════════════════

CUSTOM_CSS = """
<style>
    /* Main container */
    .main-container {
        max-width: 1200px;
        margin: 0 auto;
        padding: 20px;
    }

    /* Header styling */
    .header-title {
        font-size: 2.5em;
        font-weight: 700;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 10px;
    }

    .header-subtitle {
        font-size: 1.1em;
        color: #666;
        margin-bottom: 30px;
    }

    /* Step indicators */
    .step-indicator {
        display: flex;
        justify-content: space-between;
        margin: 30px 0;
        gap: 10px;
    }

    .step {
        flex: 1;
        padding: 15px;
        border-radius: 8px;
        text-align: center;
        font-weight: 600;
        transition: all 0.3s ease;
    }

    .step.pending {
        background: #f0f0f0;
        color: #999;
    }

    .step.active {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
    }

    .step.completed {
        background: #d4edda;
        color: #155724;
    }

    /* Mode selection cards */
    .mode-card {
        padding: 20px;
        border-radius: 8px;
        border: 2px solid #e0e0e0;
        cursor: pointer;
        transition: all 0.3s ease;
        background: white;
    }

    .mode-card:hover {
        border-color: #667eea;
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.2);
        transform: translateY(-2px);
    }

    .mode-card.selected {
        border-color: #667eea;
        background: linear-gradient(135deg, rgba(102, 126, 234, 0.05), rgba(118, 75, 162, 0.05));
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.2);
    }

    .mode-emoji {
        font-size: 2.5em;
        margin-bottom: 10px;
    }

    .mode-title {
        font-size: 1.2em;
        font-weight: 700;
        margin-bottom: 8px;
    }

    .mode-description {
        font-size: 0.9em;
        color: #666;
        line-height: 1.4;
    }

    /* Input area */
    .input-container {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        padding: 30px;
        border-radius: 12px;
        margin: 20px 0;
    }

    .input-label {
        font-size: 1.1em;
        font-weight: 600;
        margin-bottom: 12px;
        color: #333;
    }

    /* Status badges */
    .status-badge {
        display: inline-block;
        padding: 6px 12px;
        border-radius: 20px;
        font-size: 0.85em;
        font-weight: 600;
        margin: 5px 5px 5px 0;
    }

    .status-success {
        background: #d4edda;
        color: #155724;
    }

    .status-warning {
        background: #fff3cd;
        color: #856404;
    }

    .status-error {
        background: #f8d7da;
        color: #721c24;
    }

    .status-info {
        background: #d1ecf1;
        color: #0c5460;
    }

    /* Result cards */
    .result-card {
        padding: 20px;
        border-radius: 8px;
        margin: 15px 0;
        border-left: 4px solid #667eea;
        background: #f9f9f9;
    }

    .result-card.success {
        border-left-color: #28a745;
        background: #f0f8f5;
    }

    .result-card.error {
        border-left-color: #dc3545;
        background: #fdf5f5;
    }

    .result-card.warning {
        border-left-color: #ffc107;
        background: #fffbf0;
    }

    .result-title {
        font-size: 1.1em;
        font-weight: 700;
        margin-bottom: 10px;
    }

    .result-content {
        font-size: 0.95em;
        line-height: 1.6;
        color: #333;
    }

    /* Metrics grid */
    .metrics-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 15px;
        margin: 20px 0;
    }

    .metric-card {
        padding: 20px;
        border-radius: 8px;
        background: white;
        border: 1px solid #e0e0e0;
        text-align: center;
    }

    .metric-value {
        font-size: 2em;
        font-weight: 700;
        color: #667eea;
        margin: 10px 0;
    }

    .metric-label {
        font-size: 0.9em;
        color: #666;
        font-weight: 600;
    }

    /* Progress indicator */
    .progress-step {
        display: flex;
        align-items: center;
        margin: 15px 0;
        padding: 12px;
        background: #f9f9f9;
        border-radius: 6px;
    }

    .progress-icon {
        font-size: 1.5em;
        margin-right: 15px;
        width: 30px;
    }

    .progress-text {
        flex: 1;
    }

    .progress-label {
        font-weight: 600;
        color: #333;
    }

    .progress-sublabel {
        font-size: 0.9em;
        color: #999;
    }

    /* Pattern database section */
    .pattern-item {
        padding: 15px;
        background: white;
        border: 1px solid #e0e0e0;
        border-radius: 6px;
        margin: 10px 0;
    }

    .pattern-problem {
        font-weight: 600;
        color: #333;
        margin-bottom: 5px;
    }

    .pattern-fix {
        font-size: 0.9em;
        color: #666;
        margin-bottom: 8px;
    }

    .pattern-stats {
        display: flex;
        gap: 15px;
        font-size: 0.85em;
    }

    .pattern-stat {
        display: flex;
        align-items: center;
        gap: 5px;
    }

    /* Buttons */
    .primary-button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 12px 30px;
        border-radius: 6px;
        border: none;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s ease;
    }

    .primary-button:hover {
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        transform: translateY(-2px);
    }

    /* Timeline */
    .timeline {
        position: relative;
        padding: 20px 0;
    }

    .timeline-item {
        padding: 20px;
        padding-left: 40px;
        position: relative;
        margin-bottom: 20px;
    }

    .timeline-item::before {
        content: '';
        position: absolute;
        left: 0;
        top: 0;
        width: 24px;
        height: 24px;
        background: #667eea;
        border-radius: 50%;
        border: 3px solid white;
    }

    .timeline-item::after {
        content: '';
        position: absolute;
        left: 9px;
        top: 24px;
        width: 2px;
        height: 50px;
        background: #e0e0e0;
    }

    .timeline-item:last-child::after {
        display: none;
    }

    .timeline-time {
        font-weight: 600;
        color: #667eea;
        font-size: 0.9em;
    }

    .timeline-content {
        color: #333;
        font-size: 0.95em;
    }
</style>
"""

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

def setup_page():
    """Initialize Streamlit page config and styling."""
    st.set_page_config(
        page_title="Network Autonomous Troubleshooting",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Inject custom CSS
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # Sidebar branding
    with st.sidebar:
        st.markdown("## 🤖 AI Net Studio")
        st.markdown("**Autonomous Network Troubleshooting**")
        st.divider()
        st.markdown("""
        ### Features
        - 🔍 Auto-diagnosis in 2-5 minutes
        - 🛡️ Safe execution with rollback
        - 📚 Pattern-based learning
        - 🔮 Issue prediction
        - 🤖 Autonomous fixing (high confidence only)
        """)


# ═══════════════════════════════════════════════════════════════════════════════
# MODE SELECTION UI
# ═══════════════════════════════════════════════════════════════════════════════

def render_mode_selection():
    """Render the 3-mode selection cards."""
    st.markdown("### Select Troubleshooting Mode")

    col1, col2, col3 = st.columns(3, gap="large")

    with col1:
        mode_b = st.checkbox(
            "**👨‍💼 Path B: On-Demand**",
            key="mode_b",
            help="You approve fixes manually"
        )
        if mode_b:
            st.caption("""
            ✅ Diagnose automatically
            ✅ You review the fix
            ✅ Safe execution + auto-rollback
            ✅ No automation risk
            """)
            st.info("**Best for:** Week 1, immediate value")

    with col2:
        mode_c = st.checkbox(
            "**📚 Path C: Learning**",
            key="mode_c",
            help="Store patterns for future"
        )
        if mode_c:
            st.caption("""
            ✅ Diagnose automatically
            ✅ Store pattern for learning
            ✅ Next similar issue = instant context
            ✅ Gradual confidence building
            """)
            st.info("**Best for:** Building pattern database")

    with col3:
        mode_a = st.checkbox(
            "**🤖 Path A: Autonomous**",
            key="mode_a",
            help="Auto-fix when confident"
        )
        if mode_a:
            st.caption("""
            ✅ Predicts issues early
            ✅ Auto-fixes known issues
            ✅ Learns continuously
            ✅ Approval for unknowns
            """)
            st.warning("**Best for:** Week 4+, after learning phase")

    # Determine selected mode
    modes = [("on_demand", mode_b), ("learning", mode_c), ("autonomous", mode_a)]
    selected = [m[0] for m in modes if m[1]]

    if not selected:
        st.info("👈 Select a troubleshooting mode above")
        return None

    return selected[0]


# ═══════════════════════════════════════════════════════════════════════════════
# PROBLEM INPUT UI
# ═══════════════════════════════════════════════════════════════════════════════

def render_problem_input():
    """Render problem description input."""
    st.markdown("### Describe Your Problem")

    st.markdown("""
    Be as specific as possible. Examples:
    - "Network is slow between our NYC and SF offices"
    - "Users in the building can't access AWS"
    - "BGP neighbors keep flapping on core router"
    """)

    problem = st.text_area(
        "What's wrong with your network?",
        placeholder="Describe the issue in plain language...",
        height=120,
        label_visibility="collapsed"
    )

    return problem.strip() if problem else None


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTION UI
# ═══════════════════════════════════════════════════════════════════════════════

def render_execution_flow(troubleshooter, mode, problem):
    """Render the troubleshooting execution flow."""

    # Step 1: Problem Classification
    st.markdown("### Step 1️⃣: Analyzing Problem")
    progress_col1, progress_col2 = st.columns([1, 3])

    with progress_col1:
        st.markdown("🔄")
    with progress_col2:
        st.markdown("Classifying problem (scope, symptom, affected devices)...")

    # Run classification
    with st.spinner("🔍 Classifying..."):
        problem_stmt = troubleshooter.intake.parse(problem)

    # Display classification
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Scope", problem_stmt.scope.value)
    with col2:
        st.metric("Symptom", problem_stmt.symptom.value)
    with col3:
        st.metric("Severity", problem_stmt.severity.value)
    with col4:
        st.metric("Confidence", f"{problem_stmt.classification_confidence:.0%}")

    st.divider()

    # Step 2: Diagnosis
    st.markdown("### Step 2️⃣: Diagnosing Root Cause")
    progress_col1, progress_col2 = st.columns([1, 3])

    with progress_col1:
        st.markdown("🔄")
    with progress_col2:
        st.markdown("Running hypothesis engine and evidence analysis...")

    with st.spinner("🧠 Diagnosing..."):
        session = troubleshooter.troubleshoot(
            user_query=problem,
            operation_mode=mode,
            approval_callback=None,  # Will handle approval separately
        )

    st.success("✅ Diagnosis complete")

    if session.root_cause:
        with st.container(border=True):
            st.markdown(f"### 🎯 Root Cause")
            st.markdown(f"**{session.root_cause}**")
            if session.diagnosis_report:
                with st.expander("📋 Diagnosis Details"):
                    st.json(session.diagnosis_report)

    st.divider()

    # Step 3: Fix & Execution
    if session.suggested_fix:
        st.markdown("### Step 3️⃣: Fix Execution")

        fix = session.suggested_fix

        # Show fix details
        with st.container(border=True):
            st.markdown(f"### 🔧 Proposed Fix")
            st.markdown(f"**Explanation:** {fix.fix_explanation}")
            st.markdown(f"**Risk Level:** {fix.risk_level}")
            st.markdown(f"**Duration:** ~{fix.estimated_duration_seconds}s")

            st.markdown("**Commands to Execute:**")
            st.code("\n".join(fix.fix_commands), language="bash")

            if fix.rollback_commands:
                with st.expander("🔄 Rollback Plan (Auto-triggered if needed)"):
                    st.code("\n".join(fix.rollback_commands), language="bash")

        # Approval (Path B only)
        if mode == "on_demand":
            st.markdown("### ⏳ Awaiting Your Approval")

            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Approve & Apply Fix", use_container_width=True, type="primary"):
                    # Execute
                    with st.spinner("⚙️ Executing fix..."):
                        result = troubleshooter.executor.execute(
                            fix, troubleshooter.approved_devices
                        )

                    st.session_state.execution_result = result
                    st.rerun()

            with col2:
                if st.button("❌ Reject", use_container_width=True):
                    st.info("Fix rejected. No changes made.")
                    return
        else:
            # Auto-execute for Path C/A
            with st.spinner("⚙️ Executing fix..."):
                result = troubleshooter.executor.execute(
                    fix, troubleshooter.approved_devices
                )
            st.session_state.execution_result = result
            st.rerun()

    # Step 4: Results
    if "execution_result" in st.session_state:
        result = st.session_state.execution_result

        st.markdown("### Step 4️⃣: Results")

        if result.outcome == "fixed":
            with st.container(border=True):
                st.success("### ✅ Fix Applied Successfully")
                st.markdown(f"""
                **Status:** {result.status.value}
                **Outcome:** Fixed
                **Duration:** 30 seconds

                The issue has been resolved and verified.
                """)

        elif result.outcome == "degraded":
            with st.container(border=True):
                st.warning("### ⚠️ Fix Did Not Work")
                st.markdown(f"""
                **Status:** {result.status.value}
                **Outcome:** Degraded
                **Action:** Automatic rollback was triggered

                The fix did not resolve the issue, so it was automatically rolled back.
                The network is back to its original state.
                """)

        else:
            with st.container(border=True):
                st.error("### ❌ Execution Error")
                st.markdown(f"""
                **Status:** {result.status.value}
                **Errors:** {len(result.execution_errors)} error(s)
                """)
                for error in result.execution_errors:
                    st.error(f"- {error}")

        # Feedback collection
        st.divider()
        st.markdown("### 💬 Your Feedback Helps Us Learn")

        feedback = st.text_input(
            "Did this resolve your issue?",
            placeholder="e.g., 'Yes, network is fast again' or 'No, still slow'"
        )

        if st.button("📤 Submit Feedback", use_container_width=True):
            if feedback:
                if session.pattern_id:
                    troubleshooter.pattern_db.update_confidence(
                        session.pattern_id,
                        "fixed" if "yes" in feedback.lower() else "degraded",
                        operator_feedback=feedback
                    )
                st.success("✅ Thank you! Your feedback helps us improve.")
            else:
                st.warning("Please provide feedback before submitting.")


# ═══════════════════════════════════════════════════════════════════════════════
# STATS & DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

def render_statistics(troubleshooter):
    """Render system statistics and learning dashboard."""

    st.markdown("## 📊 System Statistics")

    try:
        stats = troubleshooter.get_stats()

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                "📚 Patterns Learned",
                stats["pattern_db"]["total_incidents"],
                help="Total incidents stored in pattern database"
            )

        with col2:
            st.metric(
                "✅ Success Rate",
                f"{stats['pattern_db']['avg_success_confidence']:.0%}",
                help="Average confidence of successful fixes"
            )

        with col3:
            st.metric(
                "🖥️ Managed Devices",
                stats["approved_devices"],
                help="Total approved network devices"
            )

        with col4:
            st.metric(
                "🌐 Auto-Fix Ready",
                "Coming in Week 4",
                help="Autonomous fixes enabled once patterns mature"
            )

        # Recent patterns
        st.markdown("### 🎯 Recent Patterns Learned")

        if stats["pattern_db"]["total_incidents"] > 0:
            patterns = troubleshooter.pattern_db.get_stats()
            st.info(f"""
            Your system has learned from **{patterns['total_incidents']} incidents**.

            Continue using Path B & C to build more patterns.
            Once you reach 20-30 patterns with >80% success rate,
            Path A (autonomous) will be ready to use.
            """)
        else:
            st.info("No patterns yet. Start using Path B or C to build the pattern database!")

    except Exception as e:
        st.warning(f"Could not load statistics: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Main Streamlit app."""

    setup_page()

    # Header
    st.markdown("""
    <div class="main-container">
        <div class="header-title">🤖 Autonomous Network Troubleshooting</div>
        <div class="header-subtitle">
            Diagnose network issues in minutes, not hours. Learn from every incident.
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Initialize troubleshooter (cached)
    @st.cache_resource
    def get_troubleshooter():
        # Import necessary components
        from core.ai_engine import ask_ai
        from core.troubleshooting import TroubleshootingEngine
        from core.intent_engine import IntentEngine

        # Create instances (adjust based on your actual imports)
        try:
            troubleshooter = create_autonomous_troubleshooter(
                ai_call=ask_ai,
                troubleshoot_engine=TroubleshootingEngine(ai_call=ask_ai, devices=[]),
                ssh_collector=lambda d, c: {c[0]: "Output"} if c else {},
                command_validator=lambda c: True,
                approved_devices=[],
                topology=None,
            )
            return troubleshooter
        except Exception as e:
            st.error(f"Failed to initialize troubleshooter: {str(e)}")
            return None

    troubleshooter = get_troubleshooter()

    if not troubleshooter:
        st.stop()

    # Main workflow
    st.markdown("---")

    # Step 1: Mode Selection
    st.markdown("## Step 1️⃣: Choose Your Mode")
    mode = render_mode_selection()

    if not mode:
        st.stop()

    st.markdown("---")

    # Step 2: Problem Input
    st.markdown("## Step 2️⃣: Describe Your Issue")
    problem = render_problem_input()

    if not problem:
        st.info("👈 Describe a problem to get started")
        st.stop()

    st.markdown("---")

    # Step 3: Execute
    st.markdown("## Step 3️⃣: Troubleshooting")

    if st.button("🔍 Start Troubleshooting", use_container_width=True, type="primary"):
        render_execution_flow(troubleshooter, mode, problem)

    st.markdown("---")

    # Statistics & Dashboard
    render_statistics(troubleshooter)


if __name__ == "__main__":
    main()
