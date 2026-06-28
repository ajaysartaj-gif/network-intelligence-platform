# Investigation 4 — Configuration Decision Pipeline
### Exactly how NetBrain AI makes configuration decisions — reverse-engineered from source

> Rules honored: no speculation; no recommendations; repository evidence only. Every statement
> cites file / class / function / line. Anything absent is marked **“Not found in repository.”**

---

## Evidence index

| Concern | File | Symbol : line |
|---|---|---|
| Config generation | `core/ai_config.py` | `generate_config` :383 |
| Decision branches | `core/ai_config.py` | status `unavailable/empty/ok/unsafe` :407–526 |
| Deterministic synth | `core/intelligence/config_synthesis/synthesizer.py` | `ConfigSynthesizer.synthesize` :85 |
| Safety gate (config) | `core/ai_config.py` | `validate_config` :112 |
| Safety gate (rollback) | `core/ai_config.py` | `validate_rollback` :129 |
| Command validation | `core/verification/command_validator.py` | `CommandValidator.validate_batch` :124 |
| Version parsing | `core/verification/version_parser.py` | `parse_show_version` :92 |
| Risk scoring | `core/self_healing_engine.py` | `risk_score` :79 |
| Approval (autonomous) | `core/self_healing_engine.py` | `approval_workflow` :84 |
| Approval (monitor) | `core/autonomous_monitor.py` | `pending_approvals` :74 |
| Deployment | `app.py` | `ConnectHandler.send_config_set` :2500 |
| Verification | `core/intelligence/outcome_contract.py` | `enforce` :224 |
| Rollback build | `core/ai_config.py` | `_finalize_rollback_plan` :143 |
| Workflow tracking | `core/workflow_tracker.py` | `WorkflowTracker` :138 |
| Twin simulation | `core/orchestration_engine.py` | `simulate_change_impact` :674 |
| Autonomy gate (defined) | `core/orchestration_engine.py` | `authorize_change` :812 |
| Decision engine (defined) | `core/orchestration_engine.py` | `deliberate` :838 |

---

## 1. Configuration Generation

- **Entry:** `generate_config(request, device, ai_call, device_facts, fleet_context,
  inventory_summary)` (`core/ai_config.py:383`).
- **Two generators, proven ordering:**
  1. **Deterministic** — if `parse_intent(request).features ⊆ template features`, compile via
     `config_synthesis` and return `status="ok"`, `risk="low"`, `deterministic=True`
     (`ai_config.py:423–448`).
  2. **LLM** — otherwise `ai_call(build_prompt(...))` (`:453`) → `_parse_json` (`:463`).
- **Output dict:** `status, commands, rollback, verify, risk, summary, assumptions, blocked,
  reasons, raw` (`:401`, `:404–407`).

## 2. Decision Logic

Proven branch set inside `generate_config`:
| Condition | Result | Line |
|---|---|---|
| `not ai_call` | `status="unavailable"` | `:410` |
| `not request.strip()` | `status="empty"` | `:413` |
| features ⊆ templates | `status="ok"` (deterministic) | `:431–448` |
| `ai_call` raises | `reasons=[AI call error]`, return | `:472–475` |
| `not cmds` after parse | `status="empty"` | `:506` |
| `validate_config` fails | `status="unsafe"` | `:519` |
| otherwise | `status="ok"` | `:524` |

Intent classification (separate path): `IntentEngine._classify(query)` (`core/intent_engine.py:658`)
returns `INTENT_CONFIG` vs diagnostic (`:674`). This is **rule-based** (keyword matching in the
function body). The branch `if intent == INTENT_CONFIG` drives config vs diagnostic
(`:214`, `:317`).

## 3. Dependency Validation

`KnowledgeGraph.get_dependencies(node_id)` (`core/knowledge_graph.py:55`) and `trace_impact_chain`
(`:74`) exist. **No call to these from the configuration-generation or deploy path was found**
(grep across `app.py`, `core/ai_config.py`, `core/network_fixer.py`, `core/autonomous_monitor.py`).
→ **Dependency validation as a config decision gate: Not found in repository.**

## 4. Evidence Validation

- **Post-deployment (proven):** `OutcomeContractEngine.enforce` (`outcome_contract.py:224`) runs real
  `run_command` outputs, fetches `show running-config`/`show startup-config`, and judges via
  `interpret` (`:174`); `Verdict` enum includes `PENDING`/`UNKNOWN` for unproven evidence.
- **Pre-deployment:** the only evidence handling is a **prompt note**, not a gate —
  `build_prompt` inserts `"(No live CLI data — use Login on this device first …)"`
  (`ai_config.py:363`) when `device_facts` is empty. Generation still proceeds.
→ Evidence validation exists **after** deploy; a pre-deploy “missing evidence” decision is
  **Not found in repository.**

## 5. Risk Scoring

- **Self-healing path (proven, rule-based):** `SelfHealingEngine.risk_score(incident)`
  (`self_healing_engine.py:79`) maps severity string → int: `{low:20, medium:50, high:75,
  critical:95}` (`:81`).
- **Config-generation path:** `out["risk"] = str(data.get("risk","unknown"))`
  (`ai_config.py:486`) — the risk label is **taken from the LLM JSON**, not computed; the
  deterministic branch hard-codes `out["risk"]="low"` (`:438`).
→ A computed risk score for LLM-generated config is **Not found in repository** (it is asserted).

## 6. Confidence Scoring

- **Defined but not in the config path:** `Conclusion.confidence` (`reasoning.py:54`),
  `Judgment.confidence` (decision engine), forecasting `Forecast.probability`.
- The config-generation/deploy path contains **no confidence value and no confidence threshold**.
  `recovery_confidence` (`app.py:99`, `autonomous_monitor`) is an integer **counter** of recoveries,
  not a decision input.
→ Confidence scoring as a configuration decision gate: **Not found in repository.**

## 7. Approval Workflow

- **Admin path (proven, two-stage, manual):** `st.button("🔍 Generate & Preview (no changes yet)")`
  (`app.py:1952`) then a separate `st.button("⚡ Apply to Router")` (`app.py:2059`). Config is
  previewed before any apply.
- **Autonomous path (proven):** `AutonomousMonitor` holds `pending_approvals` (`:74`) and
  `approved_run_ids` (`:77`); Phase 1 stores a run in `pending_approvals` (`:346`) and waits;
  Phase 2 executes only for approved run ids (`:111–113`).
- **Self-healing (proven):** `approval_workflow(action, approver)` (`self_healing_engine.py:84`):
  `approved = action.risk != "high" or approver is not None` (`:85`); `validate_remediation`
  (`:99`): returns `False` if `risk=="high" and device.status != "healthy"` (`:100`).

## 8. Simulation

- **Available, not gating:** `DigitalTwinEngine.simulate_change` (`digital_twin_engine.py:64`) is
  reachable only through `OperationsOrchestrator.simulate_change_impact` (`orchestration_engine.py:
  674–675`). **No caller of `simulate_change_impact` exists in the deploy/fix/config path**
  (grep across `app.py`, `network_fixer.py`, `autonomous_monitor.py`).
- `NetworkFixer.fix` explicitly states **“live connection required — no simulated fallback”**
  (`network_fixer.py`, body of `fix` :162; error returned when no connection).
- The admin “Ran in SIMULATION (no live tunnel)” message (`app.py:2080`) denotes a **connection
  fallback** (no live tunnel), not a digital-twin simulation.
→ A “simulation required before deploy” decision is **Not found in repository.**

## 9. Rollback

- **Build:** rollback comes from the LLM JSON `data.get("rollback")` (`ai_config.py:497`), finalized
  by `_finalize_rollback_plan(cmds, rollback, explanation)` (`:143`, called `:521`) only when
  `mode=="config"` (`:520`); deterministic branch derives `"no " + c` per command (`:441`).
- **Safety:** `validate_rollback` (`:129`) blocks `ROLLBACK_DENY_PATTERNS`.
- **Execution:** copilot rollback runs `ConnectHandler.send_config_set(_rb_lines)` (copilot block).

## 10. Deployment

- **Entry (proven):** `netmiko.ConnectHandler(**cfg)` then `send_config_set(_cfgc, cmd_verify=False,
  read_timeout=60)` (`app.py:2500`), `save_config()` (`:2515`). Copilot deploys per device on
  `DEPLOY_DEVICE:` markers (copilot block, `ConnectHandler` rel `:659/668`).
- **Precondition:** a live netmiko connection; otherwise error/sim message (`app.py:2080`).

## 11. Verification

(Investigation 2 §19.) `OutcomeContractEngine.enforce` (`outcome_contract.py:224`):
`derive_post_conditions` (`:116`, LLM) → `interpret` (`:174`, deterministic precheck via
`config_synthesis.interface.general_precheck`, then LLM) → re-poll `PENDING`. Output: `ContractResult`.

## 12. Safety Gates

Three proven gates:
1. **`validate_config`** (`ai_config.py:112`) — regex `CONFIG_DENY_PATTERNS` via `_matches_any`
   (`:107`); blocks lockout/destructive/identity changes → `status="unsafe"`.
2. **Prompt-level deny list** — `build_prompt` embeds a literal `SAFETY (hard deny …)` section
   (`ai_config.py:374–381`): no VTY ACLs, AAA/hostname/credential changes, reload/erase, etc.
3. **`CommandValidator`** (`command_validator.py:116`) — `is_deployable` (`:85`), `all_safe`
   (`:96`), `has_blocked` (`:100`); invoked in the **IntentEngine** fix path only
   (`intent_engine.py:1043/1074`), **not** in the admin `generate_config` deploy path.
> The defined autonomy gate `authorize_change` (`orchestration_engine.py:812`) and decision gate
> `deliberate` (`:838`) have **no callers** in the deploy/fix path (grep) → those gates are **defined
> but not wired** → **Not found in repository** as active config gates.

## 13. Command Generation

- **Deterministic:** `ConfigSynthesizer.synthesize` (`synthesizer.py:85`) → templates
  (`templates.py`, Cisco IOS DNS/NTP/clock). **LLM:** `generate_config` LLM branch (`ai_config.py:
  453`). Commands normalized into `out["commands"]` (`:480`).

## 14. Vendor Abstraction

- **Vendor enum:** `Vendor` = `CISCO_IOS, CISCO_NXOS, ARISTA_EOS, JUNIPER_JUNOS, GENERIC`
  (`config_synthesis/base.py`).
- **Default:** synthesis defaults `vendor=Vendor.CISCO_IOS.value` (`synthesizer.py:87`,
  `engine.py:54`); `generate_config` does not pass a vendor, so the deterministic path is always
  Cisco IOS. **Templates implement Cisco IOS only** (Investigation 3 §9).
- **Vendor detection (exists, separate):** `device_inventory_meta.detect_oem_and_type` (`:159`),
  `parse_show_version` (`version_parser.py:92`) returns `DeviceVersion.vendor` (used in
  `intent_engine.py` at `:1053`, skipping when `vendor=="unknown"`).
→ Vendor *detection* exists; a vendor-specific abstraction for command generation beyond Cisco IOS
  is **Not found in repository.**

## 15. Command Validation

- `CommandValidator.validate_batch(commands, version)` (`command_validator.py:124`),
  `validate_one` (`:135`); results `ValidationResult.all_safe`/`has_blocked` (`:96/100`),
  `CommandValidation.is_deployable` (`:85`). Version-aware via `parse_show_version`
  (`version_parser.py:92`), `compare_versions` (`:127`).
- **Call site (proven):** only `IntentEngine` validates fix commands against device version
  (`intent_engine.py:1043` `get_validator()`, `:1074` `validate_batch(fix_commands,
  primary_version)`). The admin `generate_config` deploy path uses `validate_config`
  (`ai_config.py:112`) instead.

## 16. Workflow Tracking

- `WorkflowTracker` (`workflow_tracker.py:138`), `create_run` (`:149`); `WorkflowRun` (`:86`) of
  `WorkflowStep` (`:31`) with `StepStatus` = `PENDING, RUNNING, COMPLETED, FAILED, SKIPPED`
  (`:14–18`). Driven by `AutonomousMonitor` (`tracker.step_log`, `autonomous_monitor.py:264`).

---

# Can the system decide …?

| Decision | Verdict | Evidence |
|---|---|---|
| **Need More Information** | **Partial / Not in config gen** | Config gen never returns a need-info status; only a prompt note `"(No live CLI data …)"` (`ai_config.py:363`). The closest decision is `IntentEngine`’s `"Please clarify your question"` for skipped devices (`intent_engine.py:598`) — diagnostic path, not config. |
| **Unsafe Configuration** | **Yes** | `validate_config` → `status="unsafe"` (`ai_config.py:112/519`); UI branch `elif status=="unsafe"` (`app.py:2086`); `CommandValidator.has_blocked` (`command_validator.py:100`) in intent path. |
| **Missing Dependencies** | **No** | `KnowledgeGraph.get_dependencies` exists (`knowledge_graph.py:55`) but is **not called** in any config/deploy path. **Not found in repository.** |
| **Missing Evidence** | **Post-deploy only** | `OutcomeContractEngine` returns `PENDING/UNKNOWN` (`outcome_contract.py`); pre-deploy is a note only (`ai_config.py:363`). A pre-deploy missing-evidence decision is **Not found in repository.** |
| **Simulation Required** | **No** | `simulate_change` reachable only via `simulate_change_impact` (`orchestration_engine.py:674`) with **no deploy-path caller**; `NetworkFixer.fix` has “no simulated fallback”. **Not found in repository.** |
| **Human Approval Required** | **Yes** | Admin two-stage buttons (`app.py:1952` preview, `:2059` apply); `pending_approvals`/`approved_run_ids` (`autonomous_monitor.py:74/77`); `approval_workflow` high-risk rule (`self_healing_engine.py:85`). |
| **Confidence Too Low** | **No** | No confidence value or threshold in the config/deploy path; `recovery_confidence` is a counter (`app.py:99`); decision engine `requires_human` exists but `deliberate` is uncalled. **Not found in repository.** |
| **Unknown Topology** | **No** | No topology-completeness gate before config generation found (grep). **Not found in repository.** |
| **Unknown Vendor** | **Partial / detection only** | Detection exists: `parse_show_version`→`vendor` with `"unknown"` skip (`intent_engine.py:1053`), `is_recognized_network_vendor` (`device_inventory_meta.py:215`). Config gen does **not** refuse on unknown vendor — it defaults to Cisco IOS (`synthesizer.py:87`). A refusal decision is **Not found in repository.** |
| **Unknown Interface** | **No** | `config_synthesis.interface` normalizes names but no check that an interface exists on the device before config. **Not found in repository.** |

---

# Every location where the AI could generate configuration using assumptions instead of verified facts

All proven from source:

1. **`build_prompt` with empty `device_facts`** (`ai_config.py:363`): substitutes
   `"(No live CLI data …)"` yet generation proceeds — config can be produced with **no device facts**.
2. **`NETBRAIN_ENGINE_PREAMBLE` instruction** (`ai_config.py:205`): the system prompt explicitly
   directs *“Infer reasonable assumptions from topology — never ask for data already supplied.”*
3. **LLM generation branch** (`ai_config.py:453`): `ai_call(build_prompt(...))` has **no
   precondition** that `device_facts` be non-empty or verified.
4. **`out["assumptions"]` field** (`ai_config.py:482`): the model is allowed to return assumptions,
   which are surfaced but not verified before apply.
5. **`out["risk"]` from the model** (`ai_config.py:486`): risk is the LLM’s assertion, not a
   verified computation.
6. **Vendor assumption** (`synthesizer.py:87`, `engine.py:54`): deterministic synthesis defaults to
   `Vendor.CISCO_IOS` when no vendor is supplied; `generate_config` never passes a verified vendor.
7. **Environment assumption** (`config_synthesis/engine.py:31` `_default_environment`): defaults to
   `isolated=True` unless `NETBRAIN_ENV_ISOLATED` says otherwise — an assumed environment.
8. **Default server values** (`config_synthesis/base.py` `CANONICAL_PUBLIC_DNS`,
   `CANONICAL_PUBLIC_NTP`): used when none provided — assumed (deterministic) values.
9. **LLM-authored verification** (`outcome_contract.py:116` `derive_post_conditions`): the checks
   themselves are generated by the model — an assumption about what constitutes success.
10. **LLM planning** (`intent_engine.py:419` `_ai_generate_plan`, `:604`
    `_build_deep_analysis_prompt`): plans/analysis are model-generated text.

---

## Honesty ledger (explicitly NOT proven)

- A pre-deployment gate that blocks on missing facts/evidence/dependencies/confidence/topology →
  **Not found in repository.**
- Wiring of `authorize_change`/`deliberate`/`simulate_change_impact` into the deploy path →
  **Not found in repository** (methods defined, no callers in that path).
- Full bodies of `CommandValidator.validate_one`, `_finalize_rollback_plan`, and the LLM-branch tail
  of `generate_config` beyond cited lines were not extracted line-by-line; entry/exit and the cited
  branches are proven, deeper internals are not asserted.
