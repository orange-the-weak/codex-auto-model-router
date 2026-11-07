# Routing profiles

The profile workflow is adapted from David Soff's PR #6; the optional prompt hook comes from his PR #4. Integration preserves the reviewed catalog, explicit model pins, fallback dispatch safety, and the historical GPT-5.6 programmatic policy API.

## Commands and scope

Run commands from the installed Skill directory, or use absolute script paths:

```bash
python3 scripts/router_lite.py profile-show --repository /path/to/project
python3 scripts/router_lite.py profile-set economy --scope project --repository /path/to/project
python3 scripts/router_lite.py profile-set balanced --scope global --repository /path/to/project
python3 scripts/router_lite.py decide --profile quality --repository /path/to/project
```

Global configuration lives in `${CODEX_HOME:-$HOME/.codex}/router.toml`; project configuration lives in `<repository>/.codex/router.toml`. Profile selection is command-line > project > global > balanced. Route overrides for the selected profile are built-in < global < project. Explicit model/effort arguments override profile routes. A model-only argument does not authorize high Astra effort.

`profile-set` changes only the selected scope, preserves existing comments and route overrides, and uses atomic replacement. Invalid configuration is rejected without rewriting it. Lite routing fails open to local execution; strict CLI reports configuration errors. Lite and strict routing check project opt-out before loading profiles. Profile commands do not re-enable a disabled project.

## One decision pipeline

1. Project opt-out runs before configuration or routing.
2. `route_policy.py` classifies task signals; `routing_profiles.py` is the single source of current model/effort defaults and user lane overrides.
3. The shared policy applies explicit user model/effort arguments and Astra's automatic low/medium guard. Lite does not map an old GPT-5.6 recommendation into a second model choice.
4. `model_catalog.py` resolves availability. Explicit model pins cannot silently fall back. Sol 6.1 prefers Sol 6, then Sol 5.6 before an Astra availability fallback; Astra's effort guard still applies.
5. `router_lite.py` chooses local execution, delegate, reuse, or tool concurrency using the executable route and overhead gate. A preferred model never changes the coordinator's active model.

These are separate concerns: profile selection is not model availability, and a model recommendation is not permission to bypass execution constraints. Existing global/project profile selections and custom overrides are never rewritten by a policy update.

Migration: the Sol-first update changes the built-in tables, so saved profile names inherit these new defaults unless a lane is explicitly overridden. No settings file is migrated automatically. Existing frozen strict plans keep their recorded routes; recreate a plan to use the new policy.

## Built-in profiles

| Profile | Difference from balanced |
|---|---|
| balanced | GPT-6.1 Sol first for ordinary and complex project work; Luna only for mechanical tasks. |
| economy | Uses Luna for ordinary work and scans, but keeps Sol for complexity, uncertainty, and high consequence. |
| quality | Uses higher Sol efforts for selected lanes; does not automatically use Astra for task difficulty alone. |

| Lane | economy | balanced (default) | quality |
|---|---|---|---|
| Mechanical | Luna/medium | Luna/medium | Luna/medium |
| Ordinary | Luna/high | Sol 6.1/medium | Sol 6.1/high |
| Bounded scan | Luna/xhigh | Sol 6.1/high | Sol 6.1/high |
| Deterministic deep work | Luna/max | Sol 6.1/high | Sol 6.1/xhigh |
| Latency priority | Luna/high | Sol 6.1/low | Sol 6.1/low |
| Bounded complex | Sol 6.1/medium | Sol 6.1/medium | Sol 6.1/high |
| Uncertain / high consequence | Sol 6.1/high | Sol 6.1/high | Sol 6.1/xhigh |
| Failed complex reasoning/verification | Astra/medium | Astra/medium | Astra/medium |
| Explicit bounded specialist focus | Terra 6.1/medium | Terra 6.1/medium | Terra 6.1/high |

The matrix is a maintained project preference, not a benchmark-equivalence or measured speed claim. GPT-6.1 Sol is the strong role, GPT-6.1 Terra the specialist, GPT-6 Luna the efficient role, and Astra the frontier escalation role. GPT-6 Sol / GPT-5.6 remain fallback or explicit compatibility options; no automatic task-type rule prefers them over GPT-6.1 Sol.

## Terra specialist focus

```bash
python3 scripts/router_lite.py decide --task-focus visual --repository /path/to/project
python3 scripts/router_lite.py decide --task-focus writing --repository /path/to/project
python3 scripts/router_lite.py decide --model gpt-6.1-terra --effort medium --repository /path/to/project
```

`task_focus` is `general` (default), `visual`, `computer_use`, `writing`, or `scoped_fix`. Use it only for actual focused work with clear acceptance criteria: interpreting a chart, a bounded screen workflow, rewriting supplied material, or a localized fix. Generic UI implementation is not automatically a computer-use task. `task_kind=complex`, high ambiguity/coupling/consequence, or any prior failure prevents the specialist lane; the ordinary Sol/Astra rules then apply. Explicit model/effort arguments still win. Task focus grants no new authority for tools, messages, or other external actions.

Lite JSON tasks and strict JSON segments accept the same `task_focus`; strict capsules preserve it and different focuses are not merged. Legacy unconfigured APIs and `--model-policy legacy` ignore its routing preference but reject invalid focus names. Terra falls back to GPT-6.1 Sol, then GPT-6 Sol, then legacy Terra when availability is complete; explicit Terra pins never silently substitute another model. Availability is never inferred from an API listing or a preset file.

Router presets intentionally expose only low/medium/high/xhigh/max, even though official API docs also list `none` for Terra and Luna. No native Ultra preset is added. The host must expose the named model or generated preset before execution; installing this catalog does not prove entitlement or tool availability.

Task difficulty alone no longer selects Astra in built-ins. Astra defaults to low for a model-only pin or availability fallback; classified complex reasoning/verification failure may select medium. Infrastructure and unclassified failures do not trigger that lane. This is task-signal classification, not independently verified execution-log evidence. Astra high, xhigh, or max requires an explicit effort argument or an explicit configured lane override. Available-model checks and fallback routing still apply; a configured lane is not proof that the model executed.

## Lane overrides

```toml
schema_version = 1
profile = "balanced"

[profiles.balanced.routes.complex_uncertain]
model = "gpt-6-astra"
effort = "low"
```

Valid lanes: `mechanical_default`, `ordinary_default`, `bounded_scan`, `bounded_deep_deterministic`, `latency_priority`, `complex_bounded`, `complex_uncertain`, `high_consequence`, `complex_failed_escalation`, `specialist_default`. Each override requires both `model` and `effort`; only reviewed catalog/legacy model IDs and low-through-max efforts are accepted. Unknown keys, profiles, lanes, or unsupported efforts are errors. Overrides do not edit the model catalog or executor presets.

Strict CLI uses the same resolved profile. Programmatic `route_policy` APIs retain legacy defaults unless passed a `routing_config` from `resolve_routing_config`. Configured Assess/Retune use the catalog's strong model (currently GPT-6.1 Sol)/high; legacy callers retain GPT-5.6 Sol/high. `--model-policy legacy` preserves old Lite recommendations, including Terra's historical latency lane. Linear and parallel plans capture the selected routes once; later config changes cannot mutate an existing plan. Historical benchmark tables remain unchanged.

## Optional prompt hook

Install with `./install.sh --install-hook` or `./install.ps1 -InstallHook`, review/trust with `/hooks`, and restart Codex. Ordinary installation does not enable it. The hook adds a short routing reminder only when the Skill is installed and the project has not opted out; it does not include the user's prompt in its output, change the active model, or spawn an executor itself. Unrelated hooks are preserved, reinstall is idempotent, and installer failure rolls back the hook configuration along with the Skill payload.
