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
