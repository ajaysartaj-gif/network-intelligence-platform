"""
Regression for a real production report: the recommended fix was a bare

    ip ospf 1 area 0

with no "interface X" line above it anywhere — the fix applies to whichever
interface config context happens to be active, not necessarily the
interface actually under investigation. Root cause: render_remediation_fix()
silently DROPPED the context line (interface {iface}) whenever {iface}
was empty, but still emitted the bare command_line regardless — so an
interface-scoped intent with no positively-identified interface produced
an ambiguous, unsafe command instead of refusing.

render_remediation_fix() now refuses (returns []) whenever a recipe's own
templates actually reference its context_param and that value was never
resolved — for BOTH Cisco's separate-context-line style and Junos's
inline-substitution style — while leaving genuinely context-free recipes
(BGP's Junos activate/multihop, whose context_param defaults to "iface"
but never uses it) completely unaffected.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.knowledge.compiler.protocol_registry import RemediationRecipe, render_remediation_fix


def test_interface_scoped_cisco_recipe_refuses_without_an_interface():
    spec = RemediationRecipe(intent_name="enable_ospf_on_interface",
                             context_template="interface {iface}",
                             command_template="ip {proto} {process} area {area}",
                             defaults={"process": "1", "area": "0"})
    assert render_remediation_fix(spec, "ospf", {"interface": ""}) == []


def test_interface_scoped_cisco_recipe_renders_both_lines_with_a_real_interface():
    spec = RemediationRecipe(intent_name="enable_ospf_on_interface",
                             context_template="interface {iface}",
                             command_template="ip {proto} {process} area {area}",
                             defaults={"process": "1", "area": "0"})
    out = render_remediation_fix(spec, "ospf", {"interface": "GigabitEthernet0/0"})
    assert out == ["interface GigabitEthernet0/0", "ip ospf 1 area 0"]


def test_junos_style_inline_interface_recipe_refuses_without_an_interface():
    """Junos has no separate context-mode step — {iface} is substituted
    directly into the one command line — so the guard must also catch an
    empty value referenced ONLY in command_template, not just context_template."""
    spec = RemediationRecipe(intent_name="enable_ospf_on_interface",
                             context_template=None,
                             command_template="set protocols ospf area {area} interface {iface}",
                             defaults={"area": "0.0.0.0"})
    assert render_remediation_fix(spec, "ospf", {"interface": ""}) == []


def test_junos_style_inline_interface_recipe_renders_with_a_real_interface():
    spec = RemediationRecipe(intent_name="enable_ospf_on_interface",
                             context_template=None,
                             command_template="set protocols ospf area {area} interface {iface}",
                             defaults={"area": "0.0.0.0"})
    out = render_remediation_fix(spec, "ospf", {"interface": "ge-0/0/0"})
    assert out == ["set protocols ospf area 0.0.0.0 interface ge-0/0/0"]


def test_context_required_false_renders_without_the_context_line_when_unresolved():
    """BGP's real recipes: the command line is already uniquely scoped by
    neighbor_ip alone, so an unresolved local_as is a cosmetic gap the
    recipe explicitly marks safe to skip via context_required=False —
    must NOT be treated the same as OSPF's genuinely ambiguous case."""
    spec = RemediationRecipe(intent_name="remove_bgp_neighbor_shutdown",
                             context_template="router bgp {local_as}", context_param="local_as",
                             command_template="no neighbor {neighbor_ip} shutdown",
                             context_required=False)
    out = render_remediation_fix(spec, "bgp", {"neighbor_ip": "10.0.0.3", "local_as": ""})
    assert out == ["no neighbor 10.0.0.3 shutdown"]


def test_context_required_true_by_default_refuses_when_unresolved():
    """Same shape as the BGP recipe above but WITHOUT context_required=False
    (the dataclass default) must still refuse — proves the safety-critical
    default wasn't accidentally loosened."""
    spec = RemediationRecipe(intent_name="remove_bgp_neighbor_shutdown",
                             context_template="router bgp {local_as}", context_param="local_as",
                             command_template="no neighbor {neighbor_ip} shutdown")
    assert render_remediation_fix(spec, "bgp", {"neighbor_ip": "10.0.0.3", "local_as": ""}) == []


def test_recipe_whose_context_param_is_unused_is_unaffected_by_empty_interface():
    """BGP's Junos recipes default context_param to "iface" (the dataclass
    default) but are genuinely neighbor/group-scoped — {iface} never
    appears in either template. An empty "interface" param must not block
    these; only a param the recipe's OWN templates actually reference
    should ever gate the fix."""
    spec = RemediationRecipe(intent_name="remove_bgp_neighbor_shutdown",
                             context_template=None,
                             command_template="activate protocols bgp group {group} neighbor {neighbor_ip}",
                             defaults={"group": "external"})
    out = render_remediation_fix(spec, "bgp", {"interface": "", "neighbor_ip": "10.0.0.2"})
    assert out == ["activate protocols bgp group external neighbor 10.0.0.2"]


def test_neighbor_scoped_recipe_refuses_without_a_neighbor_ip():
    spec = RemediationRecipe(intent_name="set_lacp_mode_active",
                             context_template="interface {neighbor_ip}",
                             command_template="channel-group {channel_group} mode active",
                             context_param="neighbor_ip",
                             defaults={"channel_group": "1"})
    assert render_remediation_fix(spec, "lacp", {"neighbor_ip": ""}) == []


def test_errdisable_recipe_refuses_without_a_cause():
    spec = RemediationRecipe(intent_name="enable_errdisable_recovery",
                             context_template=None, context_param="errdisable_reason",
                             command_template="errdisable recovery cause {errdisable_reason}")
    assert render_remediation_fix(spec, "stp", {"errdisable_reason": ""}) == []
    out = render_remediation_fix(spec, "stp", {"errdisable_reason": "udld"})
    assert out == ["errdisable recovery cause udld"]
