---
name: codex-auto-model-router
description: Deterministically analyze, apply, query, record, and retune project model routing inside Codex. For Apply, create the smallest useful bounded task graph, run independent work with dependency-aware concurrency when worthwhile, and select GPT-5.6 Sol, Terra, or Luna plus low, medium, high, or xhigh reasoning per segment. Keep availability fallback inside the GPT-5.6 family whenever any 5.6 model is available, restore only a verified original GPT-5.6 route, and use GPT-5.5 only when the complete GPT-5.6 family is unavailable. Maintain a Markdown report and validated per-segment and parallel usage history. Use when the user invokes $codex-auto-model-router, asks which model should handle project work, requests dynamically routed implementation, queries usage ratios, records outcomes, or retunes assignments. Never create a new top-level Codex task.
---

# Codex Auto Model Router

Route simple requests through `apply-fast-v1`: re-evaluate the request, select one route, and avoid a full DAG/cursor continuation when no switch is needed. Use linear `segmented-v1` only for real sequential boundaries and `dependency-parallel-v1` only for genuinely independent work. Never inherit the previous request's strength, add API integration, create a top-level Codex task, or commit/push unless the user separately requests it.

Run `scripts/route_policy.py` before Assess, Retune, or Apply. For Apply, pass a JSON segment plan with `--segments-json`. Read [execution-state-machine.md](references/execution-state-machine.md) for segment envelopes and transitions, [preset-mapping.md](references/preset-mapping.md) before custom-agent fallback, [usage-ledger.md](references/usage-ledger.md) before writing history, [routing-criteria.md](references/routing-criteria.md) for model selection, and [benchmark-evidence.md](references/benchmark-evidence.md) before changing evidence-derived lanes.

## Path dispatch

Choose one path before other work:

- `ROUTE_PROJECT_MODELS_ROUTED_TURN=1` with `ROUTED_MODE=APPLY_SEGMENT`: run only the named segment, then advance, stop, or Restore.
- `ROUTE_PROJECT_MODELS_ROUTED_TURN=1` with `ROUTED_MODE=APPLY_ONESHOT`: backward-compatible one-segment Apply; run it once, then Restore.
- `ROUTE_PROJECT_MODELS_ROUTED_TURN=1` with `ROUTED_MODE=ASSESS` or `RETUNE`: perform only that analysis, save artifacts, then Restore.
- `ROUTE_PROJECT_MODELS_ROUTED_TURN=1` with `ROUTED_MODE=RETURN`: do no project work; present the accumulated result concisely.
- `ROUTE_PROJECT_MODELS_EXECUTOR=1`: execute only the supplied bounded segment; never plan, route, or delegate.
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
3. Parse optional user overrides. Accept Sol, GPT-5.6, GPT-5.6 Sol, Terra, or Luna; accept low, medium, high, xhigh, and map `very high` or `extra high` to xhigh. A whole-request override applies to every segment. A segment-specific override applies only there. Ask only when overrides conflict or are unsupported.
4. For Assess or Retune, classify and route the single analysis task with the policy script, then use Capability check and Dispatch.
5. For Apply, create the smallest necessary plan. One normalized Segment uses `apply-fast-v1`; multiple sequential Segments use `segmented-v1`; independent tasks may use `dependency-parallel-v1`.
6. Use `scripts/router_runtime.py begin` and `finish` as the normal state gates. They combine envelope validation, replay claim when needed, runtime inspection, verified recording, and next-state resolution. Do not split those deterministic operations into extra model turns.

## Apply segment planning

Use one segment by default. Add a boundary only when the next stage has a different objective, verification contract, or sufficient route. Common useful boundaries are analysis, implementation, deterministic verification, and high-risk review; do not add all four mechanically.

Each candidate segment must contain:

- `segment_id`: lowercase stable identifier unique within `route_id`
- `goal`: bounded work owned only by this segment
- `depends_on`: for `segmented-v1`, empty for the first segment and otherwise exactly the previous ID; for `dependency-parallel-v1`, zero or more earlier Segment IDs
- `task_kind`: `mechanical`, `ordinary`, or `complex`
- `risk`: `low`, `normal`, or `high`
- `size`: `tiny`, `normal`, or `large`
- optional task evidence: `ambiguity` and `coupling` (`low|medium|high`), `verification` (`deterministic|mixed|judgment`), `consequence` (`low|normal|high`), and `prior_failure` (boolean)
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
- Merge adjacent segments with the same model and effort.
- Route every Segment from its own task kind, risk, size, ambiguity, coupling, verification, consequence, prior failure, report match, and user override. Use the current route only to choose `local` versus `same-task-switch` after selection.
- Use the bundled, versioned `references/benchmark-evidence.json` only as an offline prior. Task evidence and user overrides outrank it. If the snapshot is missing, invalid, or expired, use the deterministic fallback; never fetch benchmarks during Apply.
- `segmented-v1` rejects branches, cycles, and non-linear dependencies. `dependency-parallel-v1` accepts only an acyclic graph whose dependencies reference earlier IDs. Both reject duplicate IDs and conflicting overrides.
- Never re-plan after execution begins. A failed segment stops the chain; do not retry it by cycling through models.
- Do not add a review segment unless risk, ambiguity, or the user requires an independent review.

## Dependency-aware parallel planning

Enable `--parallel` only when useful independent work exists. Automatic planning requests at most 4, then reduces it by dependency-independent width and **observed free worker slots**. When metadata exposes total slots, pass `--runtime-total-slots <n>`; the planner reserves one coordinator slot and subtracts already-running workers from `--runtime-running-workers`. Do not treat a documented/default thread limit as live free capacity. With no observed capacity, dispatch one worker, confirm the next free slot, then refill; never pre-create a queue. A user request above 4 is legal only when observed free slots and useful independent width both meet it.

- Keep a single task intact when its state or file boundaries are coupled. Split one long task only across real independent boundaries with separate acceptance checks and ownership.
- Estimate work coarsely as short, normal, or long. Compute critical-path weight from this estimate and dispatch ready tasks in descending critical-path order, breaking ties by normalized plan order. Use wait-any list scheduling: when any worker completes, update the frontier and fill the next free slot; do not impose wave barriers.
- Merge at most three short siblings only when they have identical dependencies and successors, the same selected model/effort and task class, and compatible mutation ownership.
- Prefer read-only workers for broad discovery. Every write worker must own concrete repository-relative `write_scopes`; concurrently running write scopes must not overlap. Use `conflict_keys` to serialize Git index, lockfiles, project files, migrations, deployment targets, shared simulators, and other shared mutable resources. Any conflict adds a deterministic dependency and degrades to serial.
- The coordinator exclusively owns the full plan, conversation context, ready/running/completed frontier, wait-any loop, and final summary. Workers receive only a bounded context capsule: goal, necessary decisions, paths/ownership, dependencies, acceptance, validation budget, prohibited actions, and immutable IDs/hashes. Never copy the full chat or future plan into every worker.
- Failure policy is `stop-dispatch-drain-running`: after the first failed worker, start nothing else, wait for already running workers, preserve their bounded results, mark undispatched work skipped, and summarize deterministically in normalized Segment order. Never retry a failed Segment by cycling models.
- Hash the full DAG, routes, coarse work estimates, write scopes, conflict keys, `parallelism_source=standard|smart-reduced|user-override`, requested/effective concurrency, scheduler, aggregation order, and failure policy. Echo the source and both caps in every worker envelope; validate them against the immutable plan, completed/running sets, dependencies, confirmed free capacity, and attempt ID. Legacy `adaptive-extended` plans and plans without `parallelism_source` remain readable.
- Create an executor only after confirming a free slot. Keep later nodes in the immutable plan but do not pre-create, queue, or block agents beyond effective capacity; refill exactly one free slot after a worker returns.

Immediately before parallel dispatch show:

`Codex 自动路由｜并行计划：<tasks> 个任务｜并发：<effective>/<requested>｜可用 worker：<observed>｜来源：<standard|smart-reduced|user-override>｜调度：关键路径优先`

Then show the normal per-Segment model line once for each dispatched worker. This makes both automatic model and concurrency selection visible.

## Capability check and Dispatch

Use this order once for the complete plan:

1. Search available Codex task tools for `send_message_to_thread` (normally `codex_app__send_message_to_thread`). Use native same-task chaining only when the interface explicitly accepts `model` and `thinking`. Never create a new top-level Codex task. Linear routing uses only the verified `current.thread_id`; parallel routing may create bounded leaf executor agents through the available agent tool, never an unverified generic task interface.
2. Read the tool's supported-model list when exposed. Before any non-target execution, run `scripts/route_policy.py --resolve-fallback --target-model <model> --target-effort <effort> --available-model <id> ...`. Unknown availability means try the selected GPT-5.6 target first; it never authorizes GPT-5.5.
3. If the original model and effort are verified, execute a locally matched first segment or send the first mismatched segment to the same task with its exact model and effort. Each successful segment sends at most one follow-up for the next segment. This is intentional bounded continuation, not recursive planning.
4. If the target is rejected for availability before execution, use the resolver's deterministic GPT-5.6 substitute: Sol → Terra → Luna, Terra → Sol → Luna, or Luna → Terra → Sol. These bounded capability attempts are not Segment retries.
5. If persistent same-task switching is unsafe or unavailable, execute through explicitly model-selectable executor presets that target GPT-5.6 when the subagent interface proves the selection. A task/agent name alone is not proof of model selection.
6. Execute locally only when the current model is GPT-5.6 or the capability check proves that Sol, Terra, and Luna are all unavailable. Never accept `available-default`, the current model, or GPT-5.5 while any GPT-5.6 route remains selectable. Do not restore to an original GPT-5.5 setting after a GPT-5.6 Segment succeeds.
7. Use GPT-5.5 only after the capability surface explicitly exposes no GPT-5.6 model, or all three 5.6 candidates are rejected as unavailable before Segment execution. Record `fallback_from`, `fallback_to`, and `fallback_reason=gpt56-family-unavailable`; never silently downgrade.

Never make a persistent same-task switch when the original model or effort is unknown. The policy returns `selectable-subagent-or-local` in that case.

## Context and envelope

The coordinator retains the full immutable plan. A worker or one-Segment continuation carries only:

- `ROUTE_PROJECT_MODELS_ROUTED_TURN=1` and `ROUTED_MODE=APPLY_SEGMENT`
- one immutable `route_id`, protocol version, `plan_hash`, `segment_id`, and `attempt_id`
- current `segment_id`, index, selected model/effort, goal, dependencies, acceptance, and validation budget
- verified `original_model` and `original_effort`
- repository, report, and ledger paths
- only the necessary prior decisions and bounded changed-file/result summary

Do not include full chat history or unrelated future implementation details. `segmented-v1` coordinator state still validates the complete plan; leaf workers never receive it.

## Visible routing protocol

Immediately before every Assess, Retune, Apply segment, Query, or Record, show one compact commentary line:

`Codex 自动路由｜Segment <index>/<total>：<task segment>｜模型：<model>｜推理：<low|medium|high|xhigh|none>｜<reason>`

- This means Codex automatically selected the route; never use an ambiguous bare `路由提示` label.
- Show the line once per executed segment, not once per command or file.
- For a one-segment request, use `Segment 1/1`.
- Do not narrate fast-path internals; one compact route line is enough.
- If the selected route already matches the current task settings, show the actual model and effort with `当前路由已匹配`; never show `current-route` or `keep` placeholders.
- Label a configured route as configured, not observed, when reliable metadata is unavailable.
- A normal successful completion needs no separate model-identity or runtime-verification warning.
- Always disclose a GPT-5.5 fallback once, even for low-risk work, because it proves the GPT-5.6 family was unavailable.
- Only for a high-risk fallback, show: `Codex 自动路由状态｜目标：<model/effort>｜当前对话不支持带模型续接，已用当前可用模型继续｜<reason>`.

## Routed Apply segment

When `ROUTED_MODE=APPLY_SEGMENT`:

1. Run `scripts/router_runtime.py begin --ledger <path> --envelope-json '<json>'`. It validates protocol/identity/frontier, performs an atomic claim only when continuation can replay, inspects runtime metadata, and returns the bounded context capsule. If its state gate stops, do no project work.
2. A local `apply-fast-v1` Segment whose selected route already matches skips claim, cursor, full-plan continuation, and Restore. A switched fast Segment retains one compact claim and one final Restore decision.
3. Show the segment's visible routing line, then execute only its goal. Read applicable repository instructions, preserve unrelated changes, and stay within its validation budget.
4. Run `scripts/router_runtime.py finish` once with the bounded result. It inspects current metadata, records actual execution only from task metadata or user confirmation, accepts optional observed overhead metrics, and resolves `advance|refill-frontier|restore|return|stop`.
5. On failure, record the verified outcome when possible, stop all remaining segments, and enter Restore with a concise partial result. Do not silently retry with another route.
6. On success, append the bounded result and changed-file summary to the accumulator. If another segment exists, send exactly one same-task continuation with the next model/effort and cursor, then end the turn.
7. After the final segment, run proportionate final checks only if they were assigned to that segment, then enter Restore.

`ROUTED_MODE=APPLY_ONESHOT` follows the same rules as a plan containing exactly one segment and cannot create another implementation segment.

## Executor fallback path

An executor preset requires `ROUTE_PROJECT_MODELS_EXECUTOR=1`, `route_id`, and `segment_id`. Execute only that bounded segment, do not route or delegate, and return status, changed files, checks, remaining risks, and exposed runtime model metadata to the coordinator. The coordinator alone advances the cursor. Read [preset-mapping.md](references/preset-mapping.md) for exact names.

For `dependency-parallel-v1`, the executor also receives the immutable plan hash, selected route, dependencies, access mode, write scopes, conflict keys, acceptance, and validation budget. It must stay inside its write ownership and preserve unrelated changes. The coordinator uses wait-any scheduling but aggregates status, changed files, checks, risks, and runtime metadata in normalized Segment order after draining active workers.

## Query and Record fast path

Before Query or Record, use the visible line with `local-script` and `none`.

- Record the invocation as `skill_run` with the matching mode.
- Query runs `summary`, then `render` to update only the marked report section.
- Record appends only user-confirmed or reliable task-metadata execution, then summarizes and renders.
- Report actual execution proportions as verified Segment attempts, separate from analysis calls and latest recommended allocation.
- For parallel work, also report model × verified concurrency. Record `parallel_plan` as configured intent. Record `parallel_execution` only when wall clock, cumulative worker duration, peak concurrency, worker count, source, and outcome are genuinely available from task metadata or user confirmation. Never use the ledger event timestamp as a worker start time or turn estimates into observed timing.
- Record `routing_efficiency` only from task metadata or user confirmation: routing/orchestration, queue wait, executor startup, switch, Restore, useful execution, model/tool round trips, and state-gate stops. Missing fields stay missing; never guess them.
- End every Apply chat summary with one concise concurrency line. For serial work say `并发：未启用｜原因：任务未形成有价值的独立并行边界`. Without verified timing say `并发：<effective>/<requested>｜测量：待记录`. With verified timing say `并发：峰值 <n>｜墙钟：<wall>｜累计 worker：<worker>｜有效并发倍率：<worker / wall>x｜并发利用率：<worker / (peak × wall)>%`. The multiplier is an observed work-overlap metric and needs no serial baseline; do not call it actual speedup. Report actual speedup only for an optional controlled A/B run.
- Never infer actual use from a recommendation or configured-but-unverified route.

## Routed Assess and Retune

Perform only the requested read-only analysis. Save the report to `<repository>/docs/codex-model-routing-report.md`, maintain `<repository>/.codex/model-routing-history.jsonl`, and enter Restore. Do not implement project work or recursively dispatch.

## Restore and Return

- Preserve an original GPT-5.6 model and effort from the Coordinator envelope; never replace them with an intermediate segment route. Keep a non-5.6 original only for audit and do not use it as a Restore target after verified GPT-5.6 execution.
- If the final/failed segment is already on the verified original route, return the accumulated result directly; it is already restored.
- Otherwise, after success or failure, if a persistent switch occurred and the verified original is GPT-5.6 with both values known, make exactly one Restore continuation with the original `model` and `thinking`, `ROUTED_MODE=RETURN`, the same `route_id`, and the accumulated result.
- If the original model was GPT-5.5 or another non-5.6 model and a GPT-5.6 Segment ran, skip Restore and return on the verified GPT-5.6 route. This prevents completion from silently switching the task back to GPT-5.5.
- If restoration is rejected, do not loop. Mention it only for high-risk work or when the user asks for an audit.
- `RETURN` is terminal: perform no tools, edits, tests, assessment, delegation, ledger writes, segment advancement, or additional routing.

## Assessment and routing principles

Inventory representative project evidence without builds or tests. Route each recurring task by ambiguity, scope, coupling, verification difficulty, consequence of error, and whether a well-scoped attempt already failed. Luna/low fits clear mechanical work; Terra/low or medium fits bounded ordinary engineering; Sol/medium fits bounded complex work; Sol/high fits high ambiguity, coupling, judgment, or consequence. Reserve Sol/xhigh for failed complex attempts or explicit user choice. Prefer a bounded segment over higher effort.

## Report and ledger output

Lead the report with the default route and state the actual analysis route separately. Include task evidence, model, effort, reason, upgrade trigger, fast path, Sol-only cases, dynamic segment examples, efficiency estimate, usage proportions, and confidence gaps. The efficiency estimate must state its baseline, task mix, switching overhead, calculation, `预计增效：约 X–Y%`, highest-impact optimization, and whether it is heuristic or measured.

Under `## Usage proportions`, include exactly one empty marker pair:

`<!-- MODEL_USAGE_START -->`

`<!-- MODEL_USAGE_END -->`

The ledger script owns the marker contents. Retune raises only after at least 5 comparable attempts with at least 40% failure/escalation/rework pressure, and lowers only after at least 10 attempts with at least 90% completion, deterministic verification, and no pressure events. Keep chat results brief: completion, key optimizations, checks, remaining risk, concurrency-effectiveness line, and report link when applicable.
