"""
Regression for a real user report: the Copilot's chat history and current
context (selected devices, mode) disappeared on every browser refresh.

Root cause: Streamlit's st.session_state lives only for the lifetime of a
browser tab's WebSocket connection — a hard page refresh opens a brand-new
connection, so the script gets a completely empty session_state, identical
to a first-ever visit. initialize_session_state() unconditionally defaulted
every key (copilot_conversations, copilot_selected_devices, copilot_ai_mode,
copilot_autonomous_mode) to blank whenever they weren't already present,
with nothing persisting them anywhere else — so a refresh always looked
like starting over.

_persist_copilot_state()/_load_persisted_copilot_state() close this the
same way core/troubleshooting/memory.py and core/design_engine/memory.py
already persist their own state: a small local JSON file, restored by
initialize_session_state() only when session_state is genuinely fresh.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import copilot_engine


def test_persist_writes_current_session_state_to_disk(tmp_path, monkeypatch):
    state_path = tmp_path / "copilot_state.json"
    monkeypatch.setattr(copilot_engine, "_COPILOT_STATE_PATH", str(state_path))
    # raising=False: some test files in this suite stub `streamlit` as a
    # bare types.ModuleType() with no attributes at all (a pre-existing,
    # unrelated test-isolation quirk — see test_copilot_engine.py), so
    # `session_state`/`rerun` may not already exist on copilot_engine.st
    # depending on collection order. Setting a brand-new attribute on a
    # module stub is exactly what these tests need either way.
    monkeypatch.setattr(copilot_engine.st, "session_state", {
        "copilot_conversations": [{"id": "c1", "title": "New chat", "messages": []}],
        "copilot_active_conversation_id": "c1",
        "copilot_selected_devices": ["192.168.96.136"],
        "copilot_ai_mode": "troubleshoot",
        "copilot_autonomous_mode": True,
    }, raising=False)

    copilot_engine._persist_copilot_state()

    assert state_path.exists()
    import json
    saved = json.loads(state_path.read_text())
    assert saved["conversations"][0]["id"] == "c1"
    assert saved["active_conversation_id"] == "c1"
    assert saved["selected_devices"] == ["192.168.96.136"]
    assert saved["ai_mode"] == "troubleshoot"
    assert saved["autonomous_mode"] is True


def test_initialize_session_state_restores_from_disk_on_a_fresh_session(tmp_path, monkeypatch):
    """The hard-refresh case: session_state starts completely empty (as
    Streamlit hands it to a brand-new WebSocket connection), so
    initialize_session_state() must repopulate it from the persisted file
    instead of resetting everything to blank."""
    state_path = tmp_path / "copilot_state.json"
    import json
    state_path.write_text(json.dumps({
        "conversations": [{"id": "c1", "title": "OSPF ExStart", "messages": [
            {"role": "user", "content": "why OSPF stuck in ExStart"},
        ]}],
        "active_conversation_id": "c1",
        "selected_devices": ["192.168.96.136", "192.168.21.2"],
        "ai_mode": "troubleshoot",
        "autonomous_mode": True,
    }))
    monkeypatch.setattr(copilot_engine, "_COPILOT_STATE_PATH", str(state_path))
    monkeypatch.setattr(copilot_engine.st, "session_state", {}, raising=False)   # brand-new session

    copilot_engine.initialize_session_state()

    state = copilot_engine.st.session_state
    assert state["copilot_conversations"][0]["title"] == "OSPF ExStart"
    assert state["copilot_conversations"][0]["messages"][0]["content"] == "why OSPF stuck in ExStart"
    assert state["copilot_active_conversation_id"] == "c1"
    assert state["copilot_selected_devices"] == ["192.168.96.136", "192.168.21.2"]
    assert state["copilot_ai_mode"] == "troubleshoot"
    assert state["copilot_autonomous_mode"] is True


def test_initialize_session_state_stays_blank_with_no_persisted_file(tmp_path, monkeypatch):
    """A genuinely first-ever visit (no state file yet) must still start
    blank — restoring nothing is correct when there's nothing to restore."""
    state_path = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(copilot_engine, "_COPILOT_STATE_PATH", str(state_path))
    monkeypatch.setattr(copilot_engine.st, "session_state", {}, raising=False)

    copilot_engine.initialize_session_state()

    state = copilot_engine.st.session_state
    assert state["copilot_conversations"] == []
    assert state["copilot_selected_devices"] == []
    assert state["copilot_active_conversation_id"] is None


def test_full_round_trip_survives_a_simulated_refresh(tmp_path, monkeypatch):
    """End-to-end: populate state as real usage would, persist, wipe
    session_state entirely (simulating the new WebSocket connection a
    browser refresh creates), then confirm initialize_session_state()
    brings everything back."""
    state_path = tmp_path / "copilot_state.json"
    monkeypatch.setattr(copilot_engine, "_COPILOT_STATE_PATH", str(state_path))
    monkeypatch.setattr(copilot_engine.st, "session_state", {}, raising=False)

    copilot_engine.initialize_session_state()
    copilot_engine.st.session_state["copilot_conversations"] = [
        {"id": "c1", "title": "New chat", "messages": [
            {"role": "user", "content": "why OSPF stuck in ExStart"},
            {"role": "assistant", "content": "MTU mismatch between OSPF neighbors"},
        ]},
    ]
    copilot_engine.st.session_state["copilot_active_conversation_id"] = "c1"
    copilot_engine.st.session_state["copilot_selected_devices"] = ["192.168.96.136"]
    copilot_engine.st.session_state["copilot_ai_mode"] = "troubleshoot"
    copilot_engine._persist_copilot_state()

    # Simulate the page refresh: an entirely new, empty session_state.
    monkeypatch.setattr(copilot_engine.st, "session_state", {}, raising=False)
    copilot_engine.initialize_session_state()

    restored = copilot_engine.st.session_state
    assert len(restored["copilot_conversations"][0]["messages"]) == 2
    assert restored["copilot_selected_devices"] == ["192.168.96.136"]
    assert restored["copilot_ai_mode"] == "troubleshoot"


def test_rerun_persists_state_before_invoking_st_rerun(monkeypatch):
    """st.rerun() halts the script immediately (it raises internally) — any
    mutation made just before it must already be on disk, not queued for
    'later', since there is no 'later' in that script run."""
    calls = []
    monkeypatch.setattr(copilot_engine, "_persist_copilot_state", lambda: calls.append("persist"))
    monkeypatch.setattr(copilot_engine.st, "rerun", lambda: calls.append("rerun"), raising=False)

    copilot_engine._rerun()

    assert calls == ["persist", "rerun"]
