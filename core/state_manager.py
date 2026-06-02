"""Session state lifecycle management with TTL and cleanup."""

from datetime import datetime, timedelta
import streamlit as st
from config import (
    MAX_CHAT_HISTORY,
    MAX_RESULTS_STORED,
    TTL_SIMULATION_MINUTES,
    TTL_RESULTS_MINUTES,
)


class SessionStateManager:
    """Manages session state lifecycle with automatic cleanup and TTL."""

    @staticmethod
    def cleanup():
        """Run on every rerun to clean expired data and limit memory."""
        now = datetime.utcnow()

        # Trim chat history to last N messages
        if "chat_msgs" in st.session_state:
            msgs = st.session_state.chat_msgs
            if len(msgs) > MAX_CHAT_HISTORY:
                st.session_state.chat_msgs = msgs[-MAX_CHAT_HISTORY:]

        # Remove expired twin results
        if "twin_result_meta" in st.session_state:
            meta = st.session_state["twin_result_meta"]
            if isinstance(meta, dict) and "timestamp" in meta:
                ts = meta["timestamp"]
                if isinstance(ts, datetime):
                    if now - ts > timedelta(minutes=TTL_SIMULATION_MINUTES):
                        if "twin_result" in st.session_state:
                            del st.session_state["twin_result"]
                        del st.session_state["twin_result_meta"]

        # Cap RAG results
        if "rag_results" in st.session_state:
            st.session_state.rag_results = st.session_state.rag_results[:MAX_RESULTS_STORED]

        # Cap MDQ results
        if "mdq_results" in st.session_state:
            st.session_state.mdq_results = st.session_state.mdq_results[-1:]

        # Clear temporary form state
        temp_keys = ["_nlpf", "_mdqf", "_chgf", "_sample_q"]
        for key in temp_keys:
            if key in st.session_state:
                del st.session_state[key]

    @staticmethod
    def init_defaults():
        """Initialize session state defaults once per session."""
        defaults = {
            "workspace": "operations",
            "persona": "noc",
            "chat_msgs": [],
            "chat_hist": [],
            "kg_selected": None,
            "mdq_results": None,
            "nlp_results": None,
            "rag_results": [],
            "design_output": None,
            "auto_mode": "human",
            "user_role": "admin",
            "user_name": "engineer",
            "styles_loaded": False,
        }
        for key, default_val in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = default_val

    @staticmethod
    def clear():
        """Clear all session state (for logout)."""
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        SessionStateManager.init_defaults()
