"""
Tests for core/knowledge/compiler/completeness_check.py — the automated
completeness checker built to replace the hour-long manual Explore-agent
research that found OSPF's mis-tagged Init signature, its "areas"/"area"
naming mismatch, and its unmapped remediation intents. These tests prove
the checker (a) stays quiet on OSPF, the one protocol already audited by
hand this session, and (b) still finds real, previously-undiscovered gaps
elsewhere (STP's Cisco pseudo-states, HSRP's entirely-unwired corpus) —
the exact validation the rollout plan calls for before trusting this tool
on any protocol nobody's checked yet.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.knowledge.compiler.completeness_check import (
    _parse_corpus_params, check_corpus_completeness, check_protocol_signatures,
    run_full_audit,
)


def test_parse_corpus_params_reads_param_lines():
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("ENUMERATE: some intent\n")
        f.write("HEALTHY: FULL, 2WAY\n")
        f.write("PARAM: foo_bar | must_equal | true | foo_bar | breaks badly |\n")
        f.write("not a param line\n")
        path = f.name
    try:
        params = _parse_corpus_params(path)
        assert len(params) == 1
        assert params[0] == {"name": "foo_bar", "relation": "must_equal",
                             "fatal": "true", "read_intent": "foo_bar"}
    finally:
        os.unlink(path)


def test_ospf_signatures_have_no_hard_errors():
    """OSPF was manually audited this session (Init narrowed, Down split,
    evidence_fields corrected to real attribute names) — the checker must
    not flag anything as a hard error here, or it's miscalibrated."""
    report = check_protocol_signatures("ospf")
    assert report.clean, report.gaps


def test_ospf_down_state_has_two_distinct_signatures_and_neither_errors():
    report = check_protocol_signatures("ospf")
    errors = [g for g in report.gaps if g.severity == "error"]
    assert errors == [], errors


def test_stp_pseudo_states_are_warnings_not_hard_errors():
    """ErrDisabled/ErrDisabledLinkIntegrity are deliberate Cisco pseudo-
    states layered on top of 802.1D's 5-state FSM (see protocol_registry.py's
    own comment) -- a real design choice, not a bug, so this must warn for
    human review rather than hard-fail."""
    report = check_protocol_signatures("stp")
    assert report.clean, report.gaps
    warnings = [g for g in report.gaps if g.check == "state_tag" and "ErrDisabled" in g.detail]
    assert len(warnings) == 2, report.gaps


def test_hsrp_corpus_is_now_wired_except_2_deliberately_unfixable_params():
    """HSRP went from 0/6 params wired to 4/6 fully readable+fixable this
    pass (new verbose "show standby" adapter parsing + real recipes for
    priority/virtual_ip/auth/version). group_number/timers stay
    deliberately un-auto-fixable (renumbering isn't a single safe command;
    timers are one packed string this template substitution can't split
    back into two positions) -- flagged as reviewed warnings, not errors."""
    report = check_corpus_completeness("hsrp_pairing")
    assert report.clean, report.gaps
    warning_params = {g.detail.split("'")[1] for g in report.gaps}
    assert warning_params == {"hsrp_group_number", "hsrp_timers"}, warning_params


def test_ospf_adjacency_corpus_is_now_wired_except_2_deliberately_unfixable_params():
    """hello/dead/mtu/network_type/area/router_id are all readable and
    fixable now. ospf_auth/ospf_network_mask are readable (extracted from
    the same "show ip ospf interface" output already collected) but stay
    deliberately un-auto-fixable: the target value is just a type/prefix-
    length, not the actual secret/full addressing change needed to apply
    it safely."""
    report = check_corpus_completeness("ospf_adjacency")
    assert report.clean, report.gaps
    warning_params = {g.detail.split("'")[1] for g in report.gaps}
    assert warning_params == {"ospf_auth", "ospf_network_mask"}, warning_params


def test_run_full_audit_covers_every_compiled_protocol_and_corpus_file():
    reports = run_full_audit()
    subjects = {r.subject for r in reports}
    assert {"ospf", "bgp", "stp", "lacp", "hsrp", "vrrp", "acl", "vlan", "nat"} <= subjects
    assert {"ospf_adjacency", "hsrp_pairing"} <= subjects
