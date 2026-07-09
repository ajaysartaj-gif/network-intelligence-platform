# The Canonical Network Language (CNL)

> Status: specification of what's implemented, not an aspirational design.
> Every type/field named here maps to real code. Companion documents:
> [`nkc_architecture_blueprint.md`](nkc_architecture_blueprint.md),
> [`nkc_gap_analysis.md`](nkc_gap_analysis.md).

## What the CNL is

The CNL is **`core.vendor.models.NormalizedObject`** — it already existed
before the Network Knowledge Compiler, built for the Universal Vendor
Adapter Framework so `TroubleshootingEngine` never sees vendor syntax. The
Semantic Compiler (`core/knowledge/compiler/`) is a second **producer** of
the same shape (from documents/config/CLI text instead of live device
reads), not a second CNL. Any vendor's syntax — Cisco, Juniper, Arista,
Fortinet, Palo Alto, Huawei, Dell, Extreme, OpenConfig, YANG — that
describes "an interface with MTU 1500" compiles to the same
`NormalizedObject(type="interface", attributes={"mtu": 1500, ...})`,
regardless of which vendor's spelling produced it.

```python
NormalizedObject(type: str, id: str, device: str, attributes: Dict[str, Any])
```

## Object types (the `ObjectType` enum, `core/vendor/models.py`)

| Type | Family (ontology) | Required fields | Produced by | Example attributes |
|---|---|---|---|---|
| `interface` | Object | `name` | `interface_extractor` | `name, ip, mask, mtu, description, vrf, vlan, admin_state, acl_ref, acl_direction, nat_role, qos_policy, qos_direction` |
| `protocol` | Protocol | `protocol` | `protocol_extractor` | `protocol, process_id, networks, areas, bgp_neighbors` |
| `neighbor` | Object | — | `protocol_extractor` | `neighbor_ip, state` |
| `vrf` | Object | `name` | `vrf_extractor` | `name, rd, route_targets` |
| `vlan` | Object | `id` | `vlan_extractor` | `id, name` |
| `acl` | Security | `acl_name` | `acl_extractor` | `acl_name, action, rule` |
| `security_rule` | Security | — | `security_rule_extractor` | `acl_ref, direction, interface` \| `zone_pair, source_zone, dest_zone` |
| `qos` | Feature | `name` | `qos_extractor` | `name` (class-map) \| `name, classes` (policy-map) |
| `nat` | Feature | — | `nat_extractor` | `name, start_ip, end_ip` (pool) \| `kind, rule` (rule) |
| `vlan`/`vrf`/`acl`/`interface` (structured) | — | — | `analyze_structured()` | same fields, sourced from JSON/YAML/XML instead of line text |
| `timer` *(bare string, not an enum member)* | Configuration | — | `protocol_extractor` | `timer_type, value, context` |
| `state` *(bare string)* | OperationalState | — | `state_error_warning_extractor` | `subject, state` |
| `event` | Event | — | `state_error_warning_extractor` | `code, message` (errors) \| `message` (warnings) |
| `device, route, tunnel, topology, service, application, flow, telemetry, alarm, inventory, configuration` | various | — | *(pre-existing, produced by live `VendorAdapter`s, not yet by the Semantic Compiler)* | — |
| `cloud_resource` | Cloud | — | *(enum member exists; no extractor yet — see "Deliberately not modeled" below)* | — |

`timer` and `state` are plain strings, not `ObjectType` enum members —
`NormalizedObject.type` accepts either by design (`core/vendor/models.py`'s
own docstring: "illustrative, NOT exhaustive"); adding an enum member for
every fine-grained finding kind would be premature taxonomy-building.

## Relationships (the `RelationType` enum, `core/knowledge_graph.py`)

`DEPENDS_ON, USES, IMPLEMENTS, CONTAINS, CONNECTED_TO, NEIGHBOR_OF,
ROUTES_THROUGH, ADVERTISES, LEARNS_FROM, CAUSES, AFFECTED_BY,
CONFLICTS_WITH, OVERRIDES, SUPPORTS, DEPRECATED_BY, INTRODUCED_IN,
VALIDATED_BY, VERIFIED_BY, RESOLVED_BY, PROTECTS, BELONGS_TO, RELATED_TO`

Deterministic rules currently producing edges
(`core/knowledge/compiler/relationships.py`):

| Rule | Edge |
|---|---|
| `rule_interface_belongs_to_vrf` | `interface --BELONGS_TO--> vrf` |
| `rule_interface_uses_acl` | `interface --USES--> acl` |
| `rule_security_rule_implements_acl` | `security_rule --IMPLEMENTS--> acl` |
| `rule_interface_uses_qos_policy` | `interface --USES--> qos` |
| `rule_vlan_contains_interface` | `vlan --CONTAINS--> interface` |
| `rule_protocol_contains_neighbor` | `protocol --CONTAINS--> neighbor` |

The vocabulary is intentionally larger than what's wired today — new rules
are additive (one new function registered in `RULES`), same shape as the
extractor registry.

## Identity & provenance conventions

Every compiled object's `id` is `f"{device}:{type}:{key}"`, where `key` is
type-specific (interface name, `protocol:process_id`, VRF name, VLAN id,
...) — see `canonicalizer.py::_primary_key`. Before the key is computed,
interface and protocol names are run through
`core/knowledge/compiler/identity.py`'s deterministic normalizers
(`Gi0/1` → `GigabitEthernet0/1`, `ospfv2` → `ospf`), so syntactic variants
of the same entity compile to the same id and MERGE rather than collide as
a false conflict.

Reserved (`_`-prefixed) attribute keys, present on every compiled object,
never touched by extractors:

```
_confidence         float, 0-1 (0.9 for deterministic extraction)
_source_doc_id       the compile's source_doc_id
_vendor              vendor string, if known
_extracted_by        "deterministic" (LLM fallback path reserved, unused today)
_compiler_version    e.g. "nkc-semantic-compiler/0.1"
_source_line         source line number (0 for structured-data findings)
_extractor           which extractor produced this finding
_hash                content hash, for duplicate/conflict detection
_merged_from         list of source_doc_ids merged into this object (after identity resolution)
_merge_count          how many raw findings/objects merged into this one
_conflicting_values  dict of key -> [values] when merge found a genuine conflict
```

## Ontology (`core/knowledge/compiler/ontology.py`)

Families, per `docs/nkc_architecture_blueprint.md` Part 5, now real code:
`Infrastructure, Object, Protocol, Configuration, Security, Feature, Cloud,
Application, OperationalState, Event, Uncategorized`. `family_of(type) ->
str` never raises — an unclassified type resolves to `Uncategorized`
rather than blocking compilation.

## Deliberately NOT modeled as graph nodes (yet)

**Intent, Risk, Verification, Failure** are real concepts with real,
working homes elsewhere in the platform — modeling them as new graph node
types now, with no extractor producing them, would be dead enum surface:

| Concept | Real existing home |
|---|---|
| Intent | `core.vendor.operations.RemediationIntent`, `core.intelligence.config_synthesis.base.ConfigIntent` |
| Risk | `core.governance.contract.GovernanceContract.risk_score`/`risk_level` |
| Verification | `core.troubleshooting.models.VerificationPlan` |
| Failure / root cause | `core.troubleshooting.hypotheses`, `core.intelligence.faculties.HypothesisGenerator` |

Bridging any of these into the compiled graph is real future work once
there's a concrete producer (e.g. an extractor that reads a "known bug
signature" KB article into a `FAILURE_SIGNATURE` object) — not invented
speculatively here.

## Cross-vendor equivalence — what's real vs. what would be a bug

The CNL guarantees that the SAME vendor's syntactic variants (Cisco
`Gi0/1` vs `GigabitEthernet0/1`) compile to the same canonical object.
It does **not** assert that Cisco `Gi0/1` and Juniper `ge-0/0/1` are "the
same interface" — there is no syntactic mapping between different
vendors' physical numbering schemes, and asserting one would be a false
equivalence, not a feature. Where two vendors' devices are actually
connected on the same physical link, that's a live topology-discovery fact
(`core.topology.l3_topology`), correlated from CDP/LLDP + IP subnet
evidence — a different kind of evidence than lexical parsing can ever
provide.
