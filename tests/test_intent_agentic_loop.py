"""Tests for core/intent_engine.py's IntentEngine._detect_scenario()."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.intent_engine import IntentEngine


def _engine():
    return IntentEngine(ai_call=lambda p: "", approved_devices=[])


def test_detect_scenario_is_case_insensitive():
    """Regression: _detect_scenario did a case-SENSITIVE substring check
    ("ospf" in q), so a query written the conventional way people actually
    write protocol acronyms -- "why is OSPF stuck" -- silently fell through
    to "general" instead of "ospf". _classify() (the original caller)
    happened to lowercase before calling this, masking the bug there, but
    core.troubleshooting.engine.TroubleshootingEngine._detect_protocol()
    calls _detect_scenario() directly with the RAW query, so every
    compiled-signature feature silently stopped working whenever a query
    capitalized the protocol name."""
    ie = _engine()
    assert ie._detect_scenario("why is OSPF stuck") == "ospf"
    assert ie._detect_scenario("why is ospf stuck") == "ospf"
    assert ie._detect_scenario("BGP neighbor down") == "bgp"
    assert ie._detect_scenario("ACL blocking traffic") == "acl"
    assert ie._detect_scenario("something unrelated") == "general"
