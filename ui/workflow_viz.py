"""
Workflow Visualizer — renders the real-time autonomous remediation pipeline.
This is the primary NOC display: step-by-step visualization of detect→fix→verify.
"""
import streamlit as st
from typing import Optional, List, Dict, Any
from datetime import datetime


def render_workflow_header(run) -> None:
    """Render the workflow run header banner."""
    severity_colors = {
        "critical": "#cc0000",
        "high":     "#cc6600",
        "medium":   "#ccaa00",
        "low":      "#006600",
    }
    severity_icons = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
    color = severity_colors.get(run.severity, "#666666")
    icon  = severity_icons.get(run.severity, "⚪")

    status_badge = {
        "running":   "🔄 IN PROGRESS",
        "completed": "✅ COMPLETED",
        "failed":    "❌ FAILED",
    }.get(run.status, run.status.upper())

    st.markdown(
        f"""
        <div style="
            background: linear-gradient(135deg, {color}22, {color}11);
            border-left: 4px solid {color};
            border-radius: 8px;
            padding: 16px 20px;
            margin-bottom: 12px;
        ">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <span style="font-size:18px; font-weight:700; color:{color};">
                        {icon} AUTONOMOUS REMEDIATION — {run.anomaly_type.replace('_',' ').upper()}
                    </span><br/>
                    <span style="color:#888; font-size:13px;">
                        Device: <b style="color:#ddd;">{run.device}</b> &nbsp;|&nbsp;
                        Incident: <b style="color:#ddd;">{run.incident_id}</b> &nbsp;|&nbsp;
                        Run: <b style="color:#ddd;">{run.run_id}</b>
                    </span>
                </div>
                <div style="text-align:right;">
                    <span style="font-size:14px; font-weight:600; color:{color};">{status_badge}</span><br/>
                    <span style="color:#888; font-size:12px;">⏱ {run.elapsed_seconds:.1f}s elapsed</span>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_progress_bar(run) -> None:
    """Render step progress bar."""
    pct = run.progress_pct
    col1, col2 = st.columns([5, 1])
    with col1:
        st.progress(pct / 100)
    with col2:
        st.markdown(f"**{pct}%**")


def render_step_pipeline(run) -> None:
    """Render the horizontal step pipeline overview."""
    steps = run.steps
    n = len(steps)
    cols = st.columns(n)

    status_styles = {
        "pending":   ("⬜", "#444444", "#222222"),
        "running":   ("🔄", "#0088ff", "#001133"),
        "completed": ("✅", "#00aa44", "#001a00"),
        "failed":    ("❌", "#cc0000", "#1a0000"),
        "skipped":   ("⏭️", "#666666", "#111111"),
    }

    for i, (step, col) in enumerate(zip(steps, cols)):
        icon, border_color, bg_color = status_styles.get(step.status.value, ("⬜", "#444", "#222"))
        is_current = step.status.value == "running"
        border_width = "3px" if is_current else "1px"

        with col:
            st.markdown(
                f"""
                <div style="
                    background:{bg_color};
                    border:{border_width} solid {border_color};
                    border-radius:8px;
                    padding:10px 6px;
                    text-align:center;
                    {'box-shadow: 0 0 12px ' + border_color + '66;' if is_current else ''}
                ">
                    <div style="font-size:20px;">{icon}</div>
                    <div style="font-size:11px; font-weight:600; color:{border_color};
                                margin-top:4px; line-height:1.2;">
                        {step.name}
                    </div>
                    {f'<div style="font-size:10px; color:#888;">{step.duration_ms:.0f}ms</div>'
                     if step.duration_ms else ''}
                </div>
                """,
                unsafe_allow_html=True,
            )

        # Arrow between steps (columns handle spacing)
        if i < n - 1:
            pass


def render_active_step_detail(run) -> None:
    """Render the detailed log for the currently active (or last completed) step."""
    running_steps = [s for s in run.steps if s.status.value == "running"]
    completed_steps = [s for s in run.steps if s.status.value == "completed"]

    detail_step = running_steps[0] if running_steps else (completed_steps[-1] if completed_steps else None)

    if not detail_step:
        return

    with st.expander(
        f"{'▶' if detail_step.status.value == 'running' else '📋'} "
        f"STEP {detail_step.step_id}: {detail_step.name.upper()} — {detail_step.status.value.upper()}",
        expanded=True,
    ):
        st.markdown(f"*{detail_step.description}*")

        if detail_step.output:
            # Render as terminal-style log — last 30 lines
            log_lines = "\n".join(detail_step.output[-30:])
            st.code(log_lines, language="bash")

        if detail_step.error:
            st.error(f"Error: {detail_step.error}")

        if detail_step.data:
            if "rca" in detail_step.data:
                st.markdown("**AI Root Cause Analysis:**")
                st.info(detail_step.data["rca"][:500])
            if "plan" in detail_step.data:
                st.markdown("**Remediation Plan:**")
                for item in detail_step.data["plan"]:
                    st.markdown(f"  • {item}")
            if "commands" in detail_step.data:
                st.markdown(f"**Commands executed:** {len(detail_step.data['commands'])}")


def render_all_completed_steps(run) -> None:
    """Render collapsed view of all completed steps."""
    completed = [s for s in run.steps if s.status.value == "completed"]
    if not completed:
        return

    with st.expander(f"📜 Full Step Log ({len(completed)} steps completed)", expanded=False):
        for step in completed:
            st.markdown(f"**✅ Step {step.step_id}: {step.name}**")
            if step.output:
                for line in step.output[-5:]:
                    st.markdown(f"  `{line}`")
            if step.duration_ms:
                st.caption(f"Duration: {step.duration_ms:.0f}ms")
            st.divider()


def render_workflow_run(run) -> None:
    """
    Main entry point — render a complete workflow run visualization.
    Call this from the Streamlit app for the active workflow.
    """
    render_workflow_header(run)
    render_progress_bar(run)
    st.markdown("")
    render_step_pipeline(run)
    st.markdown("")
    render_active_step_detail(run)
    render_all_completed_steps(run)


def render_workflow_history(runs: list, max_show: int = 5) -> None:
    """Render a summary table of recent workflow runs."""
    if not runs:
        st.info("No workflow runs yet. The system will start automatically when anomalies are detected.")
        return

    st.markdown("### Recent Workflow Runs")
    for run in runs[:max_show]:
        status_icon   = {"running": "🔄", "completed": "✅", "failed": "❌"}.get(run.status, "⬜")
        severity_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(run.severity, "⚪")

        col1, col2, col3, col4, col5 = st.columns([2, 2, 1, 1, 1])
        with col1:
            st.markdown(f"{severity_icon} **{run.device}**")
        with col2:
            st.markdown(f"{run.anomaly_type.replace('_', ' ').title()}")
        with col3:
            st.markdown(f"{status_icon} {run.status}")
        with col4:
            st.markdown(f"{run.progress_pct}%")
        with col5:
            st.markdown(f"{run.elapsed_seconds:.1f}s")


def render_no_active_workflow() -> None:
    """Render placeholder when no workflow is running."""
    st.markdown(
        """
        <div style="
            background: #0d1117;
            border: 1px dashed #30363d;
            border-radius: 12px;
            padding: 40px;
            text-align: center;
        ">
            <div style="font-size: 48px; margin-bottom: 12px;">🟢</div>
            <div style="font-size: 20px; font-weight: 600; color: #58a6ff; margin-bottom: 8px;">
                Network Operating Normally
            </div>
            <div style="font-size: 14px; color: #8b949e;">
                The autonomous monitor is active. When a network anomaly is detected,<br/>
                the full remediation pipeline will appear here step by step.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
