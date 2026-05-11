"""Design system and theme configuration."""

import streamlit as st


def load_theme():
    """Load CSS theme once per session."""
    if st.session_state.get("styles_loaded"):
        return

    # Load external CSS
    try:
        with open("ui/css/design_tokens.css", "r") as f:
            css = f.read()
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        # Fallback inline CSS if file not found
        st.markdown(f"<style>{_get_fallback_css()}</style>", unsafe_allow_html=True)

    st.session_state.styles_loaded = True


def _get_fallback_css() -> str:
    """Fallback CSS if design_tokens.css not found."""
    return """
    :root {
        --bg-base: #0d1117;
        --bg-surface: #161b22;
        --accent-blue: #2f81f7;
        --text-primary: #e6edf3;
        --text-secondary: #8b949e;
    }
    .nb-topbar { background: var(--bg-surface); padding: 12px 20px; border-bottom: 1px solid #21262d; }
    .nb-metric { background: var(--bg-surface); border-radius: 10px; padding: 14px; }
    .nb-dev { background: var(--bg-surface); border-radius: 10px; padding: 11px; }
    """
