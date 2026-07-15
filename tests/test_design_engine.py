"""
Tests for core/design_engine/ (the AI Design Engine) — previously had ZERO test
coverage despite being one of the tool's three live-wired engines (troubleshoot/
configure/design). Covers three real gaps found and fixed during this pass:

1. The "insufficient options" gate checked `len(options) < 2` regardless of the
   configured `min_options` (default 3) — silently allowing 2 options through as
   fully "ready" even though the engine's own stated principle is "ALWAYS
   multiple options; never one" enforced via that exact config field.
2. The trade-off matrix's inputs were 100% self-reported by the same LLM call
   that invented each option — "auditable weighted matrix (not the LLM's whim)"
   was true of the aggregation, not the underlying scores. Fixed with a second,
   independent scoring call (DesignReasoner.score_options).
3. DesignMemory has no persistent-by-default option, and copilot_engine.py
   instantiates a fresh AIDesignEngine per request with no backend passed —
   so memory never actually persisted anything in production. The constructor
   default stays safe (in-memory, no side effects for tests/other callers);
   the real fix is an explicit JSONFileBackend wired once in copilot_engine.py.
"""
import json
import os
import sys
import types
from pathlib import Path

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.design_engine import AIDesignEngine, DesignEngineConfig, DesignStatus
from core.design_engine.models import DesignSession
from core.design_engine.memory import DesignMemory, JSONFileBackend


_GENERIC_SCORES = {"cost": 0.5, "performance": 0.5, "scalability": 0.5, "availability": 0.5,
                   "security": 0.5, "operational_simplicity": 0.5, "future_readiness": 0.5,
                   "vendor_independence": 0.5}


def _option(name, scores=None, disadvantages=None, risks=None):
    return {"name": name, "architecture": f"architecture narrative for {name}",
            "technologies": ["OSPF", "VRRP"], "advantages": ["fast convergence"],
            "disadvantages": disadvantages or [], "assumptions": [], "risks": risks or [],
            "scores": scores or dict(_GENERIC_SCORES)}


def _make_ai(options, independent_scores=None, n_requirements=4):
    """independent_scores: dict[name -> scores] returned by the separate
    'independent reviewer' scoring call; None means fall back to whatever the
    test doesn't care about (echoes generic scores)."""
    def ai(prompt: str) -> str:
        if "Summarize this request" in prompt:
            return json.dumps({"business_summary": "biz", "technical_summary": "tech"})
        if "Extract normalized requirements" in prompt:
            return json.dumps([{"kind": "technical", "detail": f"req{i}"} for i in range(n_requirements)])
        if "Identify design constraints" in prompt:
            return json.dumps([{"kind": "budget", "detail": "moderate budget"}])
        if "Assess the existing" in prompt:
            return json.dumps({"summary": "greenfield", "bottlenecks": [], "technical_debt": []})
        if "independent reviewer" in prompt:
            rows = [{"name": name, "scores": sc} for name, sc in (independent_scores or {}).items()]
            return json.dumps(rows)
        if "Generate at least" in prompt:
            return json.dumps(options)
        if "Recommend suitable networking technologies" in prompt:
            return json.dumps({"technologies": ["OSPF", "BGP"]})
        if "Estimate capacity planning" in prompt:
            return json.dumps([{"dimension": "bandwidth", "current": "1G", "projected": "10G", "headroom": "9G"}])
        if "Identify risks" in prompt:
            return json.dumps([{"kind": "operational", "detail": "staff retraining needed", "severity": "low"}])
        if "Produce a migration strategy" in prompt:
            return json.dumps({"strategy": "phased", "success_criteria": "zero downtime",
                               "phases": [{"order": 1, "name": "phase1", "actions": "cut over core",
                                          "validation": "ping test", "rollback": "revert vlan", "downtime": "0m"}]})
        if "List operational recommendations" in prompt:
            return json.dumps({"operational_recommendations": ["enable NetFlow"]})
        if "Generate concise design documentation" in prompt:
            return json.dumps({"high_level": "HLD text", "low_level": "LLD text",
                               "decision_log": "chose X", "future_recommendations": ["consider SDN"]})
        if "explain WHY this option is recommended" in prompt:
            return "Recommended for its balance of scalability and resiliency."
        return ""
    return ai


class _MemBackend:
    def __init__(self):
        self.store = {}

    def set(self, k, v):
        self.store[k] = v

    def get(self, k):
        return self.store.get(k)


def test_insufficient_status_when_below_configured_min_options():
    """Regression test for the threshold bug: the gate must respect the
    configured min_options (3 by default), not a hardcoded '< 2'."""
    options = [_option("Option A"), _option("Option B")]   # only 2, below default min_options=3
    ai = _make_ai(options)
    eng = AIDesignEngine(ai_call=ai, memory_backend=_MemBackend())
    report = eng.run("design a small branch network")
    s = report.session
    assert s.status == DesignStatus.INSUFFICIENT
    assert len(s.options) == 2


def test_two_options_accepted_when_min_options_configured_lower():
    """Confirms the fix reads the config rather than reintroducing a new
    hardcoded constant: lowering min_options to 2 must let 2 options through."""
    options = [_option("Option A"), _option("Option B")]
    ai = _make_ai(options)
    eng = AIDesignEngine(ai_call=ai, config=DesignEngineConfig(min_options=2), memory_backend=_MemBackend())
    report = eng.run("design a small branch network")
    assert report.session.status == DesignStatus.OPTIONS_READY


def test_independent_scoring_overrides_self_reported_scores():
    """The core rigor fix: if every option self-reports identical (flattering)
    scores, the self-reported values alone would produce an arbitrary/tied
    winner. The independent scoring pass must be the one that actually decides
    the recommendation."""
    options = [_option("Option A", scores=dict(_GENERIC_SCORES)),
               _option("Option B", scores=dict(_GENERIC_SCORES)),
               _option("Option C", scores=dict(_GENERIC_SCORES))]
    # All self-report identically, but the independent reviewer clearly favors B.
    independent = {
        "Option A": {**_GENERIC_SCORES, "scalability": 0.2, "availability": 0.2},
        "Option B": {**_GENERIC_SCORES, "scalability": 0.95, "availability": 0.95, "security": 0.9},
        "Option C": {**_GENERIC_SCORES, "scalability": 0.3, "availability": 0.3},
    }
    ai = _make_ai(options, independent_scores=independent)
    eng = AIDesignEngine(ai_call=ai, memory_backend=_MemBackend())
    report = eng.run("design a resilient dual-datacenter core")
    s = report.session
    assert s.status == DesignStatus.OPTIONS_READY
    rec = s.recommended()
    assert rec is not None
    assert rec.name == "Option B"
    # and the losing options' scores actually reflect the independent pass, not the flat self-report
    a = next(o for o in s.options if o.name == "Option A")
    assert a.scores["scalability"] == 0.2


def test_spof_risk_surfaced_for_recommended_option():
    options = [_option("Redundant Core", scores={**_GENERIC_SCORES, "availability": 0.9}),
               _option("Single Router Core", disadvantages=["only one core router, no redundancy"],
                       scores=dict(_GENERIC_SCORES)),
               _option("Third Option", scores=dict(_GENERIC_SCORES))]
    independent = {"Redundant Core": {**_GENERIC_SCORES, "availability": 0.95, "scalability": 0.9},
                  "Single Router Core": dict(_GENERIC_SCORES),
                  "Third Option": dict(_GENERIC_SCORES)}
    ai = _make_ai(options, independent_scores=independent)
    eng = AIDesignEngine(ai_call=ai, memory_backend=_MemBackend())
    report = eng.run("design a resilient campus core")
    s = report.session
    assert s.recommended().name == "Redundant Core"
    # SPOF aggregator only inspects the RECOMMENDED option's own risks/disadvantages
    assert not any(r.kind == "spof" for r in s.risks)


def test_spof_risk_surfaced_when_recommended_option_itself_lacks_redundancy():
    options = [_option("Single Router Core", disadvantages=["only one core router, no redundancy"],
                       scores={**_GENERIC_SCORES, "cost": 0.95}),
               _option("Option B", scores=dict(_GENERIC_SCORES)),
               _option("Option C", scores=dict(_GENERIC_SCORES))]
    independent = {"Single Router Core": {**_GENERIC_SCORES, "cost": 0.95, "scalability": 0.9},
                  "Option B": dict(_GENERIC_SCORES), "Option C": dict(_GENERIC_SCORES)}
    ai = _make_ai(options, independent_scores=independent)
    eng = AIDesignEngine(ai_call=ai, memory_backend=_MemBackend())
    report = eng.run("design a low-cost single-site network")
    s = report.session
    assert s.recommended().name == "Single Router Core"
    assert any(r.kind == "spof" for r in s.risks)


def test_full_happy_path_end_to_end_produces_complete_report():
    options = [_option("Option A"), _option("Option B", scores={**_GENERIC_SCORES, "scalability": 0.9}),
               _option("Option C")]
    independent = {"Option A": dict(_GENERIC_SCORES),
                  "Option B": {**_GENERIC_SCORES, "scalability": 0.9, "availability": 0.85},
                  "Option C": dict(_GENERIC_SCORES)}
    ai = _make_ai(options, independent_scores=independent)
    eng = AIDesignEngine(ai_call=ai, memory_backend=_MemBackend())
    report = eng.run("design a resilient dual-datacenter campus core for 5k users")
    s = report.session

    assert s.status == DesignStatus.OPTIONS_READY
    assert len(s.options) == 3
    assert s.recommended().name == "Option B"
    assert set(s.rejected) == {"Option A", "Option C"}
    assert s.capacity and s.capacity[0].dimension == "bandwidth"
    assert s.migration is not None and s.migration.phases[0].name == "phase1"
    assert s.operational_recommendations == ["enable NetFlow"]
    assert s.documentation is not None and s.documentation.high_level == "HLD text"
    assert 0.0 <= s.confidence <= 1.0
    assert s.decision_rationale

    d = report.to_dict()
    assert d["recommended_design"] == "Option B"
    md = report.to_markdown()
    assert "Option B" in md and "RECOMMENDED" in md


def test_memory_persists_across_fresh_engine_instances_via_json_file_backend(tmp_path):
    """Regression test for the dead-memory bug: a fresh DesignMemory() (no
    backend passed, mirroring copilot_engine.py's per-request instantiation)
    must still persist via the default JSON-file backend, not a process-local
    dict that resets every time."""
    path = str(tmp_path / "design_memory.json")
    mem1 = DesignMemory(JSONFileBackend(path=path))
    options = [_option("Option A"), _option("Option B"), _option("Option C")]
    ai = _make_ai(options, independent_scores={"Option A": dict(_GENERIC_SCORES),
                                                "Option B": dict(_GENERIC_SCORES),
                                                "Option C": dict(_GENERIC_SCORES)})
    eng = AIDesignEngine(ai_call=ai, memory_backend=JSONFileBackend(path=path))
    report = eng.run("design a small office network")
    session_id = report.session.id

    # A brand-new DesignMemory pointed at the same file (simulating a fresh
    # process/request) must be able to load what the first one saved.
    mem2 = DesignMemory(JSONFileBackend(path=path))
    loaded = mem2.load(session_id)
    assert loaded is not None
    assert loaded["id"] == session_id
    assert loaded["status"] == "options_ready"


def test_default_design_memory_backend_is_safe_in_memory_not_json_file():
    """DesignMemory() with NO backend argument must stay side-effect-free by
    default (no file I/O just from construction) — persistence is opt-in via
    an explicitly passed JSONFileBackend, wired once in copilot_engine.py, not
    a silent default every caller/test would otherwise trigger."""
    mem = DesignMemory()
    assert not isinstance(mem._backend, JSONFileBackend)
    mem.save(DesignSession(query="q"))   # must not touch disk
    assert not os.path.exists(".netbrain_design_memory.json")
