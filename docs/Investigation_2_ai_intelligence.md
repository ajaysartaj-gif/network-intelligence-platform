# Investigation 2 — AI Intelligence Architecture
### NetBrain AI (`network-intelligence-platform`) — every AI component, reverse-engineered from source

> Rules honored: only repository evidence; no speculation; no assumed prompts or reasoning.
> Every component cites file / class / function / line from the working tree. Anything not
> provable is marked **“Not found in repository.”**

---

## Evidence index

| # | Component | Primary file | Anchor symbol : line |
|---|---|---|---|
| 1 | Intent Engine | `core/intent_engine.py` | `IntentEngine` :168 |
| 2 | Planning | `core/intent_engine.py` / `core/autonomous_monitor.py` | `_ai_generate_plan` :334 / `_build_plan` :965 |
| 3 | Prompt Builder | `core/ai_config.py` | `build_prompt` :355 |
| 4 | Groq Integration | `core/ai_engine.py` / `app.py` | `get_client` :53 / `call_ai` :354 |
| 5 | LLM Invocation | `app.py` / `core/ai_engine.py` | `call_ai` :354 / `ask_ai` :67 |
| 6 | System Prompts | `core/ai_config.py` + 3 more | `NETBRAIN_ENGINE_PREAMBLE` :187 |
| 7 | Conversation Memory | `core/orchestration_engine.py` / `app.py` | `query_history` :73 / `nlp_messages` :4363 |
| 8 | RAG | `core/rag_engine.py` | `RAGEngine.search` :35 |
| 9 | Knowledge Graph | `core/knowledge_graph.py` | `KnowledgeGraph` :23 |
| 10 | Operational Memory | `core/intelligence/operational_memory.py` | `OperationalMemory` :149 |
| 11 | Reasoning Engine | `core/intelligence/reasoning.py` | `ReasoningRegistry` :176 |
| 12 | Decision Engine | `core/intelligence/decision/engine.py` | `DeliberationEngine` |
| 13 | Learning | `core/intelligence/learning/engine.py` | `LearningEngine` |
| 14 | Forecasting | `core/intelligence/forecasting/engine.py` | `PredictionEngine` |
| 15 | Capability Model | `core/intelligence/capability_model.py` | `CapabilityRegistry` :74 |
| 16 | Autonomy | `core/intelligence/autonomy/controller.py` | `AutonomicController` |
| 17 | Configuration Generation | `core/ai_config.py` | `generate_config` :383 |
| 18 | Rollback Generation | `core/ai_config.py` | `_finalize_rollback_plan` :143 |
| 19 | Verification | `core/intelligence/outcome_contract.py` | `OutcomeContractEngine.enforce` :224 |
| 20 | Simulation | `core/simulation_engine.py` | `SimulationEngine.step` :247 |
| 21 | Digital Twin | `core/digital_twin_engine.py` | `DigitalTwinEngine` :27 |

---

## 1. Intent Engine

- **Purpose:** Classify an operator query and route it to a config or diagnostic flow. Proven by
  `INTENT_CONFIG = "config"` (`:74`) and the branch `if intent == INTENT_CONFIG` (`:214`, `:317`).
- **Location:** `core/intent_engine.py`, class `IntentEngine` (`:168`).
- **Entry function:** `handle(...)` (`:293`); alt `propose_plan(...)` (`:185`).
- **Exit function:** `format_for_chat(result, device_name)` (`:1135`) — returns the chat string.
- **Dependencies:** an injected `ai_call` (constructor `__init__` `:175`, used at `:266`, `:419`,
  `:556`); dataclasses `DeviceResult` (`:120`), `DiagnosticPlan` (`:131`), `IntentResult` (`:142`).
- **Input:** query string + device scope (constructor args).
- **Output:** `IntentResult` (`:142`) → formatted chat text.
- **Interactions:** calls **LLM Invocation** via `ai_call`; produces **Planning** (`_ai_generate_plan`
  `:334`); invoked from `app.py` nlp workspace (`app.py:3373` `IntentEngine(...).handle`,
  `:3426` `format_for_chat`). No direct call to RAG/KG proven → **Not found in repository.**

## 2. Planning

- **Purpose:** Produce an ordered plan of devices/steps for a query.
- **Location / Entry / Exit:** two distinct, proven planners:
  - `IntentEngine._ai_generate_plan(...)` (`:334`) builds `plan_prompt` (`:359`) and calls
    `self.ai_call(plan_prompt)` (`:419`); parsed by `_parse_plan_response(...)` (`:423`);
    missing devices repaired by `_ai_complete_missing_devices(...)` (`:513`, prompt `:533`,
    `self.ai_call` `:556`).
  - `AutonomousMonitor._build_plan(anomaly, rca)` (`core/autonomous_monitor.py:965`).
- **Dependencies:** LLM (`ai_call`); for the monitor, the RCA string from `_run_rca` (`:884`).
- **Input:** classified intent + devices (engine) / anomaly + RCA (monitor).
- **Output:** `DiagnosticPlan` (`:131`) / list of plan steps (`List[str]`, monitor `:965`).
- **Interactions:** Planning → LLM; monitor Planning → **Verification** (`_verify_recovery` `:1022`).

## 3. Prompt Builder

- **Purpose:** Assemble the config-generation prompt. Proven: `build_prompt(...)`
  (`core/ai_config.py:355`).
- **Entry/Exit:** `build_prompt` returns a single string composed of `NETBRAIN_ENGINE_PREAMBLE`
  (`:187`) + `TARGET DEVICE` + inventory block + `DEVICE DATA` + fleet block + `USER INTENT` +
  a literal `SAFETY (hard deny …)` section (`:374–381`).
- **Dependencies:** `NETBRAIN_ENGINE_PREAMBLE` (`:187`); helpers `build_inventory_summary` (`:298`),
  `collect_device_context` (`:308`), `build_fleet_topology_context` (`:342`).
- **Input:** `request, device, device_facts, fleet_context, inventory_summary` (`:356–360`).
- **Output:** prompt string consumed by `generate_config` at `ai_call(build_prompt(...))` (`:453`).
- **Interactions:** Prompt Builder → **Configuration Generation** → **LLM Invocation**. Other
  prompts are built inline elsewhere (Intent `:359`, outcome contract `:169`), not via this builder.

## 4. Groq Integration

- **Purpose:** Provide an OpenAI-SDK client pointed at Groq.
- **Location:** `core/ai_engine.py` — `get_api_key()` (`:18`), `get_client()` (`:53`);
  also independently in `app.py` `_get_ai_client` / `call_ai` (`:340/354`).
- **Entry/Exit:** `get_client()` returns `OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)` (`:60–64`).
- **Dependencies:** `GROQ_BASE_URL`, `MODEL` (module constants); `st.secrets` / `os.environ` /
  `.env` (`get_api_key` 3-tier: `:20`, `:29`, `:33–41`).
- **Input:** none (reads key from environment).
- **Output:** an `OpenAI` client object, or `None` if no key (`:55–56`).
- **Interactions:** consumed by **LLM Invocation** (`ask_ai`, `call_ai`).

## 5. LLM Invocation

- **Purpose:** Execute a chat completion.
- **Location/Entry/Exit:**
  - `app.py:call_ai(prompt)` (`:354`) → `client.chat.completions.create(model=MODEL_NAME,
    messages=[system, user], max_tokens=800, temperature=0.1)` (`:365–384`); returns
    `resp.choices[0].message.content` (`:381`) or `f"AI Error: {err}"` (`:387`).
  - `core/ai_engine.py:ask_ai(query)` (`:67`) → `client.chat.completions.create(model=MODEL, …)`.
- **Dependencies:** Groq Integration (`get_client` / inline `OpenAI`), the system prompt strings.
- **Input:** a single prompt string.
- **Output:** model text (string).
- **Interactions:** invoked by Intent (`ai_call`), Configuration Generation (`ai_call`), Outcome
  Contract (`ai_call`), Copilot (`call_ai` at `app.py` copilot block, rel `:618`). `call_ai` is
  passed as the `ai_call`/`ai_call_fn` dependency into those modules (`app.py:1964`, `:2522`,
  `_get_monitor` `:485`).

## 6. System Prompts (verbatim, proven)

Four distinct system prompts exist in source:
1. **Config engine** — `NETBRAIN_ENGINE_PREAMBLE` (`core/ai_config.py:187`): *“You are NetBrain, a
   CCIE-level Network Intelligence Engine…”* (requests internal analysis + JSON sections).
2. **ask_ai** — `core/ai_engine.py:74` system content: *“You are NetBrain, a CCIE-level Network
   Intelligence Engine. Analyze topology and device context before recommending changes…”*
3. **call_ai** — `app.py:367` system content: *“You are NetBrain AI — an expert autonomous network
   operations system. Be concise, technical, and action-oriented…”*
4. **Outcome contract** — `core/intelligence/outcome_contract.py:174+` (interpret) and `:116+`
   (derive) prompts: *“You are a CCIE-level engineer judging whether a post-condition is met…”*
- The Copilot system text `_cp_sys` is built inline in the copilot block (`app.py` rel `:611–618`).

## 7. Conversation Memory

- **Purpose:** Retain prior turns.
- **Location/Entry/Exit:** two layers, both proven:
  - **Orchestrator:** `self.query_history: List[QueryRecord]` (`core/orchestration_engine.py:73`);
    write `record_query(query, response, source)` (`:494`); read `get_query_history(limit)` (`:497`).
  - **UI session:** `st.session_state["nlp_messages"]` (`app.py:4363–4401`) appended with
    `{"role","content"}` dicts; copilot uses its own session list (copilot block).
- **Dependencies:** `QueryRecord` dataclass (`core/orchestration_engine.py:35`); Streamlit
  `session_state`.
- **Input/Output:** query+response strings in, list of records out.
- **Interactions:** populated by UI handlers after **LLM Invocation**; not consumed by the LLM call
  path automatically (no evidence `query_history` is fed back into a prompt) → **Not found in
  repository** that conversation history is injected into prompts.

## 8. RAG

- **Purpose:** Keyword retrieval over seeded knowledge docs.
- **Location:** `core/rag_engine.py`, `RAGEngine` (`:16`).
- **Entry function:** `search(query, vendor, protocol, top_k=5)` (`:35`).
- **Exit:** returns `List[Dict]` with `id,title,vendor,protocol,score,snippet` (`:57–63`).
- **Dependencies:** `_tokenize` (`:25`), `_score_document` (`:28`), `KnowledgeDocument` (`:7`).
  **Retrieval is keyword/token scoring, NOT embeddings** — proven: `search` calls `_tokenize(query)`
  and `_score_document(query_tokens, document)` and sorts by `score` (`:42–66`). No embedding/vector
  call present → **embeddings Not found in repository.**
- **Input:** query text (+ optional vendor/protocol filters).
- **Output:** ranked document dicts.
- **Interactions:** instantiated as `self.rag = RAGEngine(...)` in the orchestrator
  (`core/orchestration_engine.py:53`); seeded by `_seed_default_documents` (`:422`). Used by
  `config_synthesis.engine._ground` if reachable (best-effort). No proven call from the main
  `generate_config` LLM path → the config LLM prompt is **not** RAG-grounded in `build_prompt`
  (**Not found in repository**).

## 9. Knowledge Graph

- **Purpose:** Dependency/impact graph over devices/services.
- **Location:** `core/knowledge_graph.py`, `KnowledgeGraph` (`:23`).
- **Entry functions:** `add_node` (`:31`), `add_relationship` (`:35`); queries
  `get_dependencies` (`:55`), `find_path` (`:58`), `trace_impact_chain` (`:74`).
- **Exit:** `dependency_summary()` (`:94`) → dict.
- **Dependencies:** `GraphNode` (`:8`), `GraphRelationship` (`:15`).
- **Input:** node/edge definitions.
- **Output:** dependency lists, paths, impact chains (graph traversal).
- **Interactions:** `self.kg = KnowledgeGraph()` in orchestrator (`:58`), seeded by
  `_seed_knowledge_graph` (`:447`); rebuilt in `build_topology` (`:509`). This is the **graph-based**
  reasoning substrate. No LLM dependency.

## 10. Operational Memory

- **Purpose:** Persistent record of verified outcomes; recall of recurring failures/similar cases.
- **Location:** `core/intelligence/operational_memory.py`, `OperationalMemory` (`:149`).
- **Entry functions:** `record_from_contract(...)` (`:234`); recall `temporal(...)` (`:359`),
  `recurring_failures(...)` (`:406`). Singleton `get_operational_memory()` (`:469`).
- **Exit:** `bind_memory_capability()` (`:476`) registers the capability probe.
- **Dependencies:** `_Backend` (`:87`, SQLite/Postgres), `MemoryEvent` (`:58`), `EventType` (`:46`),
  `_cosine` (`:78`), `_signature` (`:445`).
- **Input:** an outcome contract (in `record_from_contract`).
- **Output:** persisted rows; recall dicts (`_row_to_dict` `:454`).
- **Interactions:** written from the deploy path after **Verification** (`app.py` admin block);
  read by **Learning** (`Corpus` in learning) and **Forecasting**. Bound at `_bind_capabilities`
  (`app.py:215`).

## 11. Reasoning Engine

- **Purpose:** A registry of typed reasoners producing `Conclusion`s.
- **Location:** `core/intelligence/reasoning.py`.
- **Entry functions:** `ReasoningRegistry.reason(key, context)` (`:192`),
  `reason_chain(keys, context)` (`:197`); singleton `get_reasoning_registry()` (`:244`).
- **Exit:** `bind_reasoning_capability()` (`:262`).
- **Dependencies:** `Reasoner` (ABC, `:94`, `reason` `:112`), `ReasonerSpec` (`:82`),
  `Conclusion` (`:54`), `Evidence` (`:46`), `EpistemicType` (`:36`).
- **Input:** a context dict.
- **Output:** `Conclusion` objects (claim, confidence, epistemic_type, evidence, alternatives).
- **Interactions:** other subsystems register reasoners into it — Forecasting (`forward_outlook`),
  Learning (`lesson_recall`), Decision (`judgment`) — proven by their `wire_*` functions binding to
  `get_reasoning_registry().register(...)`. `EpistemicType` (`:36–42`) enumerates
  DETERMINISTIC/PROBABILISTIC/GRAPH/ML/LLM/HYBRID — the explicit taxonomy of how it reasons.

## 12. Decision Engine

- **Purpose:** Deliberate over options → an explained, confidence-bearing `Judgment`.
- **Location:** `core/intelligence/decision/engine.py`; package exports (`__init__.py __all__`):
  `DeliberationEngine, get_deliberation_engine, judge, wire_decision, Option, DecisionContext,
  Judgment, Appraisal`.
- **Entry:** `judge(question, options, …)` / `DeliberationEngine.judge(ctx)`.
- **Exit:** `wire_decision()` registers a `judgment` reasoner + capability pillar.
- **Dependencies:** Forecasting, Memory, Learning, Autonomy (`authorize`) — invoked inside the
  faculties/engine (proven in `decision/faculties.py`, `decision/engine.py`).
- **Input:** `DecisionContext` with `Option`s.
- **Output:** `Judgment` (chosen, ranking, confidence, tradeoffs, dissent).
- **Interactions:** exposed to **Reasoning** as the `judgment` reasoner; callable via
  orchestrator `deliberate()` (`core/orchestration_engine.py:838`).

## 13. Learning

- **Purpose:** Turn every event into durable lessons; periodic retrospection.
- **Location:** `core/intelligence/learning/engine.py`; exports: `LearningEngine,
  get_learning_engine, learn_from, wire_learning, Lesson, LessonType, LearningEvent, LessonStore`.
- **Entry:** `learn_from(event)` / `learn_from_contract(...)`; `retrospect()`.
- **Exit:** `wire_learning()` (registers learners + `lesson_recall` reasoner + pillars).
- **Dependencies:** Operational Memory (`Corpus`), Memory system, Reasoning registry.
- **Input:** `LearningEvent` / outcome contract.
- **Output:** `Lesson` records in `LessonStore`.
- **Interactions:** written from the deploy path (`learn_from_contract`, `app.py` admin block);
  surfaces lessons into **Reasoning**. Bound at `_bind_capabilities` (`app.py:262`).

## 14. Forecasting

- **Purpose:** Probabilistic forecasts (risk, success, cascade, etc.).
- **Location:** `core/intelligence/forecasting/engine.py`; exports: `PredictionEngine,
  get_prediction_engine, wire_prediction, Forecast, Forecaster, ForecasterSpec, ForecastType,
  Driver, ForecastRegistry`.
- **Entry:** `forecast(context, only=…)`; `resolve_outcomes()`; `early_warning()`.
- **Exit:** `wire_prediction()` (binds Prediction pillar + `forward_outlook` reasoner).
- **Dependencies:** Operational Memory + Memory (trust) for self-calibration.
- **Input:** a context dict (device/intent/protocol/site).
- **Output:** `Forecast` objects (`risk`, `probability`, `severity`, `kind`, `target`).
- **Interactions:** consumed by **Decision** faculties and `_maybe_resolve_forecasts`
  (`app.py:290`). Bound at `_bind_capabilities` (`app.py:240`).

## 15. Capability Model

- **Purpose:** A registry of platform capabilities with live health probes.
- **Location:** `core/intelligence/capability_model.py`, `CapabilityRegistry` (`:74`).
- **Entry:** `register(cap)` (`:80`), `bind_probe(key, probe)` (`:83`), `report()` (`:96`).
- **Exit:** `report()` → list of capability dicts.
- **Dependencies:** `Capability` (`:55`), `CapabilityHealth` (`:43`), `CapabilityStatus` (`:35`);
  built-in probes `_probe_knowledge` (`:130`), `_probe_topology` (`:144`), `_probe_risk` (`:161`),
  `_probe_context` (`:171`), `_probe_memory` (`:185`).
- **Input:** capability definitions + probe callables.
- **Output:** capability health report.
- **Interactions:** every intelligence subsystem binds a pillar here in its `wire_*`
  (Memory/Forecasting/Autonomy/Learning/Decision/Config). Rendered by the `intelligence` workspace.

## 16. Autonomy

- **Purpose:** MAPE-K self-management + a safety authorization gate.
- **Location:** `core/intelligence/autonomy/controller.py`; exports: `Action, Decision, Verdict,
  AutonomyLevel, Goal, autonomy_ceiling, AutonomicController, get_controller, authorize,
  wire_autonomy`.
- **Entry:** `authorize(Action)` → `Decision`; `AutonomicController.governed_run(...)`.
- **Exit:** `wire_autonomy()` (registers faculties + pillars + gate).
- **Dependencies:** Forecasting (risk), Memory (experience/business/trust), capability model.
- **Input:** an `Action` (kind/intent/device/protocol).
- **Output:** a `Decision` (`Verdict` ALLOW/GATE/DENY).
- **Interactions:** consumed by **Decision** engine (`authorize` inside `_compose`) and orchestrator
  `authorize_change` (`core/orchestration_engine.py:812`), `autonomic_cycle` (`:797`).

## 17. Configuration Generation

- **Purpose:** Turn intent into device commands.
- **Location:** `core/ai_config.py`, `generate_config(...)` (`:383`).
- **Entry:** `generate_config(request, device, ai_call, device_facts, …)` (`:383`).
- **Exit:** returns `out` dict (`status, commands, rollback, verify, risk, …`) — multiple `return out`
  (`:411/415/448/461/475/508/517/526`).
- **Dependencies:** `config_synthesis` deterministic short-circuit (`:423–448`); `build_prompt`
  (`:453`); `_parse_json` (`:463`); `validate_config` (`:519`); `_finalize_rollback_plan` (`:143`).
- **Input:** NL request + device + `ai_call`.
- **Output:** validated command set or `status` ∈ {ok, unsafe, empty, unavailable, diagnostic}.
- **Interactions:** **two ordered branches** proven: (a) deterministic `config_synthesis.synthesize`
  for templated features (DNS/NTP/clock) returns first (`:448`); (b) otherwise LLM via
  `ai_call(build_prompt)` (`:453`). Then **Verification** (`validate_config`) gates output.

## 18. Rollback Generation

- **Purpose:** Produce safe rollback commands.
- **Location:** `core/ai_config.py`.
- **Entry/Exit:** rollback taken from the LLM JSON `data.get("rollback")` (`:497`), then
  `_finalize_rollback_plan(cmds, rollback, explanation)` (`:143`, called `:521`) — only when
  `mode == "config"` (`:520`). In the deterministic branch, rollback is derived as
  `"no " + c` per command (`:441`).
- **Dependencies:** `validate_rollback` (`:129`) with `ROLLBACK_DENY_PATTERNS`; `_finalize_rollback_plan`.
- **Input:** generated commands + AI-proposed rollback.
- **Output:** `out["rollback"]` + `out["rollback_explanation"]`.
- **Interactions:** part of Configuration Generation’s output; consumed by the deploy/rollback path
  (`app.py` copilot rollback `ConnectHandler.send_config_set(_rb_lines)` rel `:539`).

## 19. Verification

- **Purpose:** Prove a change succeeded; gate unsafe config.
- **Location/Entry/Exit (three proven layers):**
  - **Outcome contract** — `core/intelligence/outcome_contract.py`,
    `OutcomeContractEngine.enforce(intent, device_name, applied_commands, run_command, …)` (`:224`):
    `derive_post_conditions` (`:116`, LLM-authored checks) → `interpret` (`:174`) which runs a
    **deterministic precheck** (`config_synthesis.interface.general_precheck`) before the LLM judge,
    re-polls `PENDING`. `Verdict` enum PASS/FAIL/PENDING/UNKNOWN.
  - **Config safety** — `core/ai_config.py:validate_config` (`:112`) using `CONFIG_DENY_PATTERNS`
    (rule-based, regex `_matches_any` `:107`).
  - **Command validator** — `core/verification/command_validator.py` (module present).
- **Dependencies:** LLM (`ai_call`), `config_synthesis` deterministic checks, regex deny lists.
- **Input:** applied commands + a `run_command` callable + live device output.
- **Output:** `ContractResult` (satisfied?, conditions, summary) / `(is_safe, blocked, reasons)`.
- **Interactions:** called by the admin deploy path (`app.py:2530`); writes **Operational Memory**
  and **Learning** afterward.

## 20. Simulation

- **Purpose:** Step a simulated network (legacy/demo mode).
- **Location:** `core/simulation_engine.py`, `SimulationEngine` (`:69`).
- **Entry:** `step()` (`:247`).
- **Exit:** `get_topology_summary()` (`:573`).
- **Dependencies:** `SimulatedDevice` (`:18`), `SimulatedInterface` (`:40`), `SimulatedLink` (`:56`).
- **Input:** internal simulated state.
- **Output:** `{"anomalies": [...]}` (consumed in `run_cycle` step 1, `orchestration_engine.py:690`).
- **Interactions:** used only when `LIVE_ONLY` is false (`orchestration_engine.py:690`,
  `autonomous_monitor.py:130`). Not an LLM component.

## 21. Digital Twin

- **Purpose:** Maintain device/link state; project change impact.
- **Location:** `core/digital_twin_engine.py`, `DigitalTwinEngine` (`:27`).
- **Entry:** `add_device` (`:34`), `add_link` (`:37`), `simulate_impact(hostname, change)` (`:46`),
  `simulate_change(hostname, action)` (`:64`).
- **Exit:** `get_topology()` (`:40`).
- **Dependencies:** `DeviceState` (`:7`), `TopologyLink` (`:19`).
- **Input:** device/link state + a change/action string.
- **Output:** topology dict / impact dict.
- **Interactions:** `self.twin = DigitalTwinEngine()` in orchestrator (`:56`), rebuilt in
  `build_topology` (`:510`); orchestrator `simulate_change_impact` (`:674`) delegates here.
  Note a duplicate legacy file `core/digit_twin_engine.py` exists; the orchestrator imports
  `digital_twin_engine` (`orchestration_engine.py:13`).

---

# Analytical Questions

## Is reasoning deterministic / rule-based / graph-based / LLM-based / hybrid?

**HYBRID — proven by the explicit taxonomy and by five co-existing mechanisms.**
The code itself declares the taxonomy: `EpistemicType` =
`DETERMINISTIC, PROBABILISTIC, GRAPH, ML, LLM, HYBRID` (`core/intelligence/reasoning.py:36–42`).
Each mechanism is present in source:

- **Rule-based / deterministic:** `IntentEngine._classify` (`core/intent_engine.py:658`);
  `validate_config`/`validate_rollback` regex deny lists (`core/ai_config.py:112/129`);
  `config_synthesis.interface.general_precheck` (deterministic verification);
  template compilation in `config_synthesis` (`generate_config:423–448`).
- **Graph-based:** `KnowledgeGraph.find_path` / `trace_impact_chain`
  (`core/knowledge_graph.py:58/74`).
- **Keyword retrieval (not ML embeddings):** `RAGEngine.search` (`core/rag_engine.py:35`).
- **Probabilistic / ML-typed:** Forecasting `PredictionEngine` (`forecasting/engine.py`),
  `Forecast.probability/risk`.
- **LLM-based:** `call_ai` (`app.py:354`), `ask_ai` (`ai_engine.py:67`), `generate_config`
  LLM branch (`ai_config.py:453`), `OutcomeContractEngine.derive_post_conditions`/`interpret`.

No single paradigm governs the platform; they are composed, which is the definition the code gives
for `HYBRID`.

## Where can hallucination first occur?

At the **first LLM generation in a request**, before any deterministic gate:
- **Config requests:** `generate_config` → `ai_call(build_prompt(...))` (`core/ai_config.py:453`),
  reached only when the deterministic `config_synthesis` short-circuit (`:423–448`) does **not**
  match. The raw model text is `_parse_json`’d (`:463`) and only then gated by `validate_config`
  (`:519`). So fabrication can enter at `:453` and is caught (for *safety patterns only*) at `:519`.
- **Planning:** `IntentEngine._ai_generate_plan` `self.ai_call(plan_prompt)` (`:419`).
- **Verification authoring:** `OutcomeContractEngine.derive_post_conditions` (LLM writes the check
  commands, `:116`) and `interpret` (LLM judges output, `:174`).
> `validate_config` blocks only destructive/lockout patterns (`CONFIG_DENY_PATTERNS`); it does **not**
> verify correctness of values, so a hallucinated-but-safe value (e.g. a wrong server IP) is **not**
> caught there — that gap is what `config_synthesis` exists to close for templated features.

## Where is confidence calculated?

- **Forecasting:** `Forecast.probability` / `risk` (forecasting engine) — probabilistic confidence.
- **Reasoning:** `Conclusion.confidence` field (`core/intelligence/reasoning.py:54`).
- **Decision:** `Judgment.confidence` computed in `DeliberationEngine` (decision/engine.py,
  agreement × evidence × margin) — proven by the `Judgment` export and engine logic.
- **Memory trust / calibration:** trust store in the memory system (used by forecasting
  `resolve_outcomes`).
> **AI config “risk”** is **not computed** — it is taken from the model’s JSON:
> `out["risk"] = str(data.get("risk","unknown"))` (`core/ai_config.py:486`). So config-risk is
> LLM-asserted, not calculated. **Not found in repository:** a deterministic confidence score for
> LLM-generated config.

## Where is evidence validated?

- **Live evidence:** `OutcomeContractEngine.enforce` runs real `run_command` show commands and
  fetches `show running-config`/`show startup-config` once (`outcome_contract.py:224+`), then
  `interpret` (`:174`).
- **Deterministic evidence match:** `config_synthesis.interface.general_precheck` /
  `verify_descriptions` (normalized, authoritative running-config).
- **Rule gate:** `validate_config` (`ai_config.py:112`).
- **Reasoning evidence object:** `Evidence` dataclass (`reasoning.py:46`) carried on `Conclusion`.

## Where is missing information detected?

- **Prompt Builder:** `build_prompt` substitutes a literal fallback when no device facts exist —
  *“(No live CLI data — use Login on this device first …)”* (`core/ai_config.py:363`).
- **Planning:** `IntentEngine._ai_complete_missing_devices` (`:513`) explicitly detects and
  back-fills devices the first plan omitted.
- **Config generation:** empty/again-empty handling — `status="empty"` when `not request` (`:413`)
  or `not cmds` (`:506`); `status="unavailable"` when `not ai_call` (`:410`).
- **Verification:** `interpret` returns `PENDING` for not-yet-converged evidence and the engine
  re-polls (`outcome_contract.py` enforce loop).

---

## Honesty ledger (explicitly NOT proven)

- Conversation history is **not** shown being injected back into any LLM prompt → **Not found in
  repository.**
- RAG (`RAGEngine.search`) is **not** shown feeding the main `generate_config` LLM prompt
  (`build_prompt` contains no RAG call) → **Not found in repository.**
- Vector/embedding retrieval → **Not found in repository** (search is keyword scoring).
- A deterministic confidence value for LLM-generated configuration → **Not found in repository**
  (risk is `data.get("risk")`).
- The full bodies of `_score_document`, `derive_post_conditions`, and each intelligence
  subsystem’s internal faculties were not all extracted line-by-line here; their entry/exit symbols
  are proven, deeper internals beyond cited lines are **not** asserted.
