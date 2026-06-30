"""
Command Resolver · Behavioral Tests (command-agnostic)
======================================================
Locks the resolution ORDER (cache → RAG → MCP → grounded AI) and proves the
resolver is not a lookup table: it returns whatever the chain yields, using
random throwaway tokens. No real network command appears anywhere.

Run: python -m tests.test_command_resolver
"""
from __future__ import annotations

import os
import tempfile
import uuid

import core.command_resolver as cr


def _fresh(tmp):
    cr._CACHE_PATH = tmp
    return cr.CommandResolver(ai_call=lambda p: "")


def _rand():
    return f"cmd{uuid.uuid4().hex[:6]}"


def test_chain_order_rag_then_mcp_then_ai():
    tmp = os.path.join(tempfile.mkdtemp(), "c.json")
    rag_cmd, mcp_cmd, ai_cmd = _rand(), _rand(), _rand()

    r = _fresh(tmp)
    r._from_rag = lambda *a: [rag_cmd]
    r._from_mcp = lambda *a: [mcp_cmd]
    r._from_ai = lambda *a: [ai_cmd]
    assert r.resolve("do something").source == "rag"          # RAG wins

    r2 = _fresh(tmp + "2")
    r2._from_rag = lambda *a: []
    r2._from_mcp = lambda *a: [mcp_cmd]
    r2._from_ai = lambda *a: [ai_cmd]
    res2 = r2.resolve("do something else")
    assert res2.source == "mcp" and res2.commands == [mcp_cmd]  # MCP only when RAG empty

    r3 = _fresh(tmp + "3")
    r3._from_rag = lambda *a: []
    r3._from_mcp = lambda *a: []
    r3._from_ai = lambda *a: [ai_cmd]
    assert r3.resolve("third thing").source == "ai"            # AI only when both empty


def test_cache_is_consulted_first():
    tmp = os.path.join(tempfile.mkdtemp(), "c.json")
    first = _rand()
    r = _fresh(tmp)
    r._from_rag = lambda *a: [first]
    p = "purpose " + _rand()
    assert r.resolve(p).source == "rag"
    # now RAG returns something different — but cache must win
    r._from_rag = lambda *a: [_rand()]
    again = r.resolve(p)
    assert again.source == "cache" and again.commands == [first]


def test_resolve_set_returns_phases_from_chain_not_a_table():
    tmp = os.path.join(tempfile.mkdtemp(), "c.json")
    token = _rand()
    r = _fresh(tmp)
    r._from_rag = lambda purpose, *a: [f"{token}-{purpose.split()[0]}"]
    out = r.resolve_set("some_new_anomaly_" + _rand())
    assert set(out) == {"diagnostic", "fix", "verify"}
    # commands came from the (stubbed) chain, keyed by purpose — not a static map
    assert all(any(token in c for c in cmds) for cmds in out.values())


def _run_all():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"PASS {name}")
    print("\nALL COMMAND-RESOLVER TESTS PASSED")


if __name__ == "__main__":
    _run_all()
