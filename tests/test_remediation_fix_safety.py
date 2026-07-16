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

from core.knowledge.compiler.protocol_registry import (
    CISCO_ADAPTER_SPECS, RemediationRecipe, render_remediation_fix,
)


# ── the REAL configured recipes (not hand-built test doubles) — proves the
# safety guard actually covers every protocol's live remediation config,
# not just a plausible-looking synthetic RemediationRecipe ─────────────────
def _real_recipe(protocol: str, intent_name: str) -> RemediationRecipe:
    spec = CISCO_ADAPTER_SPECS[protocol]
    return next(r for r in spec.recipes if r.intent_name == intent_name)


def test_real_lacp_recipe_refuses_without_a_neighbor_ip():
    recipe = _real_recipe("lacp", "set_lacp_mode_active")
    assert render_remediation_fix(recipe, "lacp", {"neighbor_ip": ""}) == []


def test_real_lacp_recipe_renders_with_a_real_neighbor_ip():
    recipe = _real_recipe("lacp", "set_lacp_mode_active")
    out = render_remediation_fix(recipe, "lacp", {"neighbor_ip": "Gi0/1"})
    assert out == ["interface Gi0/1", "channel-group 1 mode active"]


def test_real_hsrp_recipe_refuses_without_an_fhrp_interface():
    recipe = _real_recipe("hsrp", "add_hsrp_preempt")
    # HSRP/VRRP encode "iface:group" as neighbor_ip; an empty value means
    # the interface half was never resolved either.
    assert render_remediation_fix(recipe, "hsrp", {"neighbor_ip": ""}) == []


def test_real_hsrp_recipe_renders_with_a_real_interface_and_group():
    recipe = _real_recipe("hsrp", "add_hsrp_preempt")
    out = render_remediation_fix(recipe, "hsrp", {"neighbor_ip": "Gi0/0:10"})
    assert out == ["interface Gi0/0", "standby 10 preempt"]


def test_real_vrrp_recipe_refuses_without_an_fhrp_interface():
    recipe = _real_recipe("vrrp", "enable_vrrp_preempt")
    assert render_remediation_fix(recipe, "vrrp", {"neighbor_ip": ""}) == []


def test_real_vrrp_recipe_renders_with_a_real_interface_and_group():
    recipe = _real_recipe("vrrp", "enable_vrrp_preempt")
    out = render_remediation_fix(recipe, "vrrp", {"neighbor_ip": "Gi0/2:5"})
    assert out == ["interface Gi0/2", "vrrp 5 preempt"]


def test_real_stp_recipe_refuses_without_an_errdisable_cause():
    recipe = _real_recipe("stp", "enable_errdisable_recovery")
    assert render_remediation_fix(recipe, "stp", {"errdisable_reason": ""}) == []


def test_real_stp_recipe_renders_with_a_real_cause():
    recipe = _real_recipe("stp", "enable_errdisable_recovery")
    out = render_remediation_fix(recipe, "stp", {"errdisable_reason": "udld"})
    assert out == ["errdisable recovery cause udld"]


def test_real_ospf_recipes_all_refuse_without_an_interface():
    for intent_name in ("ignore_protocol_mtu", "set_protocol_network_point_to_point",
                        "configure_ospf_interface", "enable_ospf_on_interface"):
        recipe = _real_recipe("ospf", intent_name)
        assert render_remediation_fix(recipe, "ospf", {"interface": ""}) == [], intent_name


def test_real_bgp_recipes_render_without_local_as_known():
    """The one intentional exception across the whole registry: BGP's
    command lines are already uniquely scoped by neighbor_ip, so an
    unresolved local_as is safe to render without."""
    shutdown = _real_recipe("bgp", "remove_bgp_neighbor_shutdown")
    assert render_remediation_fix(shutdown, "bgp", {"neighbor_ip": "10.0.0.2"}) == \
        ["no neighbor 10.0.0.2 shutdown"]
    multihop = _real_recipe("bgp", "add_bgp_ebgp_multihop")
    assert render_remediation_fix(multihop, "bgp", {"neighbor_ip": "10.0.0.2"}) == \
        ["neighbor 10.0.0.2 ebgp-multihop 2"]


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
