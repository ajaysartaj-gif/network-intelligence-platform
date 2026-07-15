"""Tests for the AI Configuration Engine (no network, no real LLM)."""
import json
import os
import re
import sys
import types
from pathlib import Path

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config_engine import AIConfigurationEngine, ConfigStatus
from core.config_engine.audit import JSONFileBackend, SessionStore
from core.vendor import VendorGateway, RemediationIntent


class Dev:
    def __init__(self, ip, dt="cisco_ios"):
        self.ip, self.hostname, self.device_type = ip, "R", dt


def make_ai(missing=False):
    def ai(p):
        if "single high-level category" in p:
            return json.dumps({"objective": "Enable OSPF on core uplinks in area 0",
                               "category": "routing"})
        if "NORMALIZED configuration intent" in p:
            return json.dumps({"technologies": ["ospf"], "protocols": ["ospf"], "services": [],
                               "scope": [], "intents": [
                                   {"name": "configure_ospf_interface",
                                    "params": {"protocol": "ospf", "area": "0", "interface": "Gi0/0"},
                                    "rationale": "bring uplink into OSPF area 0"}]})
        if "MANDATORY inputs" in p:
            if missing:
                return json.dumps([{"field": "area", "question": "Which OSPF area?", "required": True}])
            return json.dumps([])
        if "Recommend suitable technologies" in p:
            return json.dumps([{"name": "OSPF", "rationale": "fits IGP need",
                               "tradeoffs": "flooding scope", "recommended": True}])
        if "configuration dependencies" in p:
            return json.dumps([{"kind": "interface", "detail": "Gi0/0 must be up"}])
        if "architectural flaws" in p:
            return json.dumps([{"name": "area_design", "severity": "info", "passed": True,
                               "detail": "area 0 valid"}])
        if "implementation workflow" in p:
            return json.dumps([{"order": 1, "description": "enable ospf on interface",
                               "prerequisite": "interface up"}])
        if "operational impact" in p:
            return json.dumps({"factors": ["protocol_reset"], "downtime_expected": False,
                               "summary": "OSPF adjacency will form on the uplink"})
        if "risk drivers" in p:
            return json.dumps({"mitigations": ["schedule in change window"]})
        if "best practices" in p:
            return json.dumps({"best_practices": ["use point-to-point on p2p links"]})
        if "executive summary" in p:
            return "Enables OSPF on the core uplink in area 0; low risk, no downtime expected."
        return ""
    return ai


def _gw():
    return VendorGateway(send=lambda d, c: {x: "" for x in c},
                         hint_provider=lambda d: {"device_type": d.device_type})


def test_needs_input_when_required_missing():
    eng = AIConfigurationEngine(ai_call=make_ai(missing=True), devices=[Dev("10.0.0.1")], gateway=_gw())
    rep = eng.run("set up OSPF")
    assert rep.session.status == ConfigStatus.NEEDS_INPUT
    assert any(m.field == "area" for m in rep.session.missing)   # asks, never assumes
    print("[1] requirement gating (ask, never assume): PASS")


def test_full_pipeline_produces_vendor_artifacts_and_approval():
    eng = AIConfigurationEngine(ai_call=make_ai(), devices=[Dev("10.0.0.1")], gateway=_gw())
    rep = eng.run("enable OSPF on core uplink in area 0", provided={"area": "0"})
    s = rep.session
    assert s.status == ConfigStatus.NEEDS_APPROVAL, s.status
    # normalized intent exists and is vendor-neutral
    assert s.intents and s.intents[0].name == "configure_ospf_interface"
    # vendor syntax came from the ADAPTER via the gateway, not the engine
    art = [a for a in s.artifacts if a.supported]
    assert art and any("ospf" in c for c in art[0].config_commands)
    assert art[0].rollback_commands                              # rollback mandatory
    # approval package present; nothing deployed
    assert s.approval and not s.approval.approved
    assert s.risk is not None and s.deployment is not None
    print("[2] full pipeline → vendor artifacts + approval (no deploy): PASS")


def test_engine_core_has_no_vendor_names():
    tokens = ["cisco", "juniper", "arista", "junos", "ios-xe", "nokia", "huawei"]
    files = list((ROOT / "core" / "config_engine").glob("*.py"))
    bad = []
    for f in files:
        low = f.read_text(encoding="utf-8", errors="ignore").lower()
        for t in tokens:
            if t in low:
                bad.append(f"{f.name}:{t}")
    assert not bad, f"vendor tokens leaked into config engine: {bad}"
    print("[3] zero vendor names in config engine core: PASS")


def test_approval_flip_no_deploy():
    eng = AIConfigurationEngine(ai_call=make_ai(), devices=[Dev("10.0.0.1")], gateway=_gw())
    rep = eng.run("enable OSPF", provided={"area": "0"})
    eng.approve(rep.session)
    assert rep.session.status == ConfigStatus.APPROVED and rep.session.approval.approved
    print("[4] explicit approval recorded, still no deploy: PASS")


def make_ai_with_optional_missing():
    """Same as make_ai(), but 'find_missing' also returns one NON-required
    (optional) field — required missing fields always halt the pipeline
    earlier (NEEDS_INPUT), so this is the only kind that can ever reach the
    risk scorer's unresolved_missing parameter."""
    base = make_ai()

    def ai(p):
        if "MANDATORY inputs" in p:
            return json.dumps([{"field": "description", "question": "Optional: interface description?",
                               "required": False}])
        return base(p)
    return ai


def test_unresolved_optional_missing_inputs_increase_risk_score():
    """Regression test: RiskScorer.score()'s unresolved_missing parameter has
    real logic (+0.25, a driver) but engine.py used to hardcode 0 always, so
    it could never fire even when s.missing genuinely had optional unresolved
    fields on record. Must now reflect the real count and not block the
    pipeline (only REQUIRED missing fields gate to NEEDS_INPUT)."""
    baseline = AIConfigurationEngine(ai_call=make_ai(), devices=[Dev("10.0.0.1")], gateway=_gw())
    base_rep = baseline.run("enable OSPF on core uplink in area 0", provided={"area": "0"})

    eng = AIConfigurationEngine(ai_call=make_ai_with_optional_missing(), devices=[Dev("10.0.0.1")], gateway=_gw())
    rep = eng.run("enable OSPF on core uplink in area 0", provided={"area": "0"})
    s = rep.session

    assert s.status == ConfigStatus.NEEDS_APPROVAL, s.status   # optional missing never blocks
    assert any(m.field == "description" and not m.required for m in s.missing)
    assert any("unresolved optional inputs" in d for d in s.risk.drivers)
    assert s.risk.score > base_rep.session.risk.score
    print("[5] unresolved optional inputs genuinely raise risk score: PASS")


def test_session_store_persists_across_fresh_instances_via_json_file_backend(tmp_path):
    """Regression test for the dead-audit-trail bug: a fresh SessionStore()
    (no backend passed, mirroring copilot_engine.py's per-request
    instantiation) must persist via the default JSON-file backend."""
    path = str(tmp_path / "cfg_sessions.json")
    eng = AIConfigurationEngine(ai_call=make_ai(), devices=[Dev("10.0.0.1")], gateway=_gw(),
                                session_store=JSONFileBackend(path=path))
    rep = eng.run("enable OSPF on core uplink in area 0", provided={"area": "0"})
    session_id = rep.session.id

    fresh_store = SessionStore(JSONFileBackend(path=path))
    loaded = fresh_store.load(session_id)
    assert loaded is not None
    assert loaded["id"] == session_id
    assert loaded["status"] == "needs_approval"
    print("[6] session store persists across fresh instances via JSON file: PASS")


def test_default_session_store_backend_is_safe_in_memory_not_json_file():
    """SessionStore() with no backend argument must stay side-effect-free by
    default — persistence is opt-in via an explicitly passed JSONFileBackend,
    wired once in copilot_engine.py, not a silent default every test/caller
    would otherwise trigger."""
    store = SessionStore()
    assert not isinstance(store._backend, JSONFileBackend)
    assert not os.path.exists(".netbrain_config_sessions.json")
    print("[7] default SessionStore backend stays in-memory, no file side effect: PASS")


if __name__ == "__main__":
    test_needs_input_when_required_missing()
    test_full_pipeline_produces_vendor_artifacts_and_approval()
    test_engine_core_has_no_vendor_names()
    test_approval_flip_no_deploy()
    test_unresolved_optional_missing_inputs_increase_risk_score()
    test_default_session_store_backend_is_safe_in_memory_not_json_file()
    print("\nALL CONFIG-ENGINE TESTS PASSED")
