import os
import streamlit as st
from openai import OpenAI

# =========================================================
# MODEL CONFIG
# =========================================================

# Free model — no credits needed
MODEL = "deepseek/deepseek-chat-v3-0324:free"

# =========================================================
# GET API KEY — checks all possible sources in order
# =========================================================

def get_api_key() -> str:
    """
    Load the OpenRouter API key from every possible source, in priority order:
      1. Streamlit Secrets       → works on Streamlit Cloud + local .streamlit/secrets.toml
      2. OS environment variable → works when set via export or Codespace secret
      3. .env file in repo root  → works locally via python-dotenv
    Returns empty string if not found anywhere.
    """

    # 1. Streamlit Secrets (Streamlit Cloud OR local .streamlit/secrets.toml)
    try:
        key = st.secrets.get("OPENROUTER_API_KEY", "")
        if key and key.strip():
            return key.strip()
    except Exception:
        pass

    # 2. Already in os.environ (Codespace secret, docker, export, etc.)
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key

    # 3. .env file in repo root (local development)
    try:
        from dotenv import load_dotenv
        # Find repo root — walk up from this file's location
        here = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(here)   # core/ → repo root
        env_path = os.path.join(repo_root, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=False)
            key = os.environ.get("OPENROUTER_API_KEY", "").strip()
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
        base_url="https://openrouter.ai/api/v1"
    )

# =========================================================
# ASK AI
# =========================================================

def ask_ai(query: str) -> str:
    client = get_client()
    if not client:
        return "AI is unavailable. Please check your OPENROUTER_API_KEY in Secrets."
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
            max_tokens=1000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI Error: {str(e)}"
