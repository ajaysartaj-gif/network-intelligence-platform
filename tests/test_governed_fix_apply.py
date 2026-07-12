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
import types

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


def test_verification_warns_when_a_second_neighbor_is_still_not_full(monkeypatch):
    """Regression: a real live session applied an OSPF mtu-ignore fix that
    resolved ONE neighbor (now FULL) while a SECOND, separate neighbor on the
    same device remained stuck in EXSTART -- easy to miss when skimming two
    similar-looking table rows -- and nothing flagged the inconsistency
    before the human clicked "Confirms Fixed". _apply_ts_fix must surface a
    deterministic warning from the fresh verification text itself."""
    fake_ie = FakeIntentEngine()
    two_neighbor_output = (
        "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
        "192.168.21.2      1   FULL/DR         00:00:34    192.168.21.2    GigabitEthernet2/0\n"
        "192.168.20.2      1   EXSTART/BDR     00:00:39    192.168.20.2    GigabitEthernet1/0\n"
    )
    fake_ie._ssh_collect = lambda device, cmds: FakeDR({c: two_neighbor_output for c in cmds})
    monkeypatch.setattr(copilot_engine, "_build_intent_engine", lambda call_ai_fn, devices: fake_ie)
    pending = _pending_state(["ip ospf mtu-ignore"], verification=["show ip ospf neighbor"],
                             root_cause="MTU mismatch between OSPF neighbors prevents DBD packet exchange")
    result = copilot_engine._apply_ts_fix(None, pending)

    assert result["applied_any"] is True
    warnings = result["verification_warnings"]
    assert "10.0.0.1" in warnings
    assert "192.168.20.2" in warnings["10.0.0.1"]
    assert "EXSTART" in warnings["10.0.0.1"]
    assert "192.168.21.2" not in warnings["10.0.0.1"]  # the FULL neighbor isn't flagged


def test_verification_no_warning_when_all_neighbors_full(monkeypatch):
    fake_ie = FakeIntentEngine()
    all_full_output = (
        "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
        "192.168.21.2      1   FULL/DR         00:00:34    192.168.21.2    GigabitEthernet2/0\n"
    )
    fake_ie._ssh_collect = lambda device, cmds: FakeDR({c: all_full_output for c in cmds})
    monkeypatch.setattr(copilot_engine, "_build_intent_engine", lambda call_ai_fn, devices: fake_ie)
    pending = _pending_state(["ip ospf mtu-ignore"], verification=["show ip ospf neighbor"],
                             root_cause="MTU mismatch between OSPF neighbors prevents DBD packet exchange")
    result = copilot_engine._apply_ts_fix(None, pending)
    assert result["verification_warnings"] == {}


def test_not_full_neighbors_returns_structured_targets():
    """_not_full_neighbors must capture ip/state/interface for each non-FULL
    row (the LOCAL interface facing that neighbor — the last column) so a
    caller can scope a follow-up investigation, not just warn about it."""
    output = (
        "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
        "192.168.21.2      1   FULL/DR         00:00:34    192.168.21.2    GigabitEthernet2/0\n"
        "192.168.20.2      1   EXSTART/BDR     00:00:39    192.168.20.2    GigabitEthernet1/0\n"
    )
    targets = copilot_engine._not_full_neighbors("ospf", output)
    assert targets == [{"ip": "192.168.20.2", "state": "EXSTART", "interface": "GigabitEthernet1/0"}]


# ── Auto-continue investigating a remaining broken neighbor ─────────────────
class _FakeSession:
    def __init__(self, fix=None, verification=None, goal_devices=None):
        self.fix = fix
        self.verification = verification
        self.goal = types.SimpleNamespace(devices=goal_devices or [])


class _FakeReport:
    def __init__(self, markdown, session):
        self._markdown = markdown
        self.session = session

    def to_markdown(self):
        return self._markdown


class _FakeFollowUpEngine:
    """Stands in for core.troubleshooting.TroubleshootingEngine — records the
    query/devices it was invoked with and returns a pre-built report."""
    last_devices = None
    last_query = None
    report_to_return = None

    def __init__(self, ai_call, devices, gateway, config):
        _FakeFollowUpEngine.last_devices = devices

    def run(self, query):
        _FakeFollowUpEngine.last_query = query
        return _FakeFollowUpEngine.report_to_return


def test_continue_investigation_noop_when_nothing_still_broken(monkeypatch):
    pending = _pending_state(["ip ospf mtu-ignore"], verification=["show ip ospf neighbor"])
    pending["verification_targets"] = {}
    cont = copilot_engine._continue_investigation_if_needed(None, pending)
    assert cont == {"messages": [], "next_pending_state": {}}


def test_continue_investigation_scopes_a_fresh_run_and_surfaces_a_new_fix(monkeypatch):
    dev = FakeDevice("10.0.0.1", "R1")
    pending = _pending_state(["ip ospf mtu-ignore"], verification=["show ip ospf neighbor"])
    pending["devices"] = [dev]
    pending["verification_targets"] = {
        "10.0.0.1": [{"ip": "192.168.20.2", "state": "EXSTART", "interface": "GigabitEthernet1/0"}]
    }

    fake_fix = types.SimpleNamespace(
        root_cause="Timer mismatch on GigabitEthernet1/0",
        config_commands=["ip ospf dead-interval 40"], rollback_commands=["no ip ospf dead-interval 40"])
    fake_verification = types.SimpleNamespace(commands=["show ip ospf neighbor"])
    session = _FakeSession(fix=fake_fix, verification=fake_verification, goal_devices=["10.0.0.1"])
    _FakeFollowUpEngine.report_to_return = _FakeReport("### follow-up report", session)

    monkeypatch.setattr(copilot_engine, "_make_troubleshooting_gateway", lambda call_ai_fn, devices: object())
    import core.troubleshooting as ts_module
    monkeypatch.setattr(ts_module, "TroubleshootingEngine", _FakeFollowUpEngine)

    cont = copilot_engine._continue_investigation_if_needed(None, pending)

    assert _FakeFollowUpEngine.last_devices == [dev]
    assert "192.168.20.2" in _FakeFollowUpEngine.last_query
    assert "GigabitEthernet1/0" in _FakeFollowUpEngine.last_query
    assert "EXSTART" in _FakeFollowUpEngine.last_query
    assert len(cont["messages"]) == 1
    assert "follow-up report" in cont["messages"][0]["content"]
    assert cont["next_pending_state"]["kind"] == "ts_fix"
    assert cont["next_pending_state"]["fix_commands"] == ["ip ospf dead-interval 40"]
    assert cont["next_pending_state"]["devices"] == [dev]


def test_continue_investigation_clears_state_when_followup_has_no_fix(monkeypatch):
    dev = FakeDevice("10.0.0.1", "R1")
    pending = _pending_state(["ip ospf mtu-ignore"], verification=["show ip ospf neighbor"])
    pending["devices"] = [dev]
    pending["verification_targets"] = {
        "10.0.0.1": [{"ip": "192.168.20.2", "state": "EXSTART", "interface": "GigabitEthernet1/0"}]
    }
    session = _FakeSession(fix=None, verification=None, goal_devices=["10.0.0.1"])
    _FakeFollowUpEngine.report_to_return = _FakeReport("### escalated, no fix found", session)

    monkeypatch.setattr(copilot_engine, "_make_troubleshooting_gateway", lambda call_ai_fn, devices: object())
    import core.troubleshooting as ts_module
    monkeypatch.setattr(ts_module, "TroubleshootingEngine", _FakeFollowUpEngine)

    cont = copilot_engine._continue_investigation_if_needed(None, pending)
    assert cont["next_pending_state"] == {}
    assert "escalated, no fix found" in cont["messages"][0]["content"]


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
        # dsn="" forces local SQLite regardless of NETBRAIN_MEMORY_DSN in
        # os.environ — see the matching comment in tests/test_supply_chain.py.
        # This suite exercises GovernanceEngine, whose autonomy/policy stack
        # can trigger a lazy `import app` that bridges the real Supabase DSN
        # into os.environ for the rest of the process; without this, these
        # tests (and any test file run after them in the same pytest
        # process) would silently write to the real production database.
        memory=OperationalMemory(db_path=str(tmp_path / "memory.sqlite"), dsn=""),
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


def test_record_ts_outcome_closes_the_live_session_as_resolved(tmp_path, monkeypatch):
    """The terminal-status gap: RESOLVED_PENDING_APPROVAL used to sit forever
    with no write-back once a human actually confirmed the fix worked.
    _record_ts_outcome must mutate the SAME Session object it was given
    (pending_state["session"]) via Session.close(), not just record learning."""
    monkeypatch.delenv("NETBRAIN_MEMORY_DSN", raising=False)
    import core.knowledge.compiler.supply_chain as sc_mod
    from core.troubleshooting.models import ResolutionStatus, Session
    sc = _real_supply_chain(tmp_path)
    monkeypatch.setattr(sc_mod, "NetworkIntelligenceSupplyChain", lambda: sc)

    session = Session()
    session.status = ResolutionStatus.RESOLVED_PENDING_APPROVAL
    pending = _pending_state(["ip ospf mtu-ignore"])
    pending["session"] = session

    copilot_engine._record_ts_outcome(pending, success=True)
    assert session.status == ResolutionStatus.RESOLVED


def test_record_ts_outcome_closes_the_live_session_as_unresolved(tmp_path, monkeypatch):
    monkeypatch.delenv("NETBRAIN_MEMORY_DSN", raising=False)
    import core.knowledge.compiler.supply_chain as sc_mod
    from core.troubleshooting.models import ResolutionStatus, Session
    sc = _real_supply_chain(tmp_path)
    monkeypatch.setattr(sc_mod, "NetworkIntelligenceSupplyChain", lambda: sc)

    session = Session()
    session.status = ResolutionStatus.RESOLVED_PENDING_APPROVAL
    pending = _pending_state(["ip ospf mtu-ignore"])
    pending["session"] = session

    copilot_engine._record_ts_outcome(pending, success=False)
    assert session.status == ResolutionStatus.UNRESOLVED


def test_record_ts_outcome_tolerates_pending_state_with_no_session(tmp_path, monkeypatch):
    """Older/other pending_state dicts (e.g. built before this change, or in
    a code path that never attached a session) must not raise."""
    monkeypatch.delenv("NETBRAIN_MEMORY_DSN", raising=False)
    import core.knowledge.compiler.supply_chain as sc_mod
    sc = _real_supply_chain(tmp_path)
    monkeypatch.setattr(sc_mod, "NetworkIntelligenceSupplyChain", lambda: sc)

    pending = _pending_state(["ip ospf mtu-ignore"])  # no "session" key
    msg = copilot_engine._record_ts_outcome(pending, success=True)
    assert "resolved" in msg.lower()
