---
name: codex-auto-model-router
description: Analyze, apply, query, record, and retune Codex project routing. For Apply, build the smallest useful bounded task graph, parallelize only independent work, and select GPT-5.6 Sol, Terra, or Luna with low through max reasoning per Segment. Never select Ultra automatically; accept it only as an explicit one-Segment opt-in and then disable Router-managed parallelism. Keep fallback inside GPT-5.6 whenever any 5.6 model is available, restore only a verified original GPT-5.6 route, and use GPT-5.5 only when the complete 5.6 family is unavailable. Maintain a Markdown report and validated per-Segment and concurrency history. Use when the user invokes $codex-auto-model-router, asks which model should handle project work, requests routed implementation, queries usage ratios, records outcomes, or retunes assignments. Never create a new top-level Codex task.
---

# Codex Auto Model Router

Route simple requests through `apply-fast-v1`: re-evaluate the request, select one route, and avoid a full DAG/cursor continuation when no switch is needed. Use linear `segmented-v1` only for real sequential boundaries and `dependency-parallel-v1` only for genuinely independent work. Never inherit the previous request's strength, add API integration, create a top-level Codex task, or commit/push unless the user separately requests it.

Run `scripts/route_policy.py` before Assess, Retune, or Apply. For Apply, pass a JSON segment plan with `--segments-json`. Read [execution-state-machine.md](references/execution-state-machine.md) for segment envelopes and transitions, [preset-mapping.md](references/preset-mapping.md) before custom-agent fallback, [usage-ledger.md](references/usage-ledger.md) before writing history, [routing-criteria.md](references/routing-criteria.md) for model selection, and [benchmark-evidence.md](references/benchmark-evidence.md) before changing evidence-derived lanes.

## Path dispatch

Choose one path before other work:

- `ROUTE_PROJECT_MODELS_ROUTED_TURN=1` with `ROUTED_MODE=APPLY_SEGMENT`: run only the named segment, then advance, stop, or Restore.
- `ROUTE_PROJECT_MODELS_ROUTED_TURN=1` with `ROUTED_MODE=APPLY_ONESHOT`: backward-compatible one-segment Apply; run it once, then Restore.
- `ROUTE_PROJECT_MODELS_ROUTED_TURN=1` with `ROUTED_MODE=ASSESS` or `RETUNE`: perform only that analysis, save artifacts, then Restore.
- `ROUTE_PROJECT_MODELS_ROUTED_TURN=1` with `ROUTED_MODE=RETURN`: run only the pending ID-based Restore verification when needed, then present the accumulated result concisely.
- A `dispatch-ticket-v1` attachment: execute only the persisted bounded Segment; never plan, route, or delegate. `ROUTE_PROJECT_MODELS_EXECUTOR=1` is accepted only for legacy envelopes.
- `ROUTE_PROJECT_MODELS_SUBAGENT=1`: perform only the supplied Assess or Retune analysis.
- Otherwise use the Coordinator path.

Unknown modes, missing `route_id`, invalid `segment_id`, or a cursor outside the supplied plan are terminal errors. Never reinterpret them or recurse.

## Coordinator path

1. Classify exactly one mode:
   - **Apply:** build, change, fix, refactor, test, review, or other project execution.
   - **Assess:** analyze or refresh repository routing without implementation.
   - **Query:** show usage, ratios, history, or current allocation.
   - **Record:** append a user-confirmed completed task and outcome.
   - **Retune:** adjust assignments using the report and observed history.
   - **Help:** a bare invocation. Show modes and examples in at most six lines; do not scan the repository.
2. Query, Record, and Help never switch models or spawn agents. Use the local ledger script for Query and Record.
3. Parse optional user overrides. Accept Sol, GPT-5.6, GPT-5.6 Sol, Terra, or Luna; accept low, medium, high, xhigh, or max, and map `very high` or `extra high` to xhigh. Never select `ultra` automatically. Accept it only when the user explicitly enables it for one bounded Apply Segment; default the model to Sol when none is named, reject Luna/ultra, and disable `dependency-parallel-v1` because native Ultra may delegate proactively. A whole-request override applies to every ordinary routed segment. A segment-specific override applies only there. Ask only when overrides conflict or are unsupported.
4. For Assess or Retune, classify and route the single analysis task with the policy script, then use Capability check and Dispatch.
5. For Apply, create the smallest necessary plan. One normalized Segment uses `apply-fast-v1`; multiple sequential Segments use `segmented-v1`; independent tasks may use `dependency-parallel-v1`.
6. For serial work use `scripts/router_runtime.py begin`, `finish`, and `restore`. For parallel work, call `prepare-dispatch` once with the full plan, then send only its hash-bound lightweight tickets; each executor calls `attach` with IDs and `ticket_hash`. `finish` and `restore` resolve persisted state by IDs. Never ask a model to rebuild a plan or hand-write a worker envelope.

## Apply segment planning

Use one segment by default. Add a boundary only when the next stage has a different objective, verification contract, or sufficient route. Common useful boundaries are analysis, implementation, deterministic verification, and high-risk review; do not add all four mechanically.

Each candidate segment must contain:

- `segment_id`: lowercase stable identifier unique within `route_id`; for parallel work, make it a short content-based slug such as `runtime-ledger-audit` or `windows-install-check`, never a random name
- `goal`: bounded work owned only by this segment
- `depends_on`: for `segmented-v1`, empty for the first segment and otherwise exactly the previous ID; for `dependency-parallel-v1`, zero or more earlier Segment IDs
- `task_kind`: `mechanical`, `ordinary`, or `complex`
- `risk`: `low`, `normal`, or `high`
- `size`: `tiny`, `normal`, or `large`
- optional task evidence: `ambiguity` and `coupling` (`low|medium|high`), `verification` (`deterministic|mixed|judgment`), `consequence` (`low|normal|high`), `latency_priority` (`low|normal|high`), `prior_failure` (boolean), and `prior_failure_kind=reasoning|verification|infrastructure`; an unclassified or infrastructure failure never triggers xhigh
- optional `merge_group`: a semantic slug that explicitly allows otherwise-identical neighboring or short sibling tasks to merge; same route alone is insufficient
- `acceptance`: one or more concrete completion checks
- `validation_budget`: the maximum proportionate verification work
- parallel-only `work_estimate=short|normal|long`, `access_mode=read|write`, concrete repository-relative `write_scopes` for every write task, and `conflict_keys`
- optional segment-specific `model`, `effort`, and `route_source=report|user-override`; whole-request user overrides take precedence over report routes

Pass the JSON array to `scripts/route_policy.py --mode apply --segments-json '<json>'`. When the user sets a limit, add `--max-segments 1..8` and/or `--max-switches 1..8`; one supplied value applies to both dimensions unless both are supplied. A global saved-report route is valid only for a one-segment plan; for multi-segment plans, attach each matching report route to its segment. Treat the returned order, budgets, selected routes, dispatch values, `route_id`, `plan_hash`, per-segment `attempt_id`, and Restore decision as authoritative.

Adaptive budgets:

- Use the standard budget of four routed segments and four switches including final Restore.
- Expand automatically to six segments and six switches only when the normalized plan exceeds 4/4 and contains a concrete `task_kind=complex` or `size=large` basis. High risk alone does not expand the budget.
- Honor a user budget from 1 to 8. Eight segments and eight switches are absolute hard limits; never create an unbounded chain.
- Store `segment_budget`, `switch_budget`, and `budget_source=standard|adaptive-extended|user-override` in the immutable plan and envelope.
- Merge only when both Segments share an explicit `merge_group`, route source, task evidence, and route. Keeping adjacent equal-route Segments separate does not add a switch.
- Route every Segment from its own task kind, risk, size, ambiguity, coupling, verification, consequence, prior failure, report match, and user override. Use the current route only to choose `local` versus `same-task-switch` after selection.
- Use the bundled, versioned `references/benchmark-evidence.json` only as an offline prior. Code owns the safety mapping and rejects a snapshot that rewrites it. Task evidence and user overrides outrank the snapshot; missing, invalid, or expired evidence keeps the same deterministic gradient instead of collapsing lanes. Never fetch benchmarks during Apply.
- `segmented-v1` rejects branches, cycles, and non-linear dependencies. `dependency-parallel-v1` accepts only an acyclic graph whose dependencies reference earlier IDs. Both reject duplicate IDs and conflicting overrides. Explicit native Ultra requires exactly one `apply-fast-v1` Segment and cannot be combined with Router-managed parallelism.
- Never re-plan after execution begins. A failed segment stops the chain; do not retry it by cycling through models.
- Do not add a review segment unless risk, ambiguity, or the user requires an independent review.

## Dependency-aware parallel planning

Enable `--parallel` only when useful independent work exists. Automatic planning requests at most 4 parallel tasks, then reduces it by dependency-independent width and **observed free execution slots**. When metadata exposes total slots, pass `--runtime-total-slots <n>`; the planner reserves one coordinator slot and subtracts already-running executors. For `prepare-dispatch`, wrap the live observation as schema v2 bound to the exact `route_id`, `plan_hash`, and a one-use `observation_id`; stale or replayed observations cannot authorize another batch. A four-slot Codex session normally peaks at three leaves plus the coordinator. Without exposed capacity, issue one probe ticket and refill after a fresh observation.

- Keep a single task intact when its state or file boundaries are coupled. Split one long task only across real independent boundaries with separate acceptance checks and ownership.
- Estimate work coarsely as short, normal, or long. Compute critical-path weight from this estimate and dispatch ready tasks in descending critical-path order, breaking ties by normalized plan order. Use wait-any list scheduling: when any worker completes, update the frontier and fill the next free slot; do not impose wave barriers.
- Merge at most three short siblings only when they share an explicit `merge_group`, identical dependencies, successors, route source, task evidence, and compatible mutation ownership.
- Prefer read-only workers for broad discovery. Every write worker must own concrete repository-relative `write_scopes`; concurrently running write scopes must not overlap. Use `conflict_keys` to serialize Git index, lockfiles, project files, migrations, deployment targets, shared simulators, and other shared mutable resources. Any conflict adds a deterministic dependency and degrades to serial.
- The coordinator exclusively owns the full plan, conversation context, ready/running/completed frontier, wait-any loop, and final summary. Workers receive only a bounded context capsule: goal, necessary decisions, paths/ownership, dependencies, acceptance, validation budget, prohibited actions, and immutable IDs/hashes. Each completed worker stores a bounded structured `handoff` in the route's atomic result inbox; a dependent worker reads only its declared dependency results during `attach`. Never relay every result through prose or copy the full chat/future plan into every worker.
- When creating a Codex leaf agent, pass the capsule's `agent_task_name`, deterministically normalized from the semantic `segment_id` to Codex's `[a-z0-9_]+` grammar. Do not generate random Router names or generic `worker_1` labels. A client may still display its own decorative nickname; that UI alias is outside the Skill's control.
- Failure policy is `stop-dispatch-drain-running`: after the first failed worker, start nothing else, wait for already running workers, preserve their bounded results, mark undispatched work skipped, and summarize deterministically in normalized Segment order. Never retry a failed Segment by cycling models.
- Hash the full DAG, routes, coarse work estimates, write scopes, conflict keys, `parallelism_source=standard|smart-reduced|user-override`, requested/effective concurrency, scheduler, aggregation order, and failure policy. Persist that canonical plan once. `prepare-dispatch` validates the current frontier and confirmed free capacity, reserves up to that many ready tasks, and emits hash-bound `dispatch-ticket-v1` capsules without the full plan or duplicate concurrency metadata. Legacy envelopes remain readable.
- Create only the executors covered by the current ticket batch. Keep later nodes in the immutable plan. After `worker-finish`, call `finish` immediately with a bounded `handoff`; runtime persists it and uses the released slot to return one ready continuation ticket when dependencies are satisfied. Dispatch that ticket before writing coordinator prose. Call `prepare-dispatch --route-id ...` only to recover outstanding tickets or fill additional freshly confirmed slots. Do not add a wave barrier or a waiting agent queue.

Immediately before parallel dispatch show:

When total-slot metadata is available, count the coordinator in the visible total and show:

`Codex 自动路由｜并发计划：<effective + coordinator> 个任务（含主任务）｜来源：<standard|smart-reduced|user-override>｜调度：关键路径优先`

Without verified capacity, show `并发计划：2 个任务（含主任务）`; internally dispatch one leaf task as the probe without adding that implementation detail to the visible line.

Then show the normal per-Segment model line once for each dispatched worker. This makes both automatic model and concurrency selection visible.

## Capability check and Dispatch

Use this order once for the complete plan:

1. Search available Codex task tools for `send_message_to_thread` (normally `codex_app__send_message_to_thread`). Use native same-task chaining only when the interface explicitly accepts `model` and `thinking`. Never create a new top-level Codex task. Linear routing uses only the verified `current.thread_id`; parallel routing may create bounded leaf executor agents through the available agent tool, never an unverified generic task interface.
2. Read the tool's supported-model list when exposed. Before any non-target execution, run `scripts/route_policy.py --resolve-fallback --target-model <model> --target-effort <effort> --available-model <id> ...`. Bind the verified capability result to `route_id + plan_hash + segment_id + attempt_id` as `capability_decision` in the continuation envelope. Unknown availability means try the selected GPT-5.6 target first; it never authorizes GPT-5.5.
3. If the original model and effort are verified, execute a locally matched first segment or send the first mismatched segment to the same task with its exact model and effort. Each successful segment sends at most one follow-up for the next segment. This is intentional bounded continuation, not recursive planning.
4. If the target is rejected for availability before execution, use the resolver's lane-aware GPT-5.6 substitute. It may change both model and effort to preserve the original quality/latency intent; do not blindly carry the effort label to another family. These bounded capability attempts are not Segment retries.
5. If persistent same-task switching is unsafe or unavailable, execute through explicitly model-selectable executor presets that target GPT-5.6 when the subagent interface proves the selection. A task/agent name alone is not proof of model selection.
6. Execute locally only when the current model is GPT-5.6 or the capability check proves that Sol, Terra, and Luna are all unavailable. Never accept `available-default`, the current model, or GPT-5.5 while any GPT-5.6 route remains selectable. Do not restore to an original GPT-5.5 setting after a GPT-5.6 Segment succeeds.
7. Use GPT-5.5 only after the capability surface explicitly exposes no GPT-5.6 model, or all three 5.6 candidates are rejected as unavailable before Segment execution. Record the identity-bound structured `capability_decision`, `fallback_from`, `fallback_to`, and `fallback_reason=gpt56-family-unavailable`; a free-text reason alone is never sufficient.

Never make a persistent same-task switch when the original model or effort is unknown. The policy returns `selectable-subagent-or-local` in that case.

## Context and envelope

The coordinator retains the full immutable plan. A worker or one-Segment continuation carries only:

- `ROUTE_PROJECT_MODELS_ROUTED_TURN=1` and `ROUTED_MODE=APPLY_SEGMENT`
- one immutable `route_id`, protocol version, `plan_hash`, `segment_id`, and `attempt_id`
- current `segment_id`, index, selected model/effort, goal, dependencies, acceptance, and validation budget
- content-based `agent_task_name`, deterministically normalized from the semantic `segment_id`, for Codex leaf-agent creation
- verified `original_model` and `original_effort`
- repository, report, and ledger paths
- only the necessary prior decisions and bounded changed-file/result summary

Do not include full chat history or unrelated future implementation details. `segmented-v1` coordinator state still validates the complete plan; leaf workers never receive it.

## Readable continuation prompt

Treat every `send_message_to_thread` prompt as user-visible. Never begin it with `ROUTE_PROJECT_MODELS_*`, `ROUTED_MODE`, JSON, IDs, hashes, paths, or other machine fields.

Start every model-switch or Segment continuation with this readable block:

```text
继续当前任务：<task segment>
Codex 自动路由｜任务段：<task segment>｜模型：<model>｜推理：<effort>｜<reason>
<one concise sentence describing what happens next>
```

After the readable block, place the bounded machine envelope in a Markdown HTML comment so the receiving model retains it without making it the first visible content:

```text
<!-- CODEX_ROUTER_INTERNAL
ROUTE_PROJECT_MODELS_ROUTED_TURN=1
ROUTED_MODE=APPLY_SEGMENT
<bounded immutable envelope>
-->
```

Keep the actionable goal and acceptance criteria concise and readable before the internal comment when the receiver needs them. If the continuation surface strips HTML comments before model input, put the same internal block in a fenced section titled `内部路由上下文` at the end; the readable block must still come first. Restore prompts start with `任务已完成，正在恢复原模型并返回结果。` before their internal `ROUTED_MODE=RETURN` block.

## Visible routing protocol

Immediately before every Assess, Retune, Apply segment, Query, or Record, show one compact commentary line:

`Codex 自动路由｜任务段：<task segment>｜模型：<model>｜推理：<low|medium|high|xhigh|max|ultra|none>｜<reason>`

- This means Codex automatically selected the route; never use an ambiguous bare `路由提示` label.
- Show the line once per executed segment, not once per command or file.
- Keep Segment index and total in the immutable plan and ledger only; do not expose `<index>/<total>` in the commentary line.
- Do not narrate fast-path internals; one compact route line is enough.
- If the selected route already matches the current task settings, show the actual model and effort with `当前路由已匹配`; never show `current-route` or `keep` placeholders.
- Label a configured route as configured, not observed, when reliable metadata is unavailable.
- A normal successful completion needs no separate model-identity or runtime-verification warning.
- Always disclose a GPT-5.5 fallback once, even for low-risk work, because it proves the GPT-5.6 family was unavailable.
- Only for a high-risk fallback, show: `Codex 自动路由状态｜目标：<model/effort>｜当前对话不支持带模型续接，已用当前可用模型继续｜<reason>`.

## Routed Apply segment

When `ROUTED_MODE=APPLY_SEGMENT`:

1. Run `scripts/router_runtime.py begin --ledger <path> --envelope-json '<json>'`. It validates protocol/identity/frontier and immediate dispatch capacity, verifies the actual runtime route, persists the canonical normalized plan, identity, and original route, then prepares an atomic claim. Unknown or mismatched runtime identity stops before project tools or edits.
2. A local `apply-fast-v1` Segment whose selected route already matches skips claim, cursor, full-plan continuation, and Restore. A switched fast Segment retains one compact claim and one final Restore decision.
3. Show the segment's visible routing line, then execute only its goal. Read applicable repository instructions, preserve unrelated changes, and stay within its validation budget.
4. Run `scripts/router_runtime.py finish` once with `route_id`, `segment_id`, `attempt_id`, outcome, and bounded result metadata. Do not resend or reconstruct the plan. It loads the persisted begin state, records only verified execution, and resolves `advance|refill-frontier|restore|return|stop`.
5. On failure, record the verified outcome when possible, stop all remaining segments, and enter Restore with a concise partial result. Do not silently retry with another route.
6. On success, append the bounded result and changed-file summary to the accumulator. If another segment exists, send exactly one readable-first same-task continuation with the next model/effort and cursor, then end the turn.
7. After the final segment, run proportionate final checks only if they were assigned to that segment, then enter Restore.

`ROUTED_MODE=APPLY_ONESHOT` follows the same rules as a plan containing exactly one segment and cannot create another implementation segment.

## Executor fallback path

An executor preset normally receives `dispatch-ticket-v1`, then calls `router_runtime.py attach` with `route_id`, `segment_id`, `attempt_id`, and `ticket_hash` before project work. It does not receive or reconstruct the full plan and does not depend on a shell environment marker that the agent interface cannot inject. The legacy `ROUTE_PROJECT_MODELS_EXECUTOR=1` path remains readable. Execute only the bounded Segment, do not route or delegate, and return status, changed files, checks, remaining risks, and exposed runtime model metadata. The coordinator alone advances the cursor. Read [preset-mapping.md](references/preset-mapping.md) for exact names.

For `dependency-parallel-v1`, the executor also receives the immutable plan hash, selected route, dependencies, access mode, write scopes, conflict keys, acceptance, and validation budget. It must stay inside its write ownership and preserve unrelated changes. The coordinator uses wait-any scheduling but aggregates status, changed files, checks, risks, and runtime metadata in normalized Segment order after draining active workers.

## Query and Record fast path

The default Apply brief covers the current run only. Query and history views must be explicitly labeled as historical aggregates. Resolve the project ledger with `python3 scripts/model_usage_ledger.py resolve-ledger --repository <path>` so the nearest Git root owns the history; never mix parent and child repository ledgers.

Before Query or Record, use the visible line with `local-script` and `none`.

- Record the invocation as `skill_run` with the matching mode.
- Query runs `summary`, then `render` to update only the marked report section.
- Record appends only user-confirmed or reliable task-metadata execution, then summarizes and renders.
- Report actual execution proportions as verified Segment attempts, separate from analysis calls and latest recommended allocation.
- For parallel work, keep `parallel_plan` as configured intent. Immediately after each parallel task dispatch is confirmed, call `router_runtime.py worker-start` with `route_id`, `plan_hash`, `segment_id`, and `attempt_id`; immediately after its result is received, call `worker-finish` with the same identity. These commands capture the coordinator's monotonic clock themselves—never pass timestamps, durations, peak concurrency, or aggregate timing from model text. A prepared parallel claim may be recovered only until dispatch is confirmed; a confirmed dispatch cannot replay.
- Call `router_runtime.py finish` immediately for every returned parallel result. It stores the bounded dependency handoff and may return the next ready ticket from the just-released slot; the terminal call also derives actual elapsed time, cumulative parallel-task time, task overlap, orchestration gaps, peak concurrency, and task count, then appends one schema-v2 `parallel_execution`. Missing, reversed, or incomplete traces remain `pending`. Legacy aggregate-only records stay readable but are excluded from verified metrics.
- Print the returned `parallel_execution_brief` verbatim. Never recompute, round, translate, or reformat its values in the Apply response.
- Record `routing_efficiency` only from task metadata or user confirmation: routing/orchestration, queue wait, executor startup, switch, Restore, useful execution, model/tool round trips, and state-gate stops. Missing fields stay missing; never guess them.
- End every Apply chat summary with one concise concurrency line. For serial work say `并发：未启用｜原因：任务未形成有价值的独立并行边界`. Without verified timing say `并发计划：<leaf peak + 1> 个任务（含主任务）｜测量：待记录`. With complete intervals say `并发：峰值 <leaf peak + 1>（含主任务）｜实际用时：<h时m分s秒>｜子任务累计：<h时m分s秒>｜任务重叠：<h时m分s秒>｜编排空档：<h时m分s秒>`. Raw `peak_concurrency` remains leaf-task concurrency. Round durations to whole seconds. Never label `1 - actual / cumulative` as speedup or time saved: it mixes useful overlap with scheduling gaps. Report actual speedup only for an optional controlled A/B run.
- The canonical elapsed interval runs from the first dispatch confirmation through the last result receipt on the coordinator's monotonic clock. Keep raw seconds and nanoseconds internally for compatibility, but never display obsolete compression/factor labels.
- Never infer actual use from a recommendation or configured-but-unverified route.

## Routed Assess and Retune

Perform only the requested read-only analysis. Save the report to `<repository>/docs/codex-model-routing-report.md`, maintain `<repository>/.codex/model-routing-history.jsonl`, and enter Restore. Do not implement project work or recursively dispatch.

## Restore and Return

- Preserve an original GPT-5.6 model and effort from the Coordinator envelope; never replace them with an intermediate segment route. Keep a non-5.6 original only for audit and do not use it as a Restore target after verified GPT-5.6 execution.
- If the final/failed segment is already on the verified original route, return the accumulated result directly; it is already restored.
- Otherwise, after success or failure, if a persistent switch occurred and the verified original is GPT-5.6 with both values known, make exactly one Restore continuation with the original `model` and `thinking`, `ROUTED_MODE=RETURN`, the same `route_id`, and the accumulated result.
- In that restored turn, call `scripts/router_runtime.py restore --ledger <path> --route-id <id> --segment-id <id> --attempt-id <id>`. It reads the original route and terminal result from persisted begin/finish state. Never resend, rebuild, or guess `plan_hash`.
- `finish` and `restore` are idempotent. If project ledger or runtime-state writes fail after project work completes, return the project result with one non-blocking warning; identity mismatches still stop.
- If the original model was GPT-5.5 or another non-5.6 model and a GPT-5.6 Segment ran, skip Restore and return on the verified GPT-5.6 route. This prevents completion from silently switching the task back to GPT-5.5.
- If restoration is rejected, do not loop. Mention it only for high-risk work or when the user asks for an audit.
- `RETURN` is terminal after the one deterministic Restore verification: perform no project tools, edits, tests, assessment, delegation, segment advancement, or additional routing.

## Assessment and routing principles

Assess and Retune use GPT-5.6 Sol/high by default so policy changes receive consistent analysis; an explicit user model or effort override still wins. Inventory representative project evidence without builds or tests. Route each follow-on task by ambiguity, scope, coupling, verification difficulty, consequence of error, latency priority, and classified prior failure. Eight automatic lanes are active: Luna/medium, Luna/high, Luna/xhigh, Luna/max, Terra/high, Sol/medium, Sol/high, and Sol/xhigh. Use Luna/medium as the mechanical floor and Luna/high for ordinary bounded work, including normal-size evidence scans. Use Luna/xhigh for large bounded scan/review work where max startup and token expansion are not justified. Use Luna/max only for genuinely large deterministic deep work with low consequence and acceptable latency. Terra/high is an explicit latency specialist. Sol/medium fits bounded complex work; Sol/high requires high ambiguity, coupling, or consequence rather than `judgment` alone. Sol/xhigh requires a classified reasoning/verification failure on complex work or explicit user choice; infrastructure and unclassified failures do not escalate. The full model-effort matrix remains available by explicit user override; `max` is the highest automatic single-route effort. Never select `ultra` automatically; explicit native Ultra owns its own proactive delegation, so the Router must not add parallel executors. Prefer a bounded Segment over higher effort.

## Report and ledger output

Lead the report with the default route and state the actual analysis route separately. Include task evidence, model, effort, reason, upgrade trigger, fast path, Sol-only cases, dynamic segment examples, efficiency estimate, usage proportions, and confidence gaps. The efficiency estimate must state its baseline, task mix, switching overhead, calculation, `预计增效：约 X–Y%`, highest-impact optimization, and whether it is heuristic or measured.

Under `## Usage proportions`, include exactly one empty marker pair:

`<!-- MODEL_USAGE_START -->`

`<!-- MODEL_USAGE_END -->`

The ledger script owns the marker contents. Retune raises only after at least 5 comparable attempts with at least 40% failure/escalation/rework pressure, and lowers only after at least 10 attempts with at least 90% completion, deterministic verification, and no pressure events. Keep chat results brief: completion, key optimizations, checks, remaining risk, concurrency-effectiveness line, and report link when applicable.
