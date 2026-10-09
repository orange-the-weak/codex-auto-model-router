# Routing profiles

The profile workflow is adapted from David Soff's PR #6; the optional prompt hook comes from his PR #4. Integration preserves the reviewed catalog, explicit model pins, fallback dispatch safety, and the historical GPT-5.6 programmatic policy API.

## Commands and scope

Run commands from the installed Skill directory, or use absolute script paths:

```bash
python3 scripts/router_lite.py profile-show --repository /path/to/project
python3 scripts/router_lite.py profile-set economy --scope project --repository /path/to/project
python3 scripts/router_lite.py profile-set balanced --scope global --repository /path/to/project
python3 scripts/router_lite.py decide --profile quality --repository /path/to/project
python3 scripts/router_lite.py profile-set plus --scope project --repository /path/to/project
python3 scripts/router_lite.py profile-set pro --scope global --repository /path/to/project
```

Global configuration lives in `${CODEX_HOME:-$HOME/.codex}/router.toml`; project configuration lives in `<repository>/.codex/router.toml`. Profile selection is command-line > project > global > balanced. Route overrides for the selected profile are built-in < global < project. Explicit model/effort arguments override profile routes. A model-only argument does not authorize high Astra effort.

`profile-set` changes only the selected scope, preserves existing comments and route overrides, and uses atomic replacement. Invalid configuration is rejected without rewriting it. Lite routing fails open to local execution; strict CLI reports configuration errors. Lite and strict routing check project opt-out before loading profiles. Profile commands do not re-enable a disabled project.

Only explicit user selection enables `plus` or `pro`. Their names describe routing preferences, not detected subscriptions, enforced service tiers, or promised model access. Account information, entitlements, environment plan hints, and available models never select a profile. A saved selection persists until explicitly changed. `decide --profile ...` and `plan --profile ...` override that invocation without changing either config file. Installation neither chooses a plan profile nor overwrites an existing selection.

## Built-in profiles

| Profile | Difference from balanced |
|---|---|
| balanced | Existing default routes: Luna for bounded work, Sol for bounded complexity, Astra for uncertainty/high consequence. |
| economy | Uses Luna/high for complex bounded and complex uncertain tasks; preserves the high-consequence and failure lanes. |
| quality | Uses Sol for ordinary work and deterministic scans; does not automatically increase Astra effort. |
| plus | Luna/high for light mechanical work, Luna/xhigh by default, then GPT-6.1 Sol/high and xhigh; no automatic Astra. |
| pro | Same Luna tiers, a task-based GPT-5.6 Sol/xhigh or GPT-6.1 Sol/xhigh branch, then narrowly gated Astra/xhigh. |

The three existing profiles use Astra/low, with medium reserved for reasoning/verification failure escalation. They are unchanged. Astra high, xhigh, or max requires an explicit effort argument or an explicit configured lane override, except for the explicitly selected Pro top tier below. A model-only Astra override still defaults to low. Available-model checks and fallback routing still apply; a configured lane is not proof that the model executed.

## Optional Plus and Pro policies

| Lane | Plus | Pro |
|---|---|---|
| mechanical_default | GPT-6 Luna/high | GPT-6 Luna/high |
| ordinary_default, bounded_scan, bounded_deep_deterministic, latency_priority | GPT-6 Luna/xhigh | GPT-6 Luna/xhigh |
| complex_bounded | GPT-6.1 Sol/high | GPT-5.6 Sol/xhigh |
| complex_uncertain | GPT-6.1 Sol/xhigh | GPT-6.1 Sol/xhigh |
| high_consequence | GPT-6.1 Sol/xhigh | GPT-6 Astra/xhigh |
| complex_failed_escalation | GPT-6.1 Sol/xhigh | GPT-6 Astra/xhigh |

Lane selection is evidence-gated, not a fixed escalation counter. Existing task signals still distinguish light mechanical work, ordinary work, and work requiring Sol. `--task-subtype` refines the opt-in profiles; it does not change the three existing profiles:

- `general` (default): bounded complex work uses the scoped Sol branch; high ambiguity/coupling or large complex work uses the deep Sol branch in Pro. Ordinary bounded scans remain on Luna unless stronger signals justify Sol.
- `scoped_implementation`, `existing_iteration`, `ui`, `careful_maintenance`: complex work uses Pro's GPT-5.6 Sol/xhigh branch. Merely labeling an ordinary task this way does not promote it from Luna.
- `large_repo`, `autonomous_investigation`, `complex_planning`, `deep_multi_module`: work actually requiring these scopes uses GPT-6.1 Sol/xhigh in both profiles. Do not classify a tiny edit as `large_repo` merely because its repository is large.
- `extreme`: reserved for genuinely extreme tasks. Pro may use Astra/xhigh immediately; Plus stops at Sol/xhigh. High consequence likewise selects the top profile lane. As in existing policy, `risk=high` implies high consequence; a conflicting low/normal consequence is rejected.

For Pro, ordinary complexity, ambiguity, or size alone must not trigger Astra. Escalation through failure requires all of: `prior_failure=true`, `prior_failure_kind=reasoning|verification`, `prior_failure_model` matching the corresponding Sol branch for this task, and `prior_failure_effort=xhigh`. Model and effort are observed executor settings for the actual failed attempt, not a cached recommendation. Failure of GPT-5.6 Sol/xhigh on a scoped task, or GPT-6.1 Sol/xhigh on a deep task, qualifies. Missing/wrong model or effort evidence, the other Sol branch, lower-effort Sol, Luna failure, unknown failure, and infrastructure/authentication/tool/startup failures do not qualify. A substantive Luna failure can promote to the appropriate Sol branch. Plus stays within its two Sol tiers.

```bash
# Scoped complex implementation: GPT-5.6 Sol/xhigh
python3 scripts/router_lite.py decide --profile pro --task-kind complex --task-subtype scoped_implementation
# Deep investigation: GPT-6.1 Sol/xhigh
python3 scripts/router_lite.py decide --profile pro --task-subtype autonomous_investigation
# Verified substantive failure of the matching branch: Astra/xhigh
python3 scripts/router_lite.py decide --profile pro --task-kind complex --task-subtype ui \
  --prior-failure --prior-failure-kind verification --prior-failure-model gpt-5.6-sol --prior-failure-effort xhigh
```

Pro has no intermediate Astra medium/high step. Explicitly selecting it opts into potentially substantially higher budget use; `profile-set`, `profile-show`, and decisions expose the budget warning. Existing explicit model/effort and configured lane overrides retain precedence, including an explicit Astra choice in Plus. No effort above xhigh is automatic in these two profiles.

Availability is never escalation evidence: neither Plus nor Pro may fall back from Luna/Sol to Astra. If no permitted model is available, Lite stays local and reports the limitation. An eligible Pro Astra recommendation can fall back to a supported Sol model at xhigh and reports quality degradation. Explicit model pins never silently substitute. The coordinator remains fixed, so these are recommendation and leaf-dispatch policies; an already-running Astra coordinator may still execute locally.

JSON tasks and strict plan segments accept `task_subtype`, `prior_failure_model`, and `prior_failure_effort` with the same meanings as the CLI. Strict plans and capsules freeze this evidence and profile identity, and runtime fallback checks preserve the no-Astra-promotion restriction. Generated/cached report routes, including per-segment `route_source=report`, are advisory and are reclassified under Plus/Pro; they are not explicit user pins. Changing config does not mutate an already-created plan; a new `decide`/`plan` resolves the latest selection before considering reuse. Reuse still requires an exact model/effort match and all existing safety checks; extreme/high-consequence work and prior failures exclude reuse.

## Lane overrides

```toml
schema_version = 1
profile = "balanced"

[profiles.balanced.routes.complex_uncertain]
model = "gpt-6-astra"
effort = "low"
```

Valid lanes: `mechanical_default`, `ordinary_default`, `bounded_scan`, `bounded_deep_deterministic`, `latency_priority`, `complex_bounded`, `complex_uncertain`, `high_consequence`, `complex_failed_escalation`. Each override requires both `model` and `effort`; only reviewed catalog/legacy model IDs and low-through-max efforts are accepted. Unknown keys, profiles, lanes, or unsupported efforts are errors. Overrides do not edit the model catalog or executor presets.

Strict CLI uses the same resolved profile. Programmatic `route_policy` APIs retain legacy defaults unless passed a `routing_config` from `resolve_routing_config`. Linear and parallel plans capture the selected routes once; later config changes cannot mutate an existing plan. Historical benchmark tables remain unchanged.

## Optional prompt hook

Install with `./install.sh --install-hook` or `./install.ps1 -InstallHook`, review/trust with `/hooks`, and restart Codex. Ordinary installation does not enable it. The hook adds a short routing reminder only when the Skill is installed and the project has not opted out; it does not include the user's prompt in its output, change the active model, or spawn an executor itself. Unrelated hooks are preserved, reinstall is idempotent, and installer failure rolls back the hook configuration along with the Skill payload.
