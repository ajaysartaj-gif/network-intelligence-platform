import sys
from pathlib import Path

from streamlit.errors import StreamlitAPIException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.copilot_engine import build_copilot_prompt


def test_build_copilot_prompt_includes_context_and_history():
    prompt = build_copilot_prompt(
        user_text="Why is the interface down?",
        ai_mode="Net Fix",
        selected_devices=["192.168.1.1"],
        device_context="Approved network devices:\n- R1 (192.168.1.1)",
        conversation_history=[
            {"role": "user", "content": "Check interface status"},
            {"role": "assistant", "content": "I will inspect it"},
        ],
    )

    assert "AI Mode: Net Fix" in prompt
    assert "Target devices: 192.168.1.1" in prompt
    assert "Approved network devices" in prompt
    assert "User: Check interface status" in prompt
    assert "Assistant: I will inspect it" in prompt
    assert "User question: Why is the interface down?" in prompt


def test_clear_copilot_main_input_handles_widget_state(monkeypatch):
    from core import copilot_engine

    class FailingWidgetState(dict):
        def __setitem__(self, key, value):
            if key == "copilot_main_input":
                raise StreamlitAPIException("widget state cannot be set")
            super().__setitem__(key, value)

    state = FailingWidgetState({"copilot_main_input": "hello"})
    monkeypatch.setattr(copilot_engine.st, "session_state", state)

    copilot_engine.clear_copilot_main_input()

    assert "copilot_main_input" not in state
