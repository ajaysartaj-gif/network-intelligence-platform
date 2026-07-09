"""
Tests for the Network Knowledge Compiler's Semantic Compiler
(core/knowledge/compiler/): lexer, AST builder, semantic analyzer,
canonicalizer, relationship compiler, validation engine, and the
SemanticCompiler orchestrator/publisher.

No network, no LLM, no real embedding model — this package is deterministic
by design, so these tests just exercise it directly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.knowledge.compiler.ast_builder import build_ast
from core.knowledge.compiler.canonicalizer import finding_to_object
from core.knowledge.compiler.compiler import SemanticCompiler
from core.knowledge.compiler.relationships import derive_relationships
from core.knowledge.compiler.semantic_analyzer import (
    analyze, analyze_structured, SemanticFinding,
)
from core.knowledge.compiler.tokens import TokenType, tokenize_line
from core.knowledge.compiler.validation import validate_objects, validate_relationships
from core.knowledge_graph import KnowledgeGraph, RelationType
from core.vendor.models import ObjectType


SAMPLE_CONFIG = """\
hostname R1
!
vrf definition CUSTOMER_A
 rd 65000:1
 route-target export 65000:1
 route-target import 65000:1
!
vlan 10
 name USERS
!
interface GigabitEthernet0/1
 description Uplink to R2
 ip vrf forwarding CUSTOMER_A
 ip address 10.0.0.1 255.255.255.0
 mtu 1500
 ip access-group ACL_IN in
 service-policy output QOS_OUT
 no shutdown
!
interface Vlan10
 switchport access vlan 10
 no shutdown
!
ip access-list extended ACL_IN
 permit tcp any any eq 80
 deny ip any any
!
class-map match-any VOICE
!
policy-map QOS_OUT
 class VOICE
!
ip nat pool POOL1 192.168.1.1 192.168.1.100
ip nat inside source list ACL_IN pool POOL1
!
router ospf 1
 network 10.0.0.0 0.0.0.255 area 0
!
"""

SAMPLE_NEIGHBOR_SHOW = (
    "Neighbor ID     Pri   State           Dead Time   Address         Interface\n"
    "10.0.0.2          1   FULL/DR         00:00:39    10.0.0.2        GigabitEthernet0/1\n"
)

SAMPLE_ERROR_LINE = "%OSPF-5-ADJCHG: Process 1, Nbr 10.0.0.2 on GigabitEthernet0/1 changed state\n"


# ── Lexer / tokenizer ─────────────────────────────────────────────────────

def test_tokenize_line_recognizes_categories():
    tokens = tokenize_line("interface GigabitEthernet0/1", 1)
    types = [t.type for t in tokens]
    assert types[0] == TokenType.COMMAND
    assert TokenType.INTERFACE_NAME in types


def test_tokenize_line_ip_and_mask():
    tokens = tokenize_line(" ip address 10.0.0.1 255.255.255.0", 2)
    values_by_type = {t.type: t.value for t in tokens}
    assert values_by_type[TokenType.IPV4] == "10.0.0.1"
    assert values_by_type[TokenType.MASK] == "255.255.255.0"


def test_tokenize_line_error_word():
    tokens = tokenize_line(SAMPLE_ERROR_LINE.strip(), 1)
    assert any(t.type == TokenType.ERROR_WORD and t.value == "%OSPF-5-ADJCHG" for t in tokens)


def test_tokenize_line_comment():
    tokens = tokenize_line("!", 1)
    assert tokens and tokens[0].type == TokenType.COMMENT


# ── AST builder ───────────────────────────────────────────────────────────

def test_build_ast_nests_interface_children():
    root = build_ast(SAMPLE_CONFIG)
    iface_nodes = [n for n in root.walk() if n.value.startswith("interface GigabitEthernet0/1")]
    assert len(iface_nodes) == 1
    iface = iface_nodes[0]
    child_values = [c.value for c in iface.children]
    assert any(v.startswith("ip address") for v in child_values)
    assert any(v.startswith("mtu") for v in child_values)


def test_build_ast_preserves_line_numbers():
    root = build_ast(SAMPLE_CONFIG)
    hostname_nodes = [n for n in root.walk() if n.value.startswith("hostname")]
    assert hostname_nodes[0].line == 1


def test_build_ast_bang_resets_nesting():
    root = build_ast(SAMPLE_CONFIG)
    # vlan 10's "name USERS" must nest under "vlan 10", not leak into the
    # next stanza after the "!" — if bang-reset didn't work, "name USERS"
    # would end up mis-parented.
    vlan_node = next(n for n in root.walk() if n.value == "vlan 10")
    assert any(c.value == "name USERS" for c in vlan_node.children)
    # top-level siblings (direct children of root) after the reset
    top_level_values = [c.value for c in root.children]
    assert "vlan 10" in top_level_values
    assert "hostname R1" in top_level_values


# ── Semantic analyzer: one test per extractor family ─────────────────────

def test_interface_extractor():
    root = build_ast(SAMPLE_CONFIG)
    findings = [f for f in analyze(root) if f.kind == "interface"]
    by_name = {f.attributes["name"]: f for f in findings}
    gi = by_name["GigabitEthernet0/1"]
    assert gi.attributes["ip"] == "10.0.0.1"
    assert gi.attributes["mask"] == "255.255.255.0"
    assert gi.attributes["mtu"] == 1500
    assert gi.attributes["vrf"] == "CUSTOMER_A"
    assert gi.attributes["acl_ref"] == "ACL_IN"
    assert gi.attributes["qos_policy"] == "QOS_OUT"
    assert gi.attributes["admin_state"] == "up"

    vlan_iface = by_name["Vlan10"]
    assert vlan_iface.attributes["vlan"] == 10


def test_protocol_extractor_stanza_and_neighbor():
    root = build_ast(SAMPLE_CONFIG)
    findings = analyze(root)
    protos = [f for f in findings if f.kind == "protocol"]
    assert protos and protos[0].attributes["protocol"] == "ospf"
    assert "10.0.0.0" in protos[0].attributes["networks"]
    assert "0" in protos[0].attributes["areas"]

    nbr_root = build_ast(SAMPLE_NEIGHBOR_SHOW)
    nbr_findings = [f for f in analyze(nbr_root) if f.kind == "neighbor"]
    assert any(f.attributes["neighbor_ip"] == "10.0.0.2" and f.attributes["state"] == "FULL"
              for f in nbr_findings)


def test_acl_extractor():
    root = build_ast(SAMPLE_CONFIG)
    rules = [f for f in analyze(root) if f.kind == "acl_rule"]
    assert len(rules) == 2
    assert {r.attributes["action"] for r in rules} == {"permit", "deny"}
    assert all(r.attributes["acl_name"] == "ACL_IN" for r in rules)


def test_vrf_extractor():
    root = build_ast(SAMPLE_CONFIG)
    vrfs = [f for f in analyze(root) if f.kind == "vrf"]
    assert len(vrfs) == 1
    assert vrfs[0].attributes["name"] == "CUSTOMER_A"
    assert vrfs[0].attributes["rd"] == "65000:1"
    assert len(vrfs[0].attributes["route_targets"]) == 2


def test_vlan_extractor():
    root = build_ast(SAMPLE_CONFIG)
    vlans = [f for f in analyze(root) if f.kind == "vlan"]
    assert vlans[0].attributes == {"id": 10, "name": "USERS"}


def test_qos_extractor():
    root = build_ast(SAMPLE_CONFIG)
    findings = analyze(root)
    class_maps = [f for f in findings if f.kind == "qos_class_map"]
    policy_maps = [f for f in findings if f.kind == "qos_policy_map"]
    assert class_maps[0].attributes["name"] == "VOICE"
    assert policy_maps[0].attributes["name"] == "QOS_OUT"
    assert "VOICE" in policy_maps[0].attributes["classes"]


def test_nat_extractor():
    root = build_ast(SAMPLE_CONFIG)
    findings = analyze(root)
    pools = [f for f in findings if f.kind == "nat_pool"]
    rules = [f for f in findings if f.kind == "nat_rule"]
    assert pools[0].attributes["name"] == "POOL1"
    assert pools[0].attributes["start_ip"] == "192.168.1.1"
    assert "ACL_IN" in rules[0].attributes["rule"]


def test_security_rule_extractor():
    root = build_ast(SAMPLE_CONFIG)
    rules = [f for f in analyze(root) if f.kind == "security_rule"]
    assert rules and rules[0].attributes["acl_ref"] == "ACL_IN"
    assert rules[0].attributes["direction"] == "in"


def test_state_error_warning_extractor():
    root = build_ast(SAMPLE_ERROR_LINE)
    findings = [f for f in analyze(root) if f.kind == "error"]
    assert findings and findings[0].attributes["code"] == "%OSPF-5-ADJCHG"


def test_dependency_extractor_finds_cross_references_not_declarations():
    root = build_ast(SAMPLE_CONFIG)
    deps = [f for f in analyze(root) if f.kind == "dependency"]
    referenced_names = {d.attributes["referenced_name"] for d in deps}
    # ACL_IN is declared once (its own "ip access-list extended ACL_IN" line)
    # and referenced from the interface's access-group line and the NAT rule.
    assert "ACL_IN" in referenced_names
    acl_refs = [d for d in deps if d.attributes["referenced_name"] == "ACL_IN"]
    assert not any(d.attributes["referencing_text"].startswith("ip access-list") for d in acl_refs)
    assert any("access-group" in d.attributes["referencing_text"] for d in acl_refs)


def test_analyze_structured_json_like():
    data = {"interfaces": [{"name": "Gi0/1", "mtu": 1500, "ip": "10.0.0.1"}],
           "vlans": [{"vlan-id": 10, "name": "USERS"}]}
    findings = analyze_structured(data, source_format="json")
    kinds = {f.kind for f in findings}
    assert "interface" in kinds
    assert "vlan" in kinds


# ── Canonicalizer ─────────────────────────────────────────────────────────

def test_finding_to_object_stamps_provenance_and_type():
    finding = SemanticFinding(kind="interface", attributes={"name": "Gi0/1", "mtu": 1500},
                              line=5, raw_text="interface Gi0/1", extractor="interface_extractor")
    obj = finding_to_object(finding, device="R1", source_doc_id="doc1", vendor="cisco")
    assert obj.type == ObjectType.INTERFACE.value
    assert obj.device == "R1"
    assert obj.get("mtu") == 1500
    for key in ("_confidence", "_source_doc_id", "_vendor", "_extracted_by",
               "_compiler_version", "_hash"):
        assert key in obj.attributes
    assert obj.get("_source_doc_id") == "doc1"
    assert obj.get("_extracted_by") == "deterministic"


def test_finding_to_object_stable_id_same_input():
    finding = SemanticFinding(kind="vrf", attributes={"name": "CUSTOMER_A"}, line=1)
    obj1 = finding_to_object(finding, device="R1")
    obj2 = finding_to_object(finding, device="R1")
    assert obj1.id == obj2.id


def test_finding_to_object_skips_dependency_kind():
    finding = SemanticFinding(kind="dependency", attributes={"referenced_name": "ACL_IN"})
    assert finding_to_object(finding, device="R1") is None


# ── Relationship compiler ─────────────────────────────────────────────────

def test_derive_relationships_interface_vrf_and_acl():
    root = build_ast(SAMPLE_CONFIG)
    findings = analyze(root)
    objects = [o for o in (finding_to_object(f, device="R1", vendor="cisco") for f in findings) if o]
    rels = derive_relationships(objects)

    iface = next(o for o in objects if o.type == "interface" and o.get("name") == "GigabitEthernet0/1")
    vrf = next(o for o in objects if o.type == "vrf")
    acl_rules = [o for o in objects if o.type == "acl"]

    belongs_to = [r for r in rels if r.relationship_type == RelationType.BELONGS_TO.value]
    assert any(r.source == iface.id and r.target == vrf.id for r in belongs_to)

    uses = [r for r in rels if r.relationship_type == RelationType.USES.value]
    assert any(r.source == iface.id and r.target in {a.id for a in acl_rules} for r in uses)


# ── Validation ─────────────────────────────────────────────────────────────

def test_validate_objects_missing_required_field():
    finding = SemanticFinding(kind="interface", attributes={"mtu": 1500})  # no "name"
    obj = finding_to_object(finding, device="R1")
    issues = validate_objects([obj])
    assert any(i.code == "missing_field" for i in issues)


def test_validate_objects_conflict_on_same_id_different_attributes():
    f1 = SemanticFinding(kind="neighbor", attributes={"neighbor_ip": "10.0.0.2", "state": "FULL"})
    f2 = SemanticFinding(kind="neighbor", attributes={"neighbor_ip": "10.0.0.2", "state": "LOADING"})
    obj1 = finding_to_object(f1, device="R1")
    obj2 = finding_to_object(f2, device="R1")
    assert obj1.id == obj2.id  # same identifying key -> same object id
    issues = validate_objects([obj1, obj2])
    assert any(i.code == "conflict" for i in issues)


def test_validate_relationships_broken_reference_does_not_raise():
    from core.knowledge_graph import GraphRelationship
    finding = SemanticFinding(kind="vrf", attributes={"name": "CUSTOMER_A"})
    obj = finding_to_object(finding, device="R1")
    dangling = GraphRelationship(source=obj.id, target="R1:interface:does-not-exist",
                                 relationship_type=RelationType.BELONGS_TO.value)
    issues = validate_relationships([obj], [dangling])
    assert any(i.code == "broken_reference" for i in issues)


# ── SemanticCompiler integration ───────────────────────────────────────────

def test_compile_configuration_end_to_end_publishes_to_graph():
    graph = KnowledgeGraph()
    compiler = SemanticCompiler(graph=graph)
    report = compiler.compile_configuration(SAMPLE_CONFIG, device="R1", vendor="cisco")

    assert report.objects
    assert report.relationships
    assert len(graph.nodes) == len(report.objects)
    assert len(graph.relationships) == len(report.relationships)

    iface_node_ids = [nid for nid, n in graph.nodes.items() if n.label == "interface"]
    assert iface_node_ids
    # KnowledgeGraph.add_relationship never raised — every published edge's
    # endpoints exist in graph.nodes by construction.
    for rel in graph.relationships:
        assert rel.source in graph.nodes and rel.target in graph.nodes


def test_compile_protocol_filters_to_protocol_scope():
    compiler = SemanticCompiler(graph=KnowledgeGraph())
    report = compiler.compile_protocol(SAMPLE_CONFIG, "ospf", device="R1", vendor="cisco")
    assert report.objects
    assert all(o.type in ("protocol", "neighbor", "timer") or o.get("protocol") == "ospf"
              for o in report.objects)


def test_compile_incremental_skips_unchanged_file(tmp_path):
    path = tmp_path / "r1.cfg"
    path.write_text(SAMPLE_CONFIG)
    compiler = SemanticCompiler(graph=KnowledgeGraph())

    first = compiler.compile_incremental(str(path))
    assert not first.skipped
    node_count_after_first = len(compiler.graph.nodes)

    second = compiler.compile_incremental(str(path))
    assert second.skipped
    assert len(compiler.graph.nodes) == node_count_after_first  # no duplicate publish


def test_compile_directory_aggregates_multiple_files(tmp_path):
    (tmp_path / "r1.cfg").write_text(SAMPLE_CONFIG)
    (tmp_path / "r1_neighbors.log").write_text(SAMPLE_NEIGHBOR_SHOW)

    compiler = SemanticCompiler(graph=KnowledgeGraph())
    report = compiler.compile_directory(str(tmp_path))
    assert report.stats["files_compiled"] == 2
    assert report.objects


def test_validate_re_checks_without_recompiling():
    compiler = SemanticCompiler(graph=KnowledgeGraph())
    report = compiler.compile_configuration(SAMPLE_CONFIG, device="R1", vendor="cisco")
    issues = compiler.validate(report)
    assert isinstance(issues, list)
