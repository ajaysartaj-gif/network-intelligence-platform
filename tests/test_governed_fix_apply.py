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
    def __init__(self, outputs, connected=True, error=None):
        self.outputs = outputs
        self.connected = connected
        self.error = error


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
    query/devices/excluded_causes/partial_causes it was invoked with and
    returns a pre-built report."""
    last_devices = None
    last_query = None
    last_excluded_causes = None
    last_partial_causes = None
    report_to_return = None

    def __init__(self, ai_call, devices, gateway, config, session_store=None):
        _FakeFollowUpEngine.last_devices = devices

    def run(self, query, excluded_causes=None, partial_causes=None):
        _FakeFollowUpEngine.last_query = query
        _FakeFollowUpEngine.last_excluded_causes = excluded_causes
        _FakeFollowUpEngine.last_partial_causes = partial_causes
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
        config_commands=["ip ospf dead-interval 40"], rollback_commands=["no ip ospf dead-interval 40"],
        target_devices=[])
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
    # The root cause the JUST-tried (and still-broken) fix addressed must be
    # excluded from the follow-up run — otherwise it can win again on its
    # own unchanged compiled prior, the exact repeating-fix loop a real
    # production report showed.
    assert _FakeFollowUpEngine.last_excluded_causes == [pending["root_cause"]]
    assert len(cont["messages"]) == 1
    assert "follow-up report" in cont["messages"][0]["content"]
    assert cont["next_pending_state"]["kind"] == "ts_fix"
    assert cont["next_pending_state"]["fix_commands"] == ["ip ospf dead-interval 40"]
    assert cont["next_pending_state"]["devices"] == [dev]
    # accumulates for a THIRD cycle, should this one also fail verification
    assert cont["next_pending_state"]["excluded_causes"] == [pending["root_cause"]]


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
        # dsn="" forces local SQLite regardless of AI_NET_STUDIO_MEMORY_DSN in
        # os.environ — see the matching comment in tests/test_supply_chain.py.
        # This suite exercises GovernanceEngine, whose autonomy/policy stack
        # can trigger a lazy `import app` that bridges the real Supabase DSN
        # into os.environ for the rest of the process; without this, these
        # tests (and any test file run after them in the same pytest
        # process) would silently write to the real production database.
        memory=OperationalMemory(db_path=str(tmp_path / "memory.sqlite"), dsn=""),
        learning_engine=_StubLearningEngine(),
    )


def test_troubleshooting_gateway_send_surfaces_connection_failure(monkeypatch):
    """Regression: _ssh_collect() never raises on a connection failure (bad
    host/port/credentials, GNS3 tunnel down, timeout) — it swallows the
    exception into DeviceResult.error and returns normally with
    outputs == {}. _make_troubleshooting_gateway's send() used to just
    `return dict(dr.outputs)` unconditionally, silently turning a real
    connection failure into an empty dict indistinguishable from "the
    device has nothing to report" — the exact "no observations collected,
    no explanation why" symptom a live user hit repeatedly. send() must
    now detect dr.connected is False and surface the real error instead."""
    class FakeIE:
        def _ssh_collect(self, device, cmds):
            return FakeDR({}, connected=False, error="TimeoutError: connect timed out")

    monkeypatch.setattr(copilot_engine, "_build_intent_engine", lambda call_ai_fn, devices: FakeIE())
    dev = FakeDevice("192.168.96.136", "R1")
    gw = copilot_engine._make_troubleshooting_gateway(None, [dev])

    out = gw._transport.send(dev, ["show ip ospf neighbor"])

    assert out, "must not silently return an empty dict on connection failure"
    text = out["show ip ospf neighbor"]
    # "error[...]:" prefix is the same convention
    # core.troubleshooting.engine._ingest_output() already recognizes as
    # "not evidence" — confirms this never gets fed to the parser/LLM as
    # if it were real CLI output.
    assert text.startswith("error["), text
    assert "connection failed" in text.lower()
    assert "192.168.96.136" in text
    assert "TimeoutError" in text


def test_troubleshooting_gateway_send_passes_through_real_output_when_connected(monkeypatch):
    class FakeIE:
        def _ssh_collect(self, device, cmds):
            return FakeDR({c: f"real output for {c}" for c in cmds}, connected=True)

    monkeypatch.setattr(copilot_engine, "_build_intent_engine", lambda call_ai_fn, devices: FakeIE())
    dev = FakeDevice("192.168.96.136", "R1")
    gw = copilot_engine._make_troubleshooting_gateway(None, [dev])

    out = gw._transport.send(dev, ["show ip ospf neighbor"])
    assert out == {"show ip ospf neighbor": "real output for show ip ospf neighbor"}


def test_record_ts_outcome_success_writes_real_resolution(tmp_path, monkeypatch):
    # Force local SQLite regardless of ambient NETBRAIN_MEMORY_DSN (bridged from
    # secrets in some environments) — this test's isolation depends on a fresh
    # temp-file backend, same assumption tests/test_supply_chain.py makes.
    monkeypatch.delenv("AI_NET_STUDIO_MEMORY_DSN", raising=False)
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
    monkeypatch.delenv("AI_NET_STUDIO_MEMORY_DSN", raising=False)
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
    monkeypatch.delenv("AI_NET_STUDIO_MEMORY_DSN", raising=False)
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
    monkeypatch.delenv("AI_NET_STUDIO_MEMORY_DSN", raising=False)
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


def test_target_neighbor_still_broken_true_when_root_causes_own_neighbor_still_not_full():
    pending = _pending_state(
        ["ip ospf mtu-ignore"],
        root_cause="interface_mtu must equal violated on ospf_adjacency between "
                   "10.0.0.1 and 10.0.0.2 (local=1500, remote=1200)")
    pending["verification_targets"] = {"10.0.0.1": [{"ip": "10.0.0.2", "state": "EXSTART", "interface": "Gi0/0"}]}
    assert copilot_engine._target_neighbor_still_broken(pending) is True


def test_target_neighbor_still_broken_false_when_a_different_neighbor_is_the_leftover():
    """The fix's OWN target (10.0.0.2) came back FULL — some UNRELATED
    neighbor (10.0.0.9) being separately broken must not block recording
    THIS fix as resolved."""
    pending = _pending_state(
        ["ip ospf mtu-ignore"],
        root_cause="interface_mtu must equal violated on ospf_adjacency between "
                   "10.0.0.1 and 10.0.0.2 (local=1500, remote=1200)")
    pending["verification_targets"] = {"10.0.0.1": [{"ip": "10.0.0.9", "state": "DOWN", "interface": "Gi0/1"}]}
    assert copilot_engine._target_neighbor_still_broken(pending) is False


def test_target_neighbor_still_broken_conservative_fallback_with_no_extractable_ip():
    """root_cause names no specific neighbor IP at all (e.g. a BGP cause
    like "Repeated TCP connection failures to the peer address") — cannot
    positively confirm the SAME neighbor is the leftover, so treat ANY
    still-not-full neighbor as ambiguous evidence against a plain
    "resolved" rather than silently allowing it through."""
    pending = _pending_state(["neighbor 10.0.0.2 ebgp-multihop 2"],
                             root_cause="Repeated TCP connection failures to the peer address")
    pending["verification_targets"] = {"10.0.0.1": [{"ip": "10.0.0.9", "state": "Active", "interface": ""}]}
    assert copilot_engine._target_neighbor_still_broken(pending) is True


def test_target_neighbor_still_broken_false_with_no_verification_targets_at_all():
    pending = _pending_state(["ip ospf mtu-ignore"])
    assert copilot_engine._target_neighbor_still_broken(pending) is False


def test_record_ts_outcome_downgrades_a_confirms_fixed_click_when_fresh_verification_disagrees(
        tmp_path, monkeypatch):
    """Regression for a real production report: 'Recorded as resolved' was
    followed, in the very next message, by 'Continuing — investigating the
    remaining issue' for the SAME neighbor the fresh post-apply
    verification had just shown still stuck in EXSTART. A Confirms Fixed
    click must not silently overwrite what verification just proved."""
    monkeypatch.delenv("AI_NET_STUDIO_MEMORY_DSN", raising=False)
    monkeypatch.delenv("NETBRAIN_MEMORY_DSN", raising=False)
    import core.knowledge.compiler.supply_chain as sc_mod
    from core.troubleshooting.models import ResolutionStatus, Session
    sc = _real_supply_chain(tmp_path)
    monkeypatch.setattr(sc_mod, "NetworkIntelligenceSupplyChain", lambda: sc)

    session = Session()
    session.status = ResolutionStatus.RESOLVED_PENDING_APPROVAL
    pending = _pending_state(
        ["ip ospf mtu-ignore"],
        root_cause="interface_mtu must equal violated on ospf_adjacency between "
                   "192.168.96.136 and 192.168.20.2 (local=1500, remote=1200)")
    pending["verification_targets"] = {
        "192.168.96.136": [{"ip": "192.168.20.2", "state": "EXSTART", "interface": "GigabitEthernet1/0"}]}
    pending["session"] = session

    msg = copilot_engine._record_ts_outcome(pending, success=True)   # the "Confirms Fixed" click

    assert "unresolved" in msg.lower()
    assert "still" in msg.lower() or "not yet full" in msg.lower() or "NOT yet FULL" in msg
    assert sc.learning.learn_from_calls[-1].success is False
    assert session.status == ResolutionStatus.UNRESOLVED


def test_record_ts_outcome_success_still_records_normally_when_nothing_contradicts_it(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_NET_STUDIO_MEMORY_DSN", raising=False)
    monkeypatch.delenv("NETBRAIN_MEMORY_DSN", raising=False)
    import core.knowledge.compiler.supply_chain as sc_mod
    sc = _real_supply_chain(tmp_path)
    monkeypatch.setattr(sc_mod, "NetworkIntelligenceSupplyChain", lambda: sc)

    pending = _pending_state(
        ["ip ospf mtu-ignore"],
        root_cause="interface_mtu must equal violated on ospf_adjacency between "
                   "192.168.96.136 and 192.168.20.2 (local=1500, remote=1200)")
    # no verification_targets at all this time -> genuinely resolved
    msg = copilot_engine._record_ts_outcome(pending, success=True)

    assert "unresolved" not in msg.lower()
    assert "resolved" in msg.lower()
    assert sc.learning.learn_from_calls[-1].success is True


def test_record_ts_outcome_tolerates_pending_state_with_no_session(tmp_path, monkeypatch):
    """Older/other pending_state dicts (e.g. built before this change, or in
    a code path that never attached a session) must not raise."""
    monkeypatch.delenv("AI_NET_STUDIO_MEMORY_DSN", raising=False)
    monkeypatch.delenv("NETBRAIN_MEMORY_DSN", raising=False)
    import core.knowledge.compiler.supply_chain as sc_mod
    sc = _real_supply_chain(tmp_path)
    monkeypatch.setattr(sc_mod, "NetworkIntelligenceSupplyChain", lambda: sc)

    pending = _pending_state(["ip ospf mtu-ignore"])  # no "session" key
    msg = copilot_engine._record_ts_outcome(pending, success=True)
    assert "resolved" in msg.lower()


# ── Multi-device fix targeting (real production bug: an MTU mismatch is
# two-sided, but the fix was only ever pushed to one of the two devices) ──
def test_split_by_device_tag_groups_tagged_lines_and_returns_untagged_separately():
    tagged, untagged = copilot_engine._split_by_device_tag([
        "(on 10.0.0.1) interface Gi0/0",
        "(on 10.0.0.1) ip ospf mtu-ignore",
        "(on 10.0.0.2) interface Gi0/1",
        "no tag here",
        "",
    ])
    assert tagged == {
        "10.0.0.1": ["interface Gi0/0", "ip ospf mtu-ignore"],
        "10.0.0.2": ["interface Gi0/1"],
    }
    assert untagged == ["no tag here"]


def test_split_by_device_tag_all_untagged_returns_empty_dict():
    tagged, untagged = copilot_engine._split_by_device_tag(["ip ospf mtu-ignore"])
    assert tagged == {}
    assert untagged == ["ip ospf mtu-ignore"]


def test_apply_ts_fix_two_devices_each_get_only_their_own_commands(monkeypatch):
    """The exact reported bug: a fix naming two devices must push EACH
    device only ITS OWN commands, never the other device's, and never the
    full combined list blasted at both."""
    fake_ie = FakeIntentEngine()
    monkeypatch.setattr(copilot_engine, "_build_intent_engine", lambda call_ai_fn, devices: fake_ie)
    r1, r2 = FakeDevice("192.168.96.136", "R1"), FakeDevice("192.168.20.2", "R2")
    pending = {
        "kind": "ts_fix",
        "root_cause": "interface_mtu must equal violated on ospf_adjacency between "
                      "192.168.96.136 and 192.168.20.2 (local=1500, remote=1200)",
        "fix_commands": [
            "(on 192.168.96.136) interface GigabitEthernet0/0",
            "(on 192.168.96.136) ip ospf mtu-ignore",
            "(on 192.168.20.2) interface GigabitEthernet0/1",
            "(on 192.168.20.2) ip ospf mtu-ignore",
        ],
        "rollback_commands": [
            "(on 192.168.96.136) no ip ospf mtu-ignore",
            "(on 192.168.20.2) no ip ospf mtu-ignore",
        ],
        "verification_commands": ["show ip ospf neighbor"],
        "target_ip": r1.ip, "devices": [r1, r2],
    }
    result = copilot_engine._apply_ts_fix(None, pending)

    assert result["applied_any"] is True
    applied = dict(fake_ie.applied)
    assert applied[r1.ip] == ["interface GigabitEthernet0/0", "ip ospf mtu-ignore"]
    assert applied[r2.ip] == ["interface GigabitEthernet0/1", "ip ospf mtu-ignore"]
    assert any("Applied on R1" in l for l in result["summary_lines"])
    assert any("Applied on R2" in l for l in result["summary_lines"])
    # both devices' verification was actually re-collected, not just one
    collected_ips = {ip for ip, _ in fake_ie.collect_calls}
    assert collected_ips == {r1.ip, r2.ip}


def test_apply_ts_fix_per_device_governance_blocks_one_device_not_the_other(monkeypatch):
    """A policy violation on ONE device's commands must not block the
    other's — each device is governed independently."""
    fake_ie = FakeIntentEngine()
    monkeypatch.setattr(copilot_engine, "_build_intent_engine", lambda call_ai_fn, devices: fake_ie)
    r1, r2 = FakeDevice("192.168.96.136", "R1"), FakeDevice("192.168.20.2", "R2")
    pending = {
        "kind": "ts_fix",
        "root_cause": "interface_mtu must equal violated on ospf_adjacency between "
                      "192.168.96.136 and 192.168.20.2 (local=1500, remote=1200)",
        "fix_commands": [
            "(on 192.168.96.136) no ip address",   # matches CONFIG_DENY_PATTERNS -> blocked
            "(on 192.168.20.2) ip ospf mtu-ignore",
        ],
        "rollback_commands": [],
        "verification_commands": [],
        "target_ip": r1.ip, "devices": [r1, r2],
    }
    result = copilot_engine._apply_ts_fix(None, pending)

    applied = dict(fake_ie.applied)
    assert r1.ip not in applied, "the blocked device must never reach _ssh_apply"
    assert applied[r2.ip] == ["ip ospf mtu-ignore"]
    assert any("Blocked on R1" in l for l in result["summary_lines"])
    assert any("Applied on R2" in l for l in result["summary_lines"])


def test_apply_ts_fix_skips_a_tagged_device_not_selected_this_session(monkeypatch):
    fake_ie = FakeIntentEngine()
    monkeypatch.setattr(copilot_engine, "_build_intent_engine", lambda call_ai_fn, devices: fake_ie)
    r1 = FakeDevice("192.168.96.136", "R1")   # only R1 selected -- not R2
    pending = {
        "kind": "ts_fix",
        "root_cause": "interface_mtu must equal violated on ospf_adjacency between "
                      "192.168.96.136 and 192.168.20.2 (local=1500, remote=1200)",
        "fix_commands": [
            "(on 192.168.96.136) ip ospf mtu-ignore",
            "(on 192.168.20.2) ip ospf mtu-ignore",
        ],
        "rollback_commands": [],
        "verification_commands": [],
        "target_ip": r1.ip, "devices": [r1],
    }
    result = copilot_engine._apply_ts_fix(None, pending)

    applied = dict(fake_ie.applied)
    assert applied == {r1.ip: ["ip ospf mtu-ignore"]}
    assert any("skipped" in l.lower() and "192.168.20.2" in l for l in result["summary_lines"])


def test_apply_ts_fix_single_device_untagged_behavior_is_unchanged(monkeypatch):
    """No tags anywhere (the overwhelming majority case) must produce
    exactly today's single-device behavior -- this is the regression check
    for the common case."""
    fake_ie = FakeIntentEngine()
    monkeypatch.setattr(copilot_engine, "_build_intent_engine", lambda call_ai_fn, devices: fake_ie)
    pending = _pending_state(["ip ospf mtu-ignore"], verification=["show ip ospf neighbor"])
    result = copilot_engine._apply_ts_fix(None, pending)
    assert fake_ie.applied == [("10.0.0.1", ["ip ospf mtu-ignore"])]
    assert result["applied_any"] is True
