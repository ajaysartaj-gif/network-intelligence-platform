# NRIE — Address Bounded Context (Phase 1: Enterprise Knowledge Foundation)

The **Network Resource Intelligence Engine (NRIE)** address context is the single
place responsible for **enterprise network resource knowledge**. This PR delivers
the *foundation only* — Memory, Resource, Business Context, Organizational Memory
and a Knowledge layer. **No allocation, planning, prediction, optimization, or AI.**

## Layering (DDD)

```
domain/          pure model — no persistence, no allocation
  value_objects  Identifier, EnterpriseLevel, ResourceType/Status, Lifecycle, Tags, Metadata, …
  entities       EnterpriseEntity, NetworkResource, BusinessContext, OrganizationalKnowledge
  aggregates     EnterpriseHierarchy, ResourceInventory, OrganizationalMemory (consistency + events)
  policies       ParentMustExist, HierarchyLevelOrder, BusinessContextAttachment (invariants)
  specifications composable read predicates (by_level, by_resource_type, by_purpose, …)
  events         domain facts (records only)

knowledge/       declarative domain knowledge (no AI)
  ontology       resource relationships      taxonomy   resource classification
  relationships  dependency kinds            glossary   canonical term definitions
  standards      organizational standard kinds
  memory         descriptor of WHAT is remembered + which store backs each layer
  reasoning      descriptor of reasoning questions posed to the EXISTING Reasoning Engine (IMPLEMENTS_AI = False)

contracts/       the ONLY orchestrator touchpoint
  commands  queries  events  dto  interfaces

infrastructure/  persistence + repositories (no business logic)
  persistence    MemoryStore subclasses — REUSES core.intelligence.memory (dual SQLite/Postgres)
  repositories   map domain ↔ stored payloads; persist/retrieve only

api/             thin facade (commands in, DTOs out) + read-only Streamlit panel
  service        NRIEFoundationService / get_nrie_service()
  ui             render_nrie_panel()  (wired next to the Network Topology workspace)

tests/           domain + knowledge + service round-trip (9 tests, all passing)
```

## Reuse (no duplication)

| Need | Reused platform asset |
|------|----------------------|
| Persistence / Memory Platform | `core.intelligence.memory.store.MemoryStore` (dual-backend, consolidation, decay) |
| Knowledge Graph | `core.knowledge_graph` (referenced by `knowledge/reasoning.py`; resolution in later PRs) |
| Reasoning Engine | `core.reasoning_layer` (reasoning surface declared, not reimplemented) |
| Navigation / UI | existing Streamlit workspace registry (`config/workspaces.py`) |
| Logging/telemetry | standard `logging` (`NetBrain.*` loggers) |

## Integration

`Intent → Knowledge Graph → Memory Platform → Reasoning → Orchestrator → Database → Logging → Telemetry`
— NRIE plugs in as the resource-knowledge authority; it introduces **no replacement components**
and exposes **read-only** APIs (`enterprise_hierarchy`, `resource_hierarchy`, `business_context`,
`knowledge`). The UI panel appears in the top navigation immediately after **Network Topology**.

## Out of scope (later PRs)
IP allocation · address/resource planning · prediction · capacity · optimization · route
summarization · explainability · recommendation · validation · deployment · config generation ·
DHCP/DNS automation · vendor/cloud integrations · AI decision-making.
