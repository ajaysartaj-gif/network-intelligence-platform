import os
import streamlit as st
from openai import OpenAI

# =========================================================
# GROQ CONFIG — completely free, no credits needed
# Model: llama-3.3-70b-versatile (Groq free tier)
# =========================================================

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MODEL = "llama-3.3-70b-versatile"

# =========================================================
# GET API KEY
# Priority: Streamlit Secrets → os.environ → .env file
# =========================================================

def get_api_key() -> str:
    # 1. Streamlit Secrets (Cloud + local .streamlit/secrets.toml)
    try:
        key = st.secrets.get("GROQ_API_KEY", "")
        if key and key.strip():
            return key.strip()
    except Exception:
        pass

    # 2. os.environ
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if key:
        return key

    # 3. .env file in repo root
    try:
        from dotenv import load_dotenv
        here = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(here)
        env_path = os.path.join(repo_root, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=False)
            key = os.environ.get("GROQ_API_KEY", "").strip()
            if key:
                return key
    except Exception:
        pass

    return ""


# =========================================================
# CREATE CLIENT
# =========================================================

def get_client():
    api_key = get_api_key()
    if not api_key:
        return None
    return OpenAI(
        api_key=api_key,
        base_url=GROQ_BASE_URL
    )


# =========================================================
# ASK AI
# =========================================================

def ask_ai(query: str) -> str:
    client = get_client()
    if not client:
        return "AI is unavailable. Please check your GROQ_API_KEY in .streamlit/secrets.toml"
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": """You are NetBrain AI, an enterprise-grade network operations assistant.

EXPERTISE AREAS:
- BGP, OSPF, MPLS, EVPN, VXLAN routing protocols
- Cisco IOS/IOS-XE/IOS-XR, Juniper JunOS, Arista EOS
- Firewall analysis (Palo Alto, Fortinet, Check Point)
- Network monitoring, root cause analysis, troubleshooting
- Change impact assessment and security incident response
- Compliance and audit requirements

RESPONSE GUIDELINES:
- Provide technically accurate answers with enterprise context
- Include specific CLI commands and configurations when relevant
- Be concise but comprehensive
- Use professional, technical language"""
                },
                {
                    "role": "user",
                    "content": query
                }
            ],
            temperature=0.1,
            max_tokens=800
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI Error: {str(e)}"
