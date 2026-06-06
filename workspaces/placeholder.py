"""Placeholder workspace structure - expand as needed."""

import streamlit as st
from ui.components import section_header, ai_insight_card, metric_grid
from database.manager import get_db_manager


def render():
    """Render placeholder workspace."""
    section_header(
        "Workspace Template",
        "Use this structure for new workspaces"
    )

    ai_insight_card(
        "AI Analysis",
        "Template insight card shows here",
        confidence=85,
        sources=["Template"],
    )

    metric_grid([
        {"label": "Metric 1", "value": "100", "delta": "+5%"},
        {"label": "Metric 2", "value": "200", "delta": "-2%"},
    ])

    st.markdown("---")
    st.info("📝 Add workspace content here")
