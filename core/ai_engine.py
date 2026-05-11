from openai import OpenAI
import streamlit as st
import os

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

MODEL = "anthropic/claude-3.5-sonnet"


def get_api_key():

    try:
        return st.secrets["OPENROUTER_API_KEY"]
    except Exception:
        return os.getenv("OPENROUTER_API_KEY", "")


def get_client():

    key = get_api_key()

    if not key:
        return None

    return OpenAI(
        api_key=key,
        base_url=OPENROUTER_BASE,
    )


SYSTEM_PROMPT = """
You are NetBrain AI.

You are an enterprise network operations assistant.

Provide:
- root cause analysis
- troubleshooting
- network diagnostics
- operational guidance
"""


def ask_ai(query: str):

    client = get_client()

    if client is None:
        return "AI key missing."

    try:

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": query,
                }
            ],
            temperature=0.2,
            max_tokens=1200,
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"AI Error: {str(e)}"
