
"""
NetBrain AI — Stable Edition
"""

# =========================================================
# STREAMLIT CONFIG (MUST BE FIRST)
# =========================================================

import streamlit as st

st.set_page_config(
    page_title="NetBrain AI",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================================
# IMPORTS
# =========================================================

import os
import time
import random
import logging
from typing import List, Dict

import pandas as pd

# =========================================================
# SAFE OPTIONAL IMPORTS
# =========================================================

OPENAI_AVAILABLE = False

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)

# =========================================================
# SAFE DATABASE IMPORTS
# =========================================================

DATABASE_AVAILABLE = False

try:
    from database.database import (
        seed_database,
        get_devices,
        get_incidents,
        get_changes,
        get_auto_actions,
    )

    DATABASE_AVAILABLE = True

except Exception as e:
    logger.warning(f"Database import failed: {e}")
    DATABASE_AVAILABLE = False

# =========================================================
# WORKSPACES
# =========================================================

try:
    from config.workspaces import WORKSPACES
except Exception:
    WORKSPACES = [
        ("operations", "⚡", "Operations"),
        ("incident", "🚨", "Incidents"),
        ("topology", "🗺", "Topology"),
        ("security", "🔒", "Security"),
        ("executive", "📈", "Executive"),
    ]

# =========================================================
# SESSION STATE
# =========================================================

DEFAULTS = {
    "workspace": "operations",
    "chat_history": [],
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

# =========================================================
# DATABASE INIT
# =========================================================

if DATABASE_AVAILABLE:
    try:
        seed_database()
    except Exception as e:
        logger.warning(f"Database seed failed: {e}")

# =========================================================
# AI CONFIG
# =========================================================

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
MODEL_NAME = "anthropic/claude-3.5-sonnet"


def get_api_key():
    try:
        return st.secrets.get("OPENROUTER_API_KEY", "")
    except Exception:
        return os.environ.get("OPENROUTER_API_KEY", "")


@st.cache_resource

def get_ai_client():
    if not OPENAI_AVAILABLE:
        return None

    key = get_api_key()

    if not key:
        return None

    try:
        return OpenAI(
            api_key=key,
            base_url=OPENROUTER_BASE,
        )
    except Exception:
        return None


SYSTEM_PROMPT = """
You are NetBrain AI.
You are an enterprise network operations assistant.
Focus on troubleshooting, root cause analysis,
and operational guidance.
"""


def call_ai(user_query: str):
    client = get_ai_client()

    if client is None:
        return "AI unavailable. Configure OPENROUTER_API_KEY in Streamlit Secrets."

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": user_query,
                }
            ],
            max_tokens=1200,
            temperature=0.2,
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"AI Error: {str(e)}"

# =========================================================
# SAMPLE DATA
# =========================================================


def get_sample_devices():
    return pd.DataFrame({
        "Hostname": [
            "DEL-CORE-01",
            "MUM-EDGE-01",
            "BLR-FW-01",
            "HYD-LEAF-02",
        ],
        "Status": [
            "Healthy",
            "Warning",
            "Critical",
            "Healthy",
        ],
        "CPU": [
            "32%",
            "74%",
            "91%",
            "28%",
        ],
        "Memory": [
            "44%",
            "62%",
            "87%",
            "39%",
        ],
    })


# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:
    st.title("🧠 NetBrain AI")
    st.caption("Autonomous Network OS")

    st.divider()

    for ws_id, icon, label in WORKSPACES:

        if st.button(
            f"{icon} {label}",
            use_container_width=True,
            key=f"ws_{ws_id}",
        ):
            st.session_state.workspace = ws_id

    st.divider()

    st.markdown("### Platform Status")

    st.success("Streamlit Online")

    if OPENAI_AVAILABLE:
        st.success("AI SDK Loaded")
    else:
        st.warning("AI SDK Missing")

    if DATABASE_AVAILABLE:
        st.success("Database Connected")
    else:
        st.warning("Database Offline")

# =========================================================
# HEADER
# =========================================================

st.title("🧠 NetBrain AI")
st.caption("Enterprise Autonomous Network Operations Platform")

# =========================================================
# METRICS
# =========================================================

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Devices", "248")

with col2:
    st.metric("Incidents", "12", "-2")

with col3:
    st.metric("Automation", "87%")

with col4:
    st.metric("AI Confidence", "92%")

# =========================================================
# AI SEARCH
# =========================================================

st.divider()

query = st.text_input(
    "Ask NetBrain AI",
    placeholder="Why is BGP flapping in Delhi DC?",
)

if query:

    with st.spinner("Analyzing telemetry and topology..."):
        time.sleep(2)

    from core.ai_engine import ask_ai
         ai_response = ask_ai(query)

    st.markdown("## AI Analysis")
    st.write(ai_response)

# =========================================================
# DEVICES
# =========================================================

st.divider()
st.subheader("Network Devices")

try:
    if DATABASE_AVAILABLE:
        devices = get_devices()

        if devices:
            st.dataframe(pd.DataFrame(devices))
        else:
            st.dataframe(get_sample_devices())
    else:
        st.dataframe(get_sample_devices())

except Exception:
    st.dataframe(get_sample_devices())

# =========================================================
# INCIDENTS
# =========================================================

st.divider()
st.subheader("Active Incidents")

sample_incidents = [
    "BGP flap detected in Mumbai edge",
    "Firewall CPU high in Bangalore",
    "WAN latency spike in Delhi",
    "Packet drops on Core Switch",
]

for incident in sample_incidents:
    st.warning(incident)

# =========================================================
# FOOTER
# =========================================================

st.divider()

st.caption("NetBrain AI v2.0")
