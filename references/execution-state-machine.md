# Legacy strict execution state machine

This reference is not the default Apply path. The default routing path uses direct local or leaf-agent execution without hashes, claims, cursor, ledger gates, or Restore. Read and use this state machine only after the user explicitly requests strict routing, strict ledger auditing, replay protection, or a reproducible routing experiment.

Use this state machine for Apply:

`CLASSIFY -> PLAN -> NORMALIZE -> CAPABILITY_CHECK -> SEGMENT_READY -> EXECUTE -> VERIFY -> RECORD -> ADVANCE | STOP -> RESTORE -> RETURN`

For dependency-parallel Apply, use:

`CLASSIFY -> PLAN_DAG -> NORMALIZE -> CAPABILITY_CHECK -> FRONTIER -> DISPATCH -> WAIT_ANY -> RECORD -> FRONTIER | STOP_DISPATCH -> DRAIN -> AGGREGATE -> RETURN`

Assess and Retune skip `PLAN`, `NORMALIZE`, and `ADVANCE`. Query and Record use their local fast paths.

## Invariants

- One invocation has one mode and one immutable `route_id`.
- Apply has one normalized plan: one Segment uses `apply-fast-v1`, multiple sequential Segments use `segmented-v1`, and independent work may use `dependency-parallel-v1`.
- Each segment has one stable `segment_id`, one selected route, one goal, immutable predecessors, and one verification budget.
- `apply-fast-v1` has no cursor. A local matched Segment skips the replay claim; a switched/continued Segment keeps an atomic claim. Multi-Segment cursors advance only after success.
- Adjacent segments merge only with an explicit shared `merge_group` and identical route source and task evidence; equal routes alone preserve their boundaries without another switch.
- Every new Apply request and every candidate Segment is routed from its own evidence. A previous request or Segment route never biases selection in either direction: simple work can move down, and complex work can move up.
- Automatic routed efforts are `low|medium|high|xhigh|max`. `ultra` is disabled by default. It is legal only as an explicit user opt-in for one bounded `apply-fast-v1` Segment; that native Codex mode combines maximum reasoning with proactive delegation, so `dependency-parallel-v1` must be disabled for the request.
- The bundled benchmark snapshot is an offline, stale-aware prior. Its audit metadata is immutable in new plans and covered by `plan_hash`; legacy envelopes without that field remain valid. Missing, invalid, or expired evidence falls back without a network request.
- The standard budget is 4/4, eligible complex or large plans may expand to 6/6, and explicit user budgets may reach the absolute 8/8 hard limit. Switch counts include final Restore.
- Dispatch performs at most one same-task continuation per segment boundary and at most one explicitly model-selectable subagent fallback per segment.
- Every same-task continuation is readable-first because Codex may expose the prompt as a normal chat message. A short task/route/next-action block precedes the machine envelope; the bounded envelope follows inside `<!-- CODEX_ROUTER_INTERNAL ... -->`, or in a final `内部路由上下文` fence only when the surface strips comments before model input.
- Availability fallback stays inside GPT-5.6 while Sol, Terra, or Luna is selectable. Every non-target route uses a verified capability decision bound to the complete attempt identity. GPT-5.5 is legal only after the capability check proves the complete GPT-5.6 family unavailable; a reason string alone never authorizes it.
- Only reliable task metadata or explicit user confirmation establishes actual model identity.
- Never make a persistent same-task switch when the original model or effort is unknown.
- A failed segment stops the plan. Never retry by cycling through routes or re-planning.
- A verified GPT-5.6 original remains immutable across intermediate switches. Make one Restore attempt only when that original is Sol, Terra, or Luna and the final/failed Segment is not already on it. A non-5.6 original is audit-only after verified GPT-5.6 execution.
- `RETURN` is terminal after at most one ID-based Restore verification; it cannot execute or advance a segment.
- Report, ledger, or runtime-state persistence failure after project completion does not invalidate completed work. Use isolated temporary state when possible, otherwise return one non-blocking warning.
- Parallel execution has an automatic ceiling of 4 leaf tasks. The capacity rule is `observed total slots - coordinator - running tasks`, applied globally; effective concurrency is the minimum of requested concurrency, useful independent width, and that free capacity. Four total slots normally mean one coordinator plus a peak of three leaf tasks; the visible chat combines these as `并发计划：4 个任务（含主任务）`. A documented/default thread limit is not live capacity. Store only the dispatch-capacity policy in `plan_hash`; immediately before every dispatch, the runtime boundary supplies a trusted capacity observation independently of the caller envelope. A JSON field that labels itself `task-metadata` is not proof. Without observed capacity, dispatch one task as a probe, then require a runtime observation before refill. A user request above 4 requires matching observed free slots and useful width.
- The Coordinator calls `router_runtime.py worker-start` after each dispatch confirmation and `worker-finish` after each result receipt, always with matching route/plan/segment/attempt identity. The runtime captures a shared monotonic clock; callers never supply time values. A prepared parallel claim may be recovered only until dispatch confirmation.
- A terminal `finish` consumes the matching claim through one atomic `segment_result`, derives frontier/cursor state from ledger results, and derives every parallel aggregate from complete per-task intervals. Caller-supplied completion state is never authoritative; incomplete evidence remains `pending`, and legacy aggregate-only records stay outside verified history.
- The coordinator prints the returned `parallel_execution_brief` verbatim and never recomputes its values.
- The parallel Coordinator exclusively owns the frontier, dispatch, wait-any loop, failure state, and deterministic aggregation. The first failure atomically writes a route-level stop latch; `stop-dispatch-drain-running` then rejects new claims while allowing already active tasks to finish.
- Parallel write tasks declare concrete `write_scopes`; resolve every scope to its real repository-relative path before hashing and comparison, so a symlink alias and its target conflict. Escapes are rejected. Overlapping write scopes and shared `conflict_keys` add dependencies and degrade to serial. Contract-v2 plans retain pre-conflict `declared_dependencies`; the receiver rebuilds conflict dependencies and `serialized_conflicts`, validates fixed scheduler/failure/delegation/ownership/security semantics, and accepts only GPT-5.6 Sol/Terra/Luna with a routed effort. The complete DAG and protocol metadata remain covered by `plan_hash`.
- On first accepted `begin`, the runtime atomically persists the canonical normalized plan, `plan_hash`, route/segment/attempt identities, original route, protocol, and contract version. Later `finish` and `restore` resolve that state with `route_id + segment_id + attempt_id`; callers never reconstruct the plan after compaction. Every worker event and dispatch reservation still checks the trusted anchor. Recomputing a valid hash after changing a route is insufficient, and an issued v2 route cannot strip its contract marker to enter the legacy path.

## Plan normalization

The policy script validates a JSON array and returns `apply-fast-v1` for one normalized Segment or `segmented-v1` for multiple sequential Segments, plus a unique `route_id`, routes, budgets, and Restore decision.

`apply-fast-v1` avoids a full DAG/cursor envelope. If the selected route already matches, execute locally and return. If it differs, send one compact readable-first continuation with immutable identity, claim once, execute, and Restore once when required.

Normalize in this order:

1. Validate IDs, required fields, linear dependencies, task-evidence enums (including optional `latency_priority=low|normal|high`), and overrides. Reject automatic Ultra, Luna/ultra, multi-Segment Ultra, and every Ultra plus Router-parallel combination.
2. Choose the lowest sufficient GPT-5.6 model and effort for every candidate.
3. Compare each independently selected route with the current execution route only to choose local execution or a switch.
4. Merge only when adjacent Segments share an explicit semantic `merge_group`, route source, and complete task evidence. Equal routes alone remain separate without adding a switch.
5. Rebuild indexes and linear dependencies.
6. Record the evidence snapshot status and ID, then select the immutable budget: standard 4/4; adaptive 6/6 only with a concrete complex or large basis; or a user override from 1 to 8. Reject any over-budget plan.

Do not mutate the returned plan after execution starts. If new work appears, finish or stop the current route and require a new user invocation.

For `dependency-parallel-v1`, require an explicit content-based `segment_id` for every leaf and normalize the DAG as specified in [parallel-execution.md](parallel-execution.md). Missing IDs and ordinal-only names such as `segment-1` or `worker-2` are invalid. The existing 4/6/8 Segment budgets remain unchanged; executor dispatch does not count as a persistent main-thread model switch.

## Transitions

Use `scripts/router_runtime.py begin` before serial project work, `finish` after it, and `restore` only in the restored terminal turn. For parallel work, the Coordinator calls `prepare-dispatch` once with the canonical plan and thereafter by `route_id`; each executor calls `attach` with its IDs and hash-bound ticket before project tools. `finish` loads the persisted plan and derives the next state. `restore` reads the persisted original route and result; it never receives or recomputes `plan_hash`. All gates are idempotent at their legal boundary.

| State | Success | Failure |
|---|---|---|
| CLASSIFY | PLAN for Apply; SELECT for Assess/Retune | ask only for conflicting or unsupported explicit values |
| PLAN | NORMALIZE | reduce to the smallest useful linear plan |
| NORMALIZE | CAPABILITY_CHECK | stop on invalid IDs, dependencies, overrides, segment count, or switch budget |
| FRONTIER | DISPATCH for the highest-priority ready node when a slot is free | stop on dependency, capacity, or hash mismatch |
| CAPABILITY_CHECK | SEGMENT_READY using target GPT-5.6, a deterministic 5.6 substitute, explicit 5.6 preset, or eligible local route | use GPT-5.5 only when the complete 5.6 family is unavailable; otherwise stop |
| SEGMENT_READY | EXECUTE after one visible route line | stop on envelope or cursor mismatch |
| EXECUTE | VERIFY | STOP; do not attempt another model |
| VERIFY | RECORD | STOP with verification failure |
| RECORD | ADVANCE or RESTORE | note ledger failure internally and continue |
| ADVANCE | SEGMENT_READY for exactly the next cursor | STOP on missing or repeated cursor |
| STOP | RESTORE when needed | RETURN partial result directly if no switch occurred |
| RESTORE | verify persisted original route by IDs, then RETURN | return a non-blocking warning after one failed verification |
| RETURN | terminal result | terminal result |

## Coordinator state and worker capsule

The first Apply continuation carries:

- `ROUTE_PROJECT_MODELS_ROUTED_TURN=1`
- `ROUTED_MODE=APPLY_SEGMENT`
- `protocol=segmented-v1`
- immutable `route_id`, complete normalized plan, `segment_budget`, `switch_budget`, `budget_source`, SHA-256 `plan_hash`, and deterministic per-segment `attempt_id`
- zero-based current cursor, one-based display index, `segment_id`, and total
- selected model/effort, goal, acceptance, and validation budget
- verified `original_model` and `original_effort`
- repository, report, and ledger paths
- accumulated completed-segment results and changed-file summary

After the first successful `begin`, compacted continuations may carry only the current IDs and bounded Segment capsule; the runtime restores canonical plan fields from persisted state. `finish` and `restore` require only `route_id + segment_id + attempt_id` plus result metadata. Never put the full normalized plan back together from remembered chat text.

The prompt order is part of the user-visible contract:

1. `继续当前任务：<task segment>`
2. the compact `Codex 自动路由` line
3. one concise next-action sentence
4. only then `<!-- CODEX_ROUTER_INTERNAL ... -->` containing the bounded machine envelope

Never put mode flags, IDs, hashes, paths, JSON, or the full plan before the readable block. Restore uses `任务已完成，正在恢复原模型并返回结果。` before its hidden internal block.

The coordinator retains the complete immutable plan and conversation context. `prepare-dispatch` persists it and returns `dispatch-ticket-v1` capsules containing only the goal, necessary decisions, dependencies, selected route, access/write scopes, conflict keys, acceptance, validation budget, prohibited actions, and immutable IDs/hash. No worker receives a duplicate plan or outer concurrency object. `agent_task_name` is the content-based semantic `segment_id` normalized to Codex's `[a-z0-9_]+` grammar. `attach` validates the ticket against persisted state. Any identity/hash mismatch or latched route failure is terminal.

## Same-task chain

Before switching models, the coordinator calls `router_runtime.py prepare-route` with the complete canonical envelope. This validates and persists the normalized plan once. The continuation carries only `route_id`, `segment_id`, and `attempt_id`; `begin` reloads the canonical plan from runtime state. Never copy or reconstruct `canonical_plan` in a continuation prompt. Missing state stops before project work instead of accepting a partial plan.

The Coordinator checks once that the continuation tool accepts `model` and `thinking`. A locally matched first segment may execute before any continuation. Otherwise it sends the first segment with its selected route.

After a successful segment:

1. Append its status, verification, and changed-file summary to the accumulator.
2. Increment the cursor exactly once.
3. If a next segment exists, send one same-task continuation using its exact model and effort, then end the current turn.
4. If no segment remains, return directly when already on the original route. Restore once only when the original route is GPT-5.6; if the original was GPT-5.5 or another non-5.6 model, stay on the verified GPT-5.6 route.

On failure, do not increment the cursor. Mark remaining segments skipped, Restore once when required, and return the partial result.

## Fallback chain

When persistent same-task switching is unavailable or unsafe:

1. Read the capability surface's supported-model list. Unknown availability requires trying the target GPT-5.6 route first.
2. If the target is unavailable, resolve within GPT-5.6 using the target lane's quality/latency intent; do not blindly preserve effort when that would reverse the reason for the route.
3. Use a GPT-5.6 executor preset only if the subagent interface explicitly proves the selected model/preset.
4. Give the executor one hash-bound ticket and require ID-only `attach`. `ROUTE_PROJECT_MODELS_EXECUTOR=1` is a legacy prompt marker, not a shell-environment authorization check.
5. Execute locally only if the current model is GPT-5.6, or the capability check proves no GPT-5.6 route exists.
6. Use GPT-5.5 only after all GPT-5.6 options are proven unavailable. Record and disclose `gpt56-family-unavailable` once.

Never treat a generic subagent name as model evidence. Never count a configured route as actual use. A failed Segment still stops immediately; family fallback is a bounded pre-execution capability decision, not a retry loop.

## Backward compatibility

`ROUTED_MODE=APPLY_ONESHOT` is accepted only as a one-segment plan. It executes once and proceeds directly to Restore; it cannot create or advance additional implementation segments.

Legacy `segmented-v1` plans remain readable. `apply-fast-v1` is used only for new one-Segment plans. `dependency-parallel-v1` remains opt-in or selected by a valid non-linear dependency graph. Legacy status comes from the runtime's first trusted route binding; removing `contract_version` from an already-bound v2 plan never grants legacy compatibility.
