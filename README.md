# Mismatch Strategy + Knowledge-Retrieval Engine (vendor-independent, OSPF)

Runnable. `python3 demo_multivendor.py`, `python3 demo.py`, `python3 -m pytest tests/`.

## What was wrong in v1 (and is now fixed)

v1 had a generic strategy but a **hardcoded adapter**: the command to read a
parameter, the regex to parse it, and the fix syntax lived in Python
(`PARAM_MAP`, `REMEDIATION`). So the vendor guide was never retrieved, and adding
Juniper meant writing a new adapter. That is the anti-pattern, relocated.

Fix: three kinds of knowledge, each sourced correctly.

| Knowledge | Question | Source | Where it lives now |
|---|---|---|---|
| Contract | WHICH params must agree, WHY, symptom | RFC (vendor-neutral) | `corpus/ospf_adjacency.txt` -> KP |
| Observation | HOW to read a param on THIS vendor | vendor command guide | `corpus/vendor/*.txt` -> resolver, cached |
| Remediation | HOW to fix a param on THIS vendor | vendor config guide | `corpus/vendor/*.txt` -> resolver, cached |

All three are RETRIEVED and cached. None are coded. The Cisco guide is now
actually consulted (for IOS reads); Juniper works because its guide exists.

## Adding Juniper cost exactly this

- `corpus/vendor/juniper_junos_ospf.txt`  (the guide the resolver retrieves)
- a Junos transport binding (one line: `device_type="juniper_junos"`)

Zero lines in the strategy, engine, RAG, or a "JuniperAdapter" (there is no such
class). `test_adding_juniper_touched_no_engine_code` fails the build if the words
`ospf`/`cisco`/`juniper` ever appear in engine/strategy/rag executable code.

## The two ideas that make it AI-native

1. **CapabilityResolver = your CommandResolver chain, both directions.**
   `(vendor, read_intent) -> how to read` and `(vendor, param) -> how to fix`,
   resolved cache -> RAG(vendor guide) -> MCP/NETCONF -> grounded-AI, then cached
   with provenance. Prefer structured telemetry (NETCONF/YANG, gNMI, pyATS-Genie)
   over screen-scraping when available -- `MockNetconfTransport` +
   `method=structured` show the no-regex path. The adapter holds no commands.

2. **Normalization = the world model.** The strategy never compares vendor
   strings. It compares canonical values. IOS area `0` and Junos `0.0.0.0` are the
   same area; IOS `BROADCAST` and Junos `LAN` are the same network type. Compare
   raw and you invent a false mismatch on every mixed link. `normalize.py`
   canonicalizes by semantic `read_intent` (vendor-neutral), so mismatch detection
   works across vendors. Demo output: area/type/mask/mtu MATCH across IOS+Junos,
   only the genuine hello 10-vs-30 DIFFERs.

## Transport is the only vendor code, and it is not the anti-pattern

Something must speak SSH/NETCONF to a box; you cannot document your way onto the
wire. But transport knows nothing about OSPF or issues and does not grow with
protocols. In production it is one Netmiko client (100+ platforms behind a
`device_type` string -- data, auto-discoverable) plus one NETCONF client. "New
vendor" = pick an existing transport + a device_type string + feed a guide.
The forbidden thing -- per-protocol/per-issue command+parse+fix tables -- is gone.

## Flow

```
docs ─RAG─▶ KP (what must agree, why, symptom)            [vendor-neutral, RFC]
                    │
seed ─▶ enumerate ─▶ for each param in KP:
                        resolver.resolve_observe(vendor, intent)   ─ vendor guide
                        transport.run(cmd)  ─ thin, vendor wire only
                        extract → normalize → world-model value
                        deterministic compare  (LLM never in this loop)
                        corroborate vs observed state → confidence (log-odds)
                        resolver.resolve_remediate(vendor, param)  → gated fix
```

The strategy file was NOT touched when the entire vendor layer was replaced.

## Wiring into ajaysartaj-gif/network-intelligence-platform

- `MockTransport` -> your Netmiko client (READ-ONLY session). Structured path -> ncclient/PyEZ.
- `DocDrivenResolver` -> your CommandResolver, extended to resolve reads+parsers, not just fixes.
- `StubExtractor`/`LexicalRetriever` -> `GroqExtractor` + `EmbeddingRetriever` over real docs.
- device `platform` string -> from your DeviceDiscoveryEngine.
- `Finding.logodds_delta`/`corroborated` -> evidence into your Troubleshooting Engine hypotheses.
- remediation -> your existing human-approval gate (writes stay gated regardless of how resolved).

## Files
```
knowledge/schema.py        KnowledgePackage + MatchParameter (the WHAT contract)
knowledge/rag_engine.py    retrieve → extract → validate → cache (the KP)
knowledge/capability.py    CapabilityResolver: how-to-read + how-to-fix, via the chain  <-- v2 fix
knowledge/normalize.py     semantic canonicalization = the world model                  <-- v2
knowledge/corpus_loader.py corpus/*.txt → Chunks
strategies/mismatch.py     the one invariant loop (no vendor/protocol strings)
strategies/relation_eval.py deterministic relation + guard logic
adapters/base.py           adapter interface
adapters/generic.py        ONE adapter for all vendors (transport+resolver+normalize) <-- v2
adapters/transport.py      thin per-wire transport (Netmiko/NETCONF seam)              <-- v2
corpus/ospf_adjacency.txt  OSPF contract (RFC stand-in)
corpus/hsrp_pairing.txt    proof: new relationship = new doc
corpus/vendor/cisco_ios_ospf.txt      the Cisco guide (now actually retrieved)
corpus/vendor/juniper_junos_ospf.txt  the entire cost of adding Juniper
lab.py                     wires the non-hardcoded stack from a scenario
tests/                     10 tests incl. mixed-vendor + no-hardcode guardrail
demo.py / demo_multivendor.py
```
