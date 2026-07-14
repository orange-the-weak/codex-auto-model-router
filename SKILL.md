---
name: codex-model-router
description: Analyze, apply, and tune project model routing inside Codex, use native same-task model and reasoning overrides when available, use a local fast path for usage queries and records, save a Markdown report, and persist validated per-model history. Prefer GPT-5.6 Sol medium for normal assessment, allow Sol, Terra, Luna and low, medium, high, or xhigh overrides, execute routed task segments in the same Codex task, adjust effort to difficulty, and fall back honestly when a route is unavailable. Use when the user asks which model should handle project tasks, invokes the skill with implementation work, queries actual or recommended usage proportions, records outcomes, retunes assignments from history, or wants a speed-first routing plan. Invoking this skill authorizes same-task routed continuations and dedicated report and history writes, never a new top-level task.
---

# Route Project Models

Use Codex's native same-task continuation with explicit `model` and `thinking` overrides for Assess, Retune, and routed Apply work. Handle Query and Record deterministically with the bundled ledger script so routine calls are fast. Use a named custom agent only when the available spawn tool has an explicit agent/preset selector; a matching task name alone is not proof that its TOML was applied. Save a complete report and minimal project-local ledger, then return only a concise, efficiency-focused summary. Do not create a top-level Codex task, add API integration, estimate API spend, edit unrelated configuration, or implement project code unless the same invocation requests implementation.

## Path dispatch

Choose exactly one path before doing any work:

- If the prompt contains `ROUTE_PROJECT_MODELS_EXECUTOR=1`, use only the bounded executor path in Routed execution.
- If the prompt contains `ROUTE_PROJECT_MODELS_ROUTED_TURN=1`, use only the same-task routed-turn path specified in that prompt.
- Otherwise, if it contains `ROUTE_PROJECT_MODELS_SUBAGENT=1`, use only the read-only router Subagent path.
- Otherwise, act as the coordinator below.

## Coordinator path

With neither recursion marker present, act only as the coordinator:

1. Do not perform repository assessment or routed implementation before applying the selected route. Dispatch it as a same-task continuation with explicit model metadata. The coordinator may read the routing report, inspect results or diffs, run proportionate verification, and maintain the ledger.
2. Select one mode:
   - **Assess:** when the user asks to analyze, plan, classify, or refresh repository routing without requesting implementation.
   - **Apply:** when the same skill invocation asks to build, change, fix, refactor, test, review, or otherwise execute project work. A prompt containing both routing and implementation is Apply, not Assess-only.
   - **Query:** when the user asks for usage, ratios, history, or current allocation. Read the existing report and ledger; avoid a broad repository scan.
   - **Record:** when the user supplies a completed task's model, effort, outcome, or duration. Validate and append it, then summarize current proportions.
   - **Retune:** when the user asks to adjust or optimize assignments. Compare actual history with the current recommendation and inspect only evidence needed to revise it.
3. For Query or Record, use the fast path and do not spawn an agent:
   - Before running the local fast path, show one concise commentary line: `Codex 自动路由｜任务段：<task segment>｜模型：local-script｜推理：none｜<reason>`.
   - First record the invocation as `skill_run` with `analysis_model=local-script` and `effort=none`.
   - Query: run `summary`, then `render` to update only the marked report section.
   - Record: append the user-confirmed execution with `record`, then run `summary` and `render`.
   - Return actual model and model-effort ratios, sample status, latest recommendation, and report link. Stop this coordinator workflow here.
4. For Assess, Retune, or Apply, parse optional choices from the user's invocation:
   - Model: case-insensitive `Sol`, `GPT-5.6`, `GPT-5.6 Sol`, `Terra`, or `Luna`, including `模型=Terra` and `用 Luna 分析`.
   - Reasoning: `low`, `medium`, `high`, or `xhigh`; map `very high` and `extra high` to `xhigh`.
5. Default the analysis model to Sol. Honor an explicit supported model choice.
6. Choose reasoning effort:
   - Honor one explicit supported reasoning choice first.
   - Otherwise use `low` only for a narrowly scoped, low-risk re-assessment with explicit files or boundaries and easy verification.
   - Use `medium` by default for a normal repository assessment.
   - Use `high` for broad or ambiguous scope, several coupled subsystems, or security, privacy, money, production, migration, or data-loss consequences.
   - Use `xhigh` only for an explicitly deep or exhaustive assessment, conflicting prior analyses, or a well-scoped previous assessment that failed. Do not select it merely because the repository is large.
7. Normalize the selected route to the native Codex pair `<model, thinking>`: `gpt-5.6-sol`, `gpt-5.6-terra`, or `gpt-5.6-luna`, plus `low`, `medium`, `high`, or `xhigh`. The custom preset mapping below is a secondary compatibility path only:

| Model | low | medium | high | xhigh |
|---|---|---|---|---|
| Sol | `project_model_router_low` | `project_model_router` | `project_model_router_high` | `project_model_router_xhigh` |
| Terra | `project_model_router_terra_low` | `project_model_router_terra` | `project_model_router_terra_high` | `project_model_router_terra_xhigh` |
| Luna | `project_model_router_luna_low` | `project_model_router_luna` | `project_model_router_luna_high` | `project_model_router_luna_xhigh` |

8. If the user names multiple conflicting models, multiple conflicting efforts, or an unsupported value, ask for one supported value instead of guessing.
9. For Assess or Retune, before dispatching, show one concise commentary line in the current Codex conversation: `Codex 自动路由｜任务段：<task segment>｜模型：<model>｜推理：<effort>｜<short reason>`.
10. In Codex Desktop, identify the current active thread with the thread-list capability, then send a follow-up to that same thread with the selected native `model` and `thinking`. Never call the thread-creation capability. Pass a prompt containing:
   - `ROUTE_PROJECT_MODELS_ROUTED_TURN=1`
   - `ROUTED_MODE=ASSESS` or `ROUTED_MODE=RETUNE`
   - the repository path and any scope supplied by the user
   - the selected analysis model and reasoning effort
   - the selected mode
   - the reason for any automatic effort choice
   - paths to the existing report and ledger when present
   - an instruction to read this skill, complete the routed turn without delegation, save the report, update the ledger, and return the concise summary
11. End the coordinator turn after the same-thread follow-up is accepted. The routed turn completes the work in the same Codex task. If same-thread model override is unavailable, use a subagent only when its tool explicitly accepts a model or named-agent selector. Never assume a generic subagent's task name changes its model.
12. The routed Assess or Retune turn saves its complete Markdown report:
   - Default to `<repository>/docs/codex-model-routing-report.md`.
   - Follow an applicable repository instruction if it requires a different documentation or report directory.
   - Create the parent directory when needed and update this dedicated generated report if it already exists.
13. The routed turn maintains `<repository>/.codex/model-routing-history.jsonl` using `scripts/model_usage_ledger.py` and [usage-ledger.md](references/usage-ledger.md):
   - Record each skill run separately from follow-on execution usage.
   - Append actual execution only when the model is visible in reliable task metadata or the user explicitly supplies it.
   - Append the latest recommended allocation after Assess or Retune.
   - Never infer actual usage from a routing recommendation.
   - Preserve exact fallback model names when known and the fallback reason.
   - When a follow-on execution is completed inside the current observable task, append its confirmed model, effort, task class, outcome, and optional duration before returning.
   - Run `render` after each write; never ask a model to rewrite the usage section.
14. For Apply, follow the Routed execution section after obtaining a usable routing report.
15. Return a short summary in the current task, not the full table. Include only:
   - the recommended default execution model and effort
   - two or three highest-impact efficiency optimizations
   - `预计增效：约 X–Y%`, its comparison baseline, and whether it is heuristic or measured
   - the analysis model and effort in one short line
   - an absolute clickable link to the complete report
   - for Query or Retune, actual and recommended model proportions as separate values

Keep the chat response to about six bullets or fewer. Do not duplicate the detailed evidence, routing table, calculation, or gaps from the report.

## Visible routing protocol

Make model routing visible in the current Codex conversation whenever this skill controls a distinct task segment:

- Announce the route immediately before starting repository assessment, retuning, a local Query/Record fast path, or a follow-on segment explicitly coordinated under this skill.
- Use exactly one compact commentary line per segment: `Codex 自动路由｜任务段：<task segment>｜模型：<model>｜推理：<low|medium|high|xhigh|none>｜<reason>`.
- The wording must explicitly identify that Codex selected the route; do not show a bare `路由提示` label that could be mistaken for a user instruction.
- For a multi-segment switching sequence, announce again only when the model or reasoning effort changes, or when the next segment has a materially different responsibility. Do not repeat the line for every command or file.
- Label configured-but-not-yet-verified presets as `配置模型`; do not present them as observed runtime metadata.
- If fallback occurs, immediately show: `回退提示｜原配置：<model/effort>｜实际：<verified model/effort or available-default (unverified)>｜<reason>`.
- If Codex does not expose actual runtime metadata, say `未验证` instead of inferring it. The final summary still reports the configured analysis route and any verified fallback separately.

## Native same-task routing

- Prefer the Codex thread follow-up capability because it accepts explicit `model` and `thinking` fields and keeps work in the current task.
- Resolve the current thread from active thread metadata; do not guess among multiple active threads with the same repository.
- A successful same-thread dispatch validates that the host accepted the requested model/effort combination. Still label runtime identity as unverified if execution metadata does not expose it afterward.
- Never use the thread-creation capability for routing.
- Never treat a generic subagent name as a model switch. Use a custom preset only when the spawn interface explicitly selects that preset or model.
- When the same-thread capability is absent and no explicit model-selectable internal agent exists, report that automatic switching cannot be guaranteed on that Codex surface; provide the recommendation without pretending it ran.

## Routed execution

Apply mode makes the routing plan operational for implementation requested in the same skill invocation:

1. Read `docs/codex-model-routing-report.md` and match the requested work to its task rows, upgrade triggers, and switching sequence.
2. If no report exists, it is materially stale, or it does not cover the requested responsibility, run Assess first and save the refreshed report before implementation.
3. Apply the speed gate before any extra routed turn:
   - If the report covers the responsibility, no major architecture or model-picker change is known, and the request is bounded with an obvious verification path, reuse the report without a new Assess turn.
   - If the request is one bounded responsibility, keep it as one segment. Do not split it merely to demonstrate model switching.
   - For low-risk work, prefer the current task when its available model is already sufficient; a same-task continuation is justified only when the selected model/effort differs materially or the expected quality/risk benefit exceeds one extra turn.
   - Reserve an extra Sol analysis or review turn for ambiguity, cross-subsystem coupling, security/privacy/money/production risk, migration/data-loss risk, or a failed lower-tier attempt.
4. Decompose the request into the fewest independently verifiable task segments that justify distinct routes. Do not split work merely to demonstrate model switching.
5. Assign each segment the report's model and effort. An explicit user override wins for the named segment or, if no segment is named, for the whole Apply request. Never silently replace a user override with the recommendation.
6. Select the native model ID and effort for the segment. Use the matching executor preset below only on a Codex surface whose spawn interface explicitly supports selecting named custom agents:

| Model | low | medium | high | xhigh |
|---|---|---|---|---|
| Sol | `project_model_executor_low` | `project_model_executor` | `project_model_executor_high` | `project_model_executor_xhigh` |
| Terra | `project_model_executor_terra_low` | `project_model_executor_terra` | `project_model_executor_terra_high` | `project_model_executor_terra_xhigh` |
| Luna | `project_model_executor_luna_low` | `project_model_executor_luna` | `project_model_executor_luna_high` | `project_model_executor_luna_xhigh` |

7. Before each segment, show the visible route line. Use the current task for a sufficient low-risk route; otherwise dispatch the segment to the current Codex thread with explicit `model` and `thinking`, marker `ROUTE_PROJECT_MODELS_ROUTED_TURN=1`, and `ROUTED_MODE=APPLY_SEGMENT`. Never create another top-level task.
8. Pass the routed turn the exact segment scope, acceptance criteria, applicable report row, repository path, user override, validation budget, current thread ID, and remaining ordered segments. Instruct it to read applicable `AGENTS.md` files.
9. Run dependent segments one at a time. After a successful segment, the routed turn dispatches the next segment to the same thread with its own explicit model and effort. Stop the chain on failure and report it instead of blindly queuing dependent work.
10. Record a confirmed execution event only when runtime task metadata exposes the route or the user confirms it. Otherwise record the configured route separately without presenting it as actual usage.
11. On failure, diagnose the cause before changing routes. Retry once only when a more capable model or higher effort directly addresses that cause; change one dimension at a time when practical. Show the new route or fallback line before retrying.
12. Do not claim that this routing persists into unrelated future Codex tasks. A later independent task must invoke the skill again, or explicitly ask to continue under the saved routing report.

When the prompt contains `ROUTE_PROJECT_MODELS_EXECUTOR=1` or `ROUTE_PROJECT_MODELS_ROUTED_TURN=1` with `ROUTED_MODE=APPLY_SEGMENT`, execute only the supplied bounded segment. Do not assess routing, delegate, or create another task. Read applicable repository instructions, preserve unrelated changes, implement the segment, verify proportionately, record exposed runtime metadata, and dispatch the next same-thread segment only after success.

When the prompt contains `ROUTE_PROJECT_MODELS_ROUTED_TURN=1` with `ROUTED_MODE=ASSESS` or `ROUTED_MODE=RETUNE`, perform only that routed analysis, write the dedicated report and ledger directly, and return the concise required summary. Do not dispatch recursively unless the same invocation also contains an Apply request whose first implementation segment is ready.

This skill cannot silently observe unrelated Codex tasks. On a later Query, Record, or Retune invocation, reconcile only usage visible in the current task or explicitly supplied by the user; leave other usage uncounted rather than guessing.

The user has authorized same-task routed continuations and the dedicated report and ledger writes by invoking the skill. Do not ask them to switch models or reply “已切换”. Do not use the top-level task-creation capability.

## Availability fallback

If the selected GPT-5.6 route is unavailable, do not stop solely for that reason:

1. Attempt the selected same-thread `<model, thinking>` pair once. Do not loop across unavailable GPT-5.6 routes.
2. Perform the read-only analysis in the current task with its already available model and effort if the preset cannot start. Do not claim that the fallback model or effort was programmatically changed.
3. Show the visible `回退提示` line before continuing with the fallback.
4. If Codex exposes an immediately callable alternative internal model, prefer capability for high-risk analysis and speed for bounded analysis; otherwise keep the current-task fallback.
5. State that fallback occurred, name the actual model only when exposed, and record `fallback_from`, `fallback_to`, and the reason. Use `available-default (unverified)` when the name is hidden. Never claim GPT-5.6 was used without verification.

If no usable model exists, report the capability gap and stop.

## Subagent path

When the prompt contains `ROUTE_PROJECT_MODELS_SUBAGENT=1`, do not delegate or create any task. This secondary path is valid only when the spawning interface explicitly selected a model or named custom preset; a matching task name is insufficient evidence.

Perform only Assess or Retune in this subagent. Return a complete Markdown-ready report plus a small structured ledger payload to the parent task; do not write files. Apply recommendations only to follow-on execution tasks.

## Workflow

1. Confirm a routed-turn or valid subagent marker is present; never spawn recursively.
2. Read applicable `AGENTS.md` files and repository guidance first. Read [usage-ledger.md](references/usage-ledger.md) for Retune.
3. For Assess, inventory the project with cheap commands such as `rg --files`, shallow `find`, manifest inspection, and `git status`. For Retune, start from the script's route-performance signals and inspect changed or underperforming task areas only. Exclude generated output, dependencies, caches, binaries, and vendored code unless directly relevant.
4. Identify project areas by responsibility and workflow, not merely by directory. Inspect representative entry points, manifests, tests, build/deploy files, data boundaries, and high-risk code.
5. Classify recurring tasks in each area by ambiguity, scope, coupling, verification difficulty, and consequence of error.
6. Select the smallest model and lowest reasoning effort likely to finish each follow-on task correctly in one pass. Read [routing-criteria.md](references/routing-criteria.md) for the decision rules.
7. Raise the execution recommendation one tier when evidence is incomplete, requirements are ambiguous, the change crosses several subsystems, or failure can cause security, privacy, money, data loss, or production impact.
8. Lower the execution recommendation after the task is decomposed into bounded, independently verifiable steps.

Do not compile or run tests merely to create the routing plan. For iOS repositories, respect local validation guidance and never launch a full build for a small routing assessment. If later implementation is requested, preserve any requested simulator preview state after proportionate verification.

## Model normalization

Treat `GPT-5.6` and `GPT-5.6 Sol` as the same documented model tier unless the current Codex model picker explicitly describes them differently. Present three distinct routing tiers: Sol, Terra, and Luna. If a recommended tier is unavailable in the user's Codex picker, choose the nearest more capable available tier and say so.

## Routing principles

- Route tasks, not permanent ownership of folders. The same module may use Luna for formatting, Terra for a bounded feature, and Sol for redesigning its architecture.
- Default to Terra with low reasoning for ordinary coding work when evidence does not justify either extreme.
- Use Luna for mechanical, repetitive, high-volume, locally verifiable work.
- Use Sol for ambiguous, deeply coupled, high-risk, or novel work where a wrong plan costs more than additional thinking time.
- Prefer decomposition over increasing reasoning effort. A clean sequence of Terra or Luna tasks is often faster than one broad Sol task.
- Use `xhigh` or `max` only with an explicit reason. Never select them as a generic quality setting.
- Separate implementation from independent review. A cheaper tier may implement a bounded change while a stronger tier reviews architecture, security, or migration risk.

## Required output

These output requirements apply to the complete Markdown result written by a routed turn or returned by a valid explicitly selected subagent. Lead with one sentence naming the recommended default model and effort for the repository.

State the actual analysis model and effort separately from execution recommendations. Explicitly label availability fallback and unverified model names.

Then provide a compact table:

| Project area or task | Evidence | Model | Reasoning | Why | Upgrade trigger |
|---|---|---|---|---|---|

After the table, include:

- **Fast path:** the tasks suitable for Luna or Terra at `none`/`low`.
- **Use Sol only when:** the concrete conditions that justify escalation.
- **Switching sequence:** an ordered, minimal-switch workflow for the user's likely next task.
- **Efficiency estimate:** the baseline, estimated task mix, assumptions, calculation, rounded percentage range, and the highest-impact sources of improvement. Follow the method in [routing-criteria.md](references/routing-criteria.md). Label an estimate as heuristic unless supported by repository-specific timing or evaluation evidence.
- **Usage proportions:** include a `## Usage proportions` heading followed by exactly one empty marker pair, `<!-- MODEL_USAGE_START -->` and `<!-- MODEL_USAGE_END -->`. The coordinator fills it deterministically after ledger updates; do not generate usage statistics inside the markers.
- **Confidence and gaps:** what was inspected, what was inferred, and what could change the routing.

Keep paths and task names concrete. Avoid vague labels such as “backend work” when the repository supports a more precise boundary. Do not claim benchmark-level model differences without current evidence.

## Reassessment

Re-run the routing assessment after a major architecture change, new platform or service integration, security-sensitive feature, failed lower-tier attempt, or material change to the Codex model picker. For a failed attempt, diagnose why it failed before escalating; do not automatically increase both model tier and reasoning effort.

Retune from the deterministic signals in the ledger summary. Raise only after at least 5 comparable attempts with at least 40% failure/escalation/rework pressure. Lower only after at least 10 comparable attempts with at least 90% completion, no pressure events, and deterministic verification. Keep the prior allocation when evidence is below threshold unless the user explicitly requests a heuristic reassessment. Move only the affected task class and note each changed assignment.
