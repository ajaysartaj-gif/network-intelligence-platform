# Streamlit UI Integration Guide for 6 Core Enhancements

This guide shows how to integrate the 6 core enhancements into `streamlit_autonomous_ui.py`.

## 1. Explainability - Display Step-by-Step Reasoning

```python
def render_explanations(session):
    """Display detailed reasoning for each troubleshooting step."""
    if not session.explanations:
        return
    
    st.markdown("## 🧠 Why I Made This Decision")
    st.markdown("---")
    
    for exp in session.explanations:
        with st.expander(f"Step {exp.step_number}: {exp.title}", expanded=(exp.step_number == 1)):
            st.markdown(exp.reasoning)
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Confidence", f"{exp.confidence:.0%}")
            with col2:
                if exp.sources:
                    st.metric("Sources", len(exp.sources))
```

**Integration point:** After displaying the diagnosis, before showing the fix.

```python
if session.root_cause:
    render_explanations(session)  # NEW
    st.markdown("---")
    render_fix_details(session.suggested_fix)
```

---

## 2. Multi-Device Orchestrator - Show Coordination Plan

```python
def render_device_coordination_plan(session, troubleshooter):
    """Display multi-device execution plan."""
    if len(session.problem.affected_devices or []) <= 1:
        return
    
    st.markdown("## 🔄 Multi-Device Coordination")
    
    # Show execution plan
    if hasattr(troubleshooter, 'orchestrator'):
        device_cmds = [
            DeviceCommand(
                device=dev,
                commands=session.suggested_fix.fix_commands,
                depends_on=[]  # Simplified
            )
            for dev in (session.problem.affected_devices or [])
        ]
        
        plan = troubleshooter.orchestrator.print_execution_plan(device_cmds)
        
        with st.expander("📋 Execution Plan", expanded=True):
            st.code(plan, language="text")
```

**Integration point:** Before "Execute" button for multi-device changes.

---

## 3. Predictive Forecasting - Show Future Issues

```python
def render_predictions(session):
    """Display predicted issues for next 24-48 hours."""
    if not session.predicted_issues or len(session.predicted_issues) == 0:
        return
    
    st.markdown("## 🔮 Predicted Issues (Next 24-48 Hours)")
    st.markdown("These issues will likely appear soon based on current trends.")
    
    # Group by urgency
    critical = [p for p in session.predicted_issues if p.urgency == "critical"]
    high = [p for p in session.predicted_issues if p.urgency == "high"]
    medium = [p for p in session.predicted_issues if p.urgency == "medium"]
    
    if critical:
        st.error(f"🚨 **CRITICAL** ({len(critical)} issue(s))")
        for pred in critical:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Device", pred.device)
            with col2:
                st.metric("ETA", f"{pred.eta_hours:.1f}h")
            with col3:
                st.metric("Confidence", f"{pred.confidence:.0%}")
            st.write(f"**Fix:** {pred.suggested_fix}")
            st.divider()
    
    if high:
        st.warning(f"⚠️  **HIGH** ({len(high)} issue(s))")
        for pred in high[:3]:  # Show top 3
            st.write(f"• {pred.device}: {pred.issue_type} ({pred.eta_hours:.1f}h)")
    
    if medium:
        st.info(f"📋 **MEDIUM** ({len(medium)} issue(s)) - Monitor these")
```

**Integration point:** New tab or sidebar section.

---

## 4. AI Hypothesis Generator - Show Novel Approaches

```python
def render_generated_hypotheses(session):
    """Display AI-generated hypotheses for unknown issues."""
    if not session.generated_hypotheses or len(session.generated_hypotheses) == 0:
        return
    
    st.markdown("## 🤔 Generated Hypotheses")
    st.markdown(
        "Internal diagnosis couldn't determine the cause. "
        "Here are alternative hypotheses based on AI analysis:"
    )
    
    tabs = st.tabs([f"Hypothesis {i+1}" for i in range(len(session.generated_hypotheses))])
    
    for i, (tab, hyp) in enumerate(zip(tabs, session.generated_hypotheses)):
        with tab:
            st.metric("Confidence", f"{hyp.confidence:.0%}")
            
            st.markdown("### Hypothesis")
            st.write(hyp.hypothesis)
            
            st.markdown("### Why this could be the cause")
            st.write(hyp.reasoning)
            
            st.markdown("### How to verify")
            for step in hyp.test_steps:
                st.write(f"• {step}")
            
            if hyp.suggested_fix:
                st.markdown("### If confirmed, the fix is:")
                st.code(hyp.suggested_fix)
            
            if st.button(f"Test Hypothesis {i+1}"):
                st.info(f"Run the verification steps above, then report the results.")
```

**Integration point:** When diagnosis confidence is low (< 0.60).

---

## 5. Reinforcement Learning - Show Learning Stats

```python
def render_learning_report(troubleshooter):
    """Display learning statistics and improvement over time."""
    try:
        report = troubleshooter.learner.print_learning_report()
        
        st.markdown("## 📊 System Learning Progress")
        
        with st.expander("📈 Full Learning Report"):
            st.code(report, language="text")
        
        # Show top performing categories
        learning_data = troubleshooter.learner.get_learning_report()
        
        if learning_data["top_performing_categories"]:
            st.markdown("### ✅ Top Performing Categories")
            for cat in learning_data["top_performing_categories"][:3]:
                st.metric(
                    f"{cat['category']}",
                    f"{cat['success_rate']:.0%}",
                    f"{cat['total']} incidents"
                )
        
        if learning_data["needs_improvement_categories"]:
            st.markdown("### ⚠️ Categories Needing Improvement")
            for cat in learning_data["needs_improvement_categories"][:3]:
                st.metric(
                    f"{cat['category']}",
                    f"{cat['success_rate']:.0%}",
                    f"{cat['total']} incidents"
                )
        
        # Show current decision thresholds
        if learning_data["current_thresholds"]:
            st.markdown("### 🎯 Current Decision Thresholds")
            thresholds = learning_data["current_thresholds"]
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Confidence Threshold", f"{thresholds['confidence']:.2f}")
            with col2:
                st.metric("Success Rate", f"{thresholds['success_rate']:.2f}")
            with col3:
                st.metric("Precedent Count", thresholds['precedents'])
    
    except Exception as e:
        st.warning(f"Could not load learning report: {e}")
```

**Integration point:** New "📊 Learning" sidebar tab.

---

## 6. Network Health Scorer - Executive Dashboard

```python
def render_network_health_dashboard(session, troubleshooter, telemetry):
    """Display real-time network health score and recommendations."""
    if not telemetry:
        return
    
    try:
        health = troubleshooter.score_network_health(telemetry)
        
        st.markdown("## 🏥 Network Health Dashboard")
        st.markdown("---")
        
        # Main health metric
        col1, col2, col3 = st.columns(3)
        with col1:
            # Color code the health metric
            score = health['overall_health']
            if score >= 90:
                st.metric("🟢 Network Health", f"{score:.0f}/100", "Excellent")
            elif score >= 75:
                st.metric("🟡 Network Health", f"{score:.0f}/100", "Good")
            elif score >= 60:
                st.metric("🟠 Network Health", f"{score:.0f}/100", "Fair")
            else:
                st.metric("🔴 Network Health", f"{score:.0f}/100", "Critical")
        
        with col2:
            st.metric("Grade", health['health_grade'])
        
        with col3:
            st.write("**Status**")
            st.write(health['summary'])
        
        st.markdown("---")
        
        # Factor breakdown
        st.markdown("### Factor Breakdown")
        
        factors = health.get('factors', {})
        for factor_name, factor_data in factors.items():
            col1, col2 = st.columns([3, 1])
            
            with col1:
                # Progress bar for factor
                st.progress(factor_data['value'] / 100.0)
            
            with col2:
                st.write(f"**{factor_data['value']:.0f}%**")
            
            st.caption(factor_data['description'])
            
            if factor_data.get('recommendation'):
                st.info(f"💡 {factor_data['recommendation']}")
            
            st.divider()
    
    except Exception as e:
        st.warning(f"Could not calculate network health: {e}")
```

**Integration point:** New "🏥 Health" sidebar tab.

---

## Complete UI Integration Example

```python
def main():
    st.set_page_config(page_title="AI Net Studio", layout="wide")
    
    # Initialize troubleshooter with all 6 enhancements
    troubleshooter = AutonomousNetworkTroubleshooter(...)
    
    # Sidebar for navigation
    with st.sidebar:
        st.markdown("## 🎯 Views")
        view = st.radio(
            "Select View",
            ["🔧 Troubleshoot", "📊 Learning", "🏥 Health", "🔮 Predictions"]
        )
    
    # Get telemetry
    telemetry = collect_telemetry()
    
    if view == "🔧 Troubleshoot":
        # Existing troubleshooting UI
        mode = st.radio("Mode", ["🤖 Autonomous", "👨‍💼 On-Demand", "📚 Learning"])
        problem = st.text_area("Describe your problem")
        
        if st.button("🔍 Start Troubleshooting"):
            session = troubleshooter.troubleshoot(
                problem,
                operation_mode=mode.lower(),
                telemetry_metrics=telemetry
            )
            
            # Display all enhancements
            render_explanations(session)  # NEW
            render_device_coordination_plan(session, troubleshooter)  # NEW
            render_predictions(session)  # NEW
            render_generated_hypotheses(session)  # NEW
            
            # Existing UI elements
            render_fix_details(session.suggested_fix)
            render_execution_flow(session)
            render_results(session)
    
    elif view == "📊 Learning":
        render_learning_report(troubleshooter)  # NEW
    
    elif view == "🏥 Health":
        render_network_health_dashboard(session, troubleshooter, telemetry)  # NEW
    
    elif view == "🔮 Predictions":
        render_predictions(session)  # NEW

if __name__ == "__main__":
    main()
```

---

## Summary of Integration Points

| Enhancement | UI Component | Location |
|------------|------------|----------|
| **Explainability** | Expandable reasoning steps | After diagnosis |
| **Multi-Device Orchestrator** | Execution plan display | Before execute button |
| **Predictive Forecasting** | Issue timeline + urgency | New "Predictions" tab |
| **Hypothesis Generator** | Alternative hypotheses | When diagnosis fails |
| **Reinforcement Learning** | Stats + thresholds | New "Learning" tab |
| **Network Health Scorer** | Dashboard + recommendations | New "Health" tab |

---

## Testing the Integration

```python
# To test all 6 enhancements:
streamlit run streamlit_autonomous_ui.py

# Typical flow:
1. Select "On-Demand" mode
2. Enter a complex problem description
3. See explanations for each decision (NEW)
4. If multi-device: see orchestration plan (NEW)
5. Check predictions tab to see predicted issues (NEW)
6. If low confidence: see generated hypotheses (NEW)
7. Check learning tab for statistics (NEW)
8. Check health tab for network dashboard (NEW)
```

---

## Next Steps

1. **Copy integration code** into `streamlit_autonomous_ui.py`
2. **Test with real telemetry** data
3. **Customize styling** to match your brand
4. **Add more telemetry sources** (SNMP, Prometheus, etc.)
5. **Monitor performance** on prediction accuracy

All 6 enhancements are now ready to be displayed to users! 🎉
