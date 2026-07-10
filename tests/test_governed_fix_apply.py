"""
Tests for the governed troubleshooting fix-apply path (core/copilot_engine.py):

  - _apply_ts_fix() now runs core.governance.engine.GovernanceEngine.govern()
    BEFORE any command reaches a device — a non-compliant command must never
    reach _ssh_apply, and an approved apply must re-collect the verification
    commands immediately afterward.
  - _record_ts_outcome() is the one live-runtime call site for
    core.knowledge.compiler.supply_chain.NetworkIntelligenceSupplyChain's
    record_resolution/record_failed_resolution/learn_from_incident — verified
    against a REAL, temp-db-backed instance (same isolation pattern as
    tests/test_supply_chain.py), not a bare mock, so this proves the actual
    facade methods run correctly, not just that "some" method was called.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import copilot_engine
from core.knowledge.compiler.supply_chain import NetworkIntelligenceSupplyChain
from core.knowledge.enterprise.knowledge_layer import EnterpriseKnowledgeLayer
from core.knowledge.rag.embedder import FakeEmbedder
from core.knowledge.rag.rag_engine import RAGEngine
from core.knowledge_graph import KnowledgeGraph
from core.intelligence.operational_memory import OperationalMemory


class FakeDevice:
    def __init__(self, ip, hostname):
        self.ip, self.hostname, self.device_type = ip, hostname, "cisco_ios"


class FakeDR:
    def __init__(self, outputs):
        self.outputs = outputs


class FakeIntentEngine:
    """Stands in for core.intent_engine.IntentEngine so these tests never
    open a real SSH connection."""
    def __init__(self):
        self.applied = []
        self.collect_calls = []

    def _ssh_apply(self, device, cfg):
        self.applied.append((device.ip, list(cfg)))

    def _ssh_collect(self, device, cmds):
        self.collect_calls.append((device.ip, list(cmds)))
        return FakeDR({c: f"fresh output for {c}" for c in cmds})


def _pending_state(fix_commands, rollback=None, verification=None,
                   root_cause="MTU mismatch between OSPF neighbors"):
    dev = FakeDevice("10.0.0.1", "R1")
    return {
        "kind": "ts_fix", "root_cause": root_cause, "fix_commands": fix_commands,
        "rollback_commands": rollback or [], "verification_commands": verification or [],
        "target_ip": dev.ip, "devices": [dev],
    }


# ── 1a. Governance gating ────────────────────────────────────────────────────
def test_governance_blocks_noncompliant_command(monkeypatch):
    fake_ie = FakeIntentEngine()
    monkeypatch.setattr(copilot_engine, "_build_intent_engine", lambda call_ai_fn, devices: fake_ie)
    pending = _pending_state(["no ip address"])  # matches CONFIG_DENY_PATTERNS
    result = copilot_engine._apply_ts_fix(None, pending)

    assert fake_ie.applied == [], "a compliance-blocked command must never reach _ssh_apply"
    assert result["applied_any"] is False
    assert any("Blocked" in line for line in result["summary_lines"]), result["summary_lines"]


def test_governance_approves_and_reverifies(monkeypatch):
    fake_ie = FakeIntentEngine()
    monkeypatch.setattr(copilot_engine, "_build_intent_engine", lambda call_ai_fn, devices: fake_ie)
    pending = _pending_state(["ip ospf mtu-ignore"], verification=["show ip ospf neighbor"])
    result = copilot_engine._apply_ts_fix(None, pending)

    assert fake_ie.applied == [("10.0.0.1", ["ip ospf mtu-ignore"])]
    assert result["applied_any"] is True
    assert any("Applied" in line for line in result["summary_lines"]), result["summary_lines"]
    # verification was actually re-run, not just displayed
    assert fake_ie.collect_calls == [("10.0.0.1", ["show ip ospf neighbor"])]
    assert "fresh output" in result["verification_output"]["10.0.0.1"]


def test_no_fix_commands_short_circuits_without_touching_governance_or_ssh(monkeypatch):
    fake_ie = FakeIntentEngine()
    monkeypatch.setattr(copilot_engine, "_build_intent_engine", lambda call_ai_fn, devices: fake_ie)
    pending = _pending_state([])
    result = copilot_engine._apply_ts_fix(None, pending)
    assert result["applied_any"] is False
    assert fake_ie.applied == []


# ── 1b. Operational learning feedback ────────────────────────────────────────
class _StubLearningEngine:
    def __init__(self):
        self.learn_from_calls = []

    def learn_from(self, event):
        self.learn_from_calls.append(event)
        return {"event": event.kind, "lessons_emitted": 1}

    def retrospect(self, **kwargs):
        return {}

    def digest(self):
        return {}


def _real_supply_chain(tmp_path):
    rag = RAGEngine(embedder=FakeEmbedder(), persist_dir=str(tmp_path / "chroma"),
                    collection_name="governed-fix-apply-test")
    return NetworkIntelligenceSupplyChain(
        layer=EnterpriseKnowledgeLayer(rag=rag),
        graph=KnowledgeGraph(),
        memory=OperationalMemory(db_path=str(tmp_path / "memory.sqlite")),
        learning_engine=_StubLearningEngine(),
    )


def test_record_ts_outcome_success_writes_real_resolution(tmp_path, monkeypatch):
    # Force local SQLite regardless of ambient NETBRAIN_MEMORY_DSN (bridged from
    # secrets in some environments) — this test's isolation depends on a fresh
    # temp-file backend, same assumption tests/test_supply_chain.py makes.
    monkeypatch.delenv("NETBRAIN_MEMORY_DSN", raising=False)
    import core.knowledge.compiler.supply_chain as sc_mod
    sc = _real_supply_chain(tmp_path)
    monkeypatch.setattr(sc_mod, "NetworkIntelligenceSupplyChain", lambda: sc)

    pending = _pending_state(["ip ospf mtu-ignore"])
    msg = copilot_engine._record_ts_outcome(pending, success=True)

    events = sc.memory.temporal()
    assert any(e["device"] == "10.0.0.1" for e in events), [e["device"] for e in events]
    assert sc.learning.learn_from_calls and sc.learning.learn_from_calls[0].success is True
    assert "resolved" in msg.lower()


def test_record_ts_outcome_failure_feeds_recurring_failure_detection(tmp_path, monkeypatch):
    monkeypatch.delenv("NETBRAIN_MEMORY_DSN", raising=False)
    import core.knowledge.compiler.supply_chain as sc_mod
    sc = _real_supply_chain(tmp_path)
    monkeypatch.setattr(sc_mod, "NetworkIntelligenceSupplyChain", lambda: sc)

    pending = _pending_state(["ip ospf mtu-ignore"], root_cause="MTU mismatch between OSPF neighbors")
    # record the SAME failing intent twice — recurring_failures() requires min_count
    copilot_engine._record_ts_outcome(pending, success=False)
    msg = copilot_engine._record_ts_outcome(pending, success=False)

    recurring = sc.memory.recurring_failures(min_count=2)
    assert recurring, "two identical failed resolutions must be detected as recurring"
    assert sc.learning.learn_from_calls[-1].success is False
    assert "unresolved" in msg.lower()
