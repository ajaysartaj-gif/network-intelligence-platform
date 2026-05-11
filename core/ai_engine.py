import os
import streamlit as st
from openai import OpenAI

# =========================================================
# MODEL CONFIG
# =========================================================

MODEL = "openai/gpt-4.1-mini"

# =========================================================
# GET API KEY
# =========================================================

def get_api_key():

    try:
        return st.secrets["OPENROUTER_API_KEY"]

    except Exception:
        return os.getenv("OPENROUTER_API_KEY", "")

# =========================================================
# CREATE CLIENT
# =========================================================

def get_client():

    api_key = get_api_key()

    if not api_key:
        return None

    return OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1"
    )

# =========================================================
# ASK AI
# =========================================================

def ask_ai(query: str):

    client = get_client()

    if not client:
        return "ERROR: OpenRouter API key missing."

    try:

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": """
You are NetBrain AI.

You are an expert enterprise network operations AI assistant.

Specialties:
- BGP
- OSPF
- MPLS
- EVPN
- VXLAN
- Firewall analysis
- Root cause analysis
- Multi-vendor troubleshooting
- Observability
- Incident investigation

Provide concise technical answers.
"""
                },
                {
                    "role": "user",
                    "content": query
                }
            ],
            temperature=0.2,
            max_tokens=1000
        )

        return response.choices[0].message.content

    except Exception as e:

        return f"AI Error: {str(e)}"
