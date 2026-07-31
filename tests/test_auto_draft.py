"""
Tests for core/knowledge/compiler/auto_draft.py — the offline knowledge
drafter (Build item A of the industry-wide scaling plan). Uses a fake
ai_call (same convention every other test in this suite already uses —
nothing here hits a real LLM), so these prove the PLUMBING (retrieval,
schema round-trip, idempotent registration) works correctly regardless of
what a real model returns.

register_relationship() mutates real source files by design (that's the
whole point — "auto-publish, no review gate") so these tests redirect it
at throwaway copies via monkeypatch, never the actual repo files.
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.knowledge.compiler.auto_draft as auto_draft
from core.knowledge.compiler.completeness_check import _parse_corpus_params


def test_load_prose_chunks_splits_real_vrrp_corpus_into_sections():
    chunks = auto_draft.load_prose_chunks("vrrp")
    assert len(chunks) > 1, chunks
    assert all(c.rel == "vrrp" for c in chunks)
    assert any("master" in c.text.lower() for c in chunks)


def test_load_prose_chunks_empty_for_uningested_protocol():
    assert auto_draft.load_prose_chunks("no_such_protocol_xyz") == []


def _fake_ai_call(prompt: str) -> str:
    assert "vrrp_pairing" in prompt
    assert "SOURCE:" in prompt
    return json.dumps({
        "relationship_type": "vrrp_pairing",
        "enumerate_intent": "show vrrp brief",
        "healthy_states": ["MASTER", "BACKUP"],
        "parameters": [
            {"name": "vrrp_group_number", "relation": "must_equal", "fatal_if_violated": True,
             "read_intent": "vrrp_group_number", "symptom_if_violated": "routers never pair",
             "applies_when": "", "provenance": "vrrp.txt §test"},
            {"name": "vrrp_priority", "relation": "must_differ", "fatal_if_violated": False,
             "read_intent": "vrrp_priority", "symptom_if_violated": "election tie-breaks on IP",
             "applies_when": "", "provenance": "vrrp.txt §test"},
        ],
    })


def test_draft_match_parameters_produces_valid_knowledge_package():
    kp = auto_draft.draft_match_parameters("vrrp_pairing", "vrrp", _fake_ai_call)
    assert kp.relationship_type == "vrrp_pairing"
    assert {p.name for p in kp.parameters} == {"vrrp_group_number", "vrrp_priority"}


def test_draft_match_parameters_raises_for_uningested_protocol():
    import pytest
    with pytest.raises(ValueError):
        auto_draft.draft_match_parameters("nope_pairing", "no_such_protocol_xyz", _fake_ai_call)


def test_persist_corpus_file_round_trips_through_the_real_parser(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_draft, "_CORPUS_DIR", str(tmp_path))
    kp = auto_draft.draft_match_parameters("vrrp_pairing", "vrrp", _fake_ai_call)
    path = auto_draft.persist_corpus_file(kp, "vrrp_pairing")

    params = _parse_corpus_params(path)
    assert {p["name"] for p in params} == {"vrrp_group_number", "vrrp_priority"}
    by_name = {p["name"]: p for p in params}
    assert by_name["vrrp_group_number"]["relation"] == "must_equal"
    assert by_name["vrrp_group_number"]["fatal"] == "true"
    assert by_name["vrrp_priority"]["relation"] == "must_differ"
    assert by_name["vrrp_priority"]["fatal"] == "false"


def test_register_relationship_inserts_into_throwaway_copies(tmp_path, monkeypatch):
    real_bridge = auto_draft._mismatch_bridge_path()
    real_adapter = auto_draft._gateway_adapter_path()
    fake_bridge = tmp_path / "mismatch_bridge.py"
    fake_adapter = tmp_path / "gateway_adapter.py"
    shutil.copy(real_bridge, fake_bridge)
    shutil.copy(real_adapter, fake_adapter)

    monkeypatch.setattr(auto_draft, "_mismatch_bridge_path", lambda: str(fake_bridge))
    monkeypatch.setattr(auto_draft, "_gateway_adapter_path", lambda: str(fake_adapter))

    # A relationship_type that could never legitimately already exist in the
    # real repo files, so "the real files were untouched" stays a valid
    # assertion regardless of what's been genuinely registered there since
    # (e.g. vrrp_pairing itself, drafted for real earlier this session).
    fixture_rel, fixture_protocol = "zzz_test_fixture_pairing", "zzz_test_fixture_protocol"
    auto_draft.register_relationship(fixture_rel, fixture_protocol)

    bridge_text = fake_bridge.read_text()
    adapter_text = fake_adapter.read_text()
    assert f'"{fixture_rel}": ("{fixture_protocol}",)' in bridge_text
    assert f'"{fixture_rel}": "{fixture_protocol}"' in adapter_text
    # both files must still be syntactically valid Python after the insert
    import ast
    ast.parse(bridge_text)
    ast.parse(adapter_text)

    # idempotent: registering again doesn't duplicate the line
    auto_draft.register_relationship(fixture_rel, fixture_protocol)
    assert fake_bridge.read_text().count(f'"{fixture_rel}": ("{fixture_protocol}",)') == 1
    assert fake_adapter.read_text().count(f'"{fixture_rel}": "{fixture_protocol}"') == 1

    # the real repo files were never touched
    with open(real_bridge) as f:
        assert fixture_rel not in f.read()
    with open(real_adapter) as f:
        assert fixture_rel not in f.read()
