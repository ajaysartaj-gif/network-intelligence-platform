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
You are NetBrain AI, an enterprise-grade network operations assistant.

EXPERTISE AREAS:
- BGP, OSPF, MPLS, EVPN, VXLAN routing protocols
- Cisco IOS/IOS-XE/IOS-XR, Juniper JunOS, Arista EOS
- Firewall analysis (Palo Alto, Fortinet, Check Point)
- Network monitoring and observability
- Root cause analysis and troubleshooting
- Change impact assessment
- Security incident response
- Compliance and audit requirements

RESPONSE GUIDELINES:
- Provide technical accuracy with enterprise context
- Include specific commands, configurations, or log patterns when relevant
- Explain complex concepts clearly for network engineers
- Suggest next diagnostic steps when appropriate
- Reference industry best practices
- Be concise but comprehensive
- Use professional, technical language

If the query is unclear, ask for clarification on specific symptoms, devices, or protocols.
"""
                },
                {
                    "role": "user",
                    "content": query
                }
            ],
            temperature=0.1,
            max_tokens=1200
        )

        return response.choices[0].message.content

    except Exception as e:

        return f"AI Error: {str(e)}"
