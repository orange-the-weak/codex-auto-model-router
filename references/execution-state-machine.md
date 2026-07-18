# Segmented and dependency-parallel execution state machine

Use this state machine for Apply:

`CLASSIFY -> PLAN -> NORMALIZE -> CAPABILITY_CHECK -> SEGMENT_READY -> EXECUTE -> VERIFY -> RECORD -> ADVANCE | STOP -> RESTORE -> RETURN`

For dependency-parallel Apply, use:

`CLASSIFY -> PLAN_DAG -> NORMALIZE -> CAPABILITY_CHECK -> FRONTIER -> DISPATCH -> WAIT_ANY -> RECORD -> FRONTIER | STOP_DISPATCH -> DRAIN -> AGGREGATE -> RETURN`

Assess and Retune skip `PLAN`, `NORMALIZE`, and `ADVANCE`. Query and Record use their local fast paths.

## Invariants

- One invocation has one mode and one immutable `route_id`.
- Apply has one normalized plan under an immutable adaptive budget: linear `segmented-v1` or DAG-based `dependency-parallel-v1`.
- Each segment has one stable `segment_id`, one selected route, one goal, immutable predecessors, and one verification budget.
- The cursor advances only after the current segment succeeds; an atomic pre-execution claim prevents the same Segment envelope from executing twice.
- Adjacent segments with the same model and effort are merged before execution.
- Every new Apply request and every candidate Segment is routed from its own evidence. A previous request or Segment route never biases selection in either direction: simple work can move down, and complex work can move up.
- The bundled benchmark snapshot is an offline, stale-aware prior. Its audit metadata is immutable in new plans and covered by `plan_hash`; legacy envelopes without that field remain valid. Missing, invalid, or expired evidence falls back without a network request.
- The standard budget is 4/4, eligible complex or large plans may expand to 6/6, and explicit user budgets may reach the absolute 8/8 hard limit. Switch counts include final Restore.
- Dispatch performs at most one same-task continuation per segment boundary and at most one explicitly model-selectable subagent fallback per segment.
- Availability fallback stays inside GPT-5.6 while Sol, Terra, or Luna is selectable. GPT-5.5 is legal only after the capability check proves the complete GPT-5.6 family unavailable.
- Only reliable task metadata or explicit user confirmation establishes actual model identity.
- Never make a persistent same-task switch when the original model or effort is unknown.
- A failed segment stops the plan. Never retry by cycling through routes or re-planning.
- A verified GPT-5.6 original remains immutable across intermediate switches. Make one Restore attempt only when that original is Sol, Terra, or Luna and the final/failed Segment is not already on it. A non-5.6 original is audit-only after verified GPT-5.6 execution.
- `RETURN` is terminal and cannot execute or advance a segment.
- Report or ledger persistence failure does not invalidate otherwise completed work.
- Parallel execution has an automatic ceiling of 4 and only reduces it from dependency-independent width, model task count, and runtime capacity. It never auto-expands. A user request above 4 requires observed matching `agents.max_threads` and enough independent ready work; otherwise it is rejected instead of queued. Executors are created only after a free slot is confirmed.
- The parallel Coordinator exclusively owns the frontier, dispatch, wait-any loop, failure state, and deterministic aggregation. `stop-dispatch-drain-running` starts no new work after the first failure but waits for already active workers.
- Parallel write tasks declare concrete `write_scopes`; overlapping write scopes and shared `conflict_keys` add dependencies and degrade to serial. The complete DAG, routes, estimates, scopes, conflict keys, `parallelism_source`, requested/effective concurrency, scheduler, aggregation order, and failure policy are covered by `plan_hash` and echoed in worker envelopes. Legacy parallel plans without the source remain valid.

## Plan normalization

The policy script validates a JSON array and returns `protocol=segmented-v1`, a unique `route_id`, the normalized segments, dispatch decisions, switch count, and Restore requirement.

Normalize in this order:

1. Validate IDs, required fields, linear dependencies, enums, and overrides.
2. Choose the lowest sufficient GPT-5.6 model and effort for every candidate.
3. Compare each independently selected route with the current execution route only to choose local execution or a switch.
4. Merge adjacent segments with the same route.
5. Rebuild indexes and linear dependencies.
6. Record the evidence snapshot status and ID, then select the immutable budget: standard 4/4; adaptive 6/6 only with a concrete complex or large basis; or a user override from 1 to 8. Reject any over-budget plan.

Do not mutate the returned plan after execution starts. If new work appears, finish or stop the current route and require a new user invocation.

For `dependency-parallel-v1`, normalize the DAG as specified in [parallel-execution.md](parallel-execution.md). The existing 4/6/8 Segment budgets remain unchanged; executor dispatch does not count as a persistent main-thread model switch.

## Transitions

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
| RESTORE | RETURN | stop after one failed Restore attempt |
| RETURN | terminal result | terminal result |

## Immutable plan envelope

Every Apply continuation carries:

- `ROUTE_PROJECT_MODELS_ROUTED_TURN=1`
- `ROUTED_MODE=APPLY_SEGMENT`
- `protocol=segmented-v1`
- immutable `route_id`, complete normalized plan, `segment_budget`, `switch_budget`, `budget_source`, SHA-256 `plan_hash`, and deterministic per-segment `attempt_id`
- zero-based current cursor, one-based display index, `segment_id`, and total
- selected model/effort, goal, acceptance, and validation budget
- verified `original_model` and `original_effort`
- repository, report, and ledger paths
- accumulated completed-segment results and changed-file summary

The receiver runs the policy script's envelope validator, recomputes `plan_hash` and `attempt_id`, and validates the outer `route_id`, selected budgets and source, original route, Restore decision, zero-based cursor, named Segment, and ordered completed IDs. It then atomically claims `(route_id, segment_id, attempt_id)` in the ledger before project work. Any mismatch or repeated claim is terminal.

## Same-task chain

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
2. If the target is unavailable, resolve within the family: Sol → Terra → Luna, Terra → Sol → Luna, Luna → Terra → Sol. Preserve effort.
3. Use a GPT-5.6 executor preset only if the subagent interface explicitly proves the selected model/preset.
4. Give the executor only one segment with `ROUTE_PROJECT_MODELS_EXECUTOR=1`, `route_id`, and `segment_id`; let the Coordinator validate the result and advance the cursor.
5. Execute locally only if the current model is GPT-5.6, or the capability check proves no GPT-5.6 route exists.
6. Use GPT-5.5 only after all GPT-5.6 options are proven unavailable. Record and disclose `gpt56-family-unavailable` once.

Never treat a generic subagent name as model evidence. Never count a configured route as actual use. A failed Segment still stops immediately; family fallback is a bounded pre-execution capability decision, not a retry loop.

## Backward compatibility

`ROUTED_MODE=APPLY_ONESHOT` is accepted only as a one-segment plan. It executes once and proceeds directly to Restore; it cannot create or advance additional implementation segments.

Legacy `segmented-v1` plans remain readable. New plans may include the optional local-node fields without changing legacy model nodes. `dependency-parallel-v1` is opt-in or selected by a valid non-linear dependency graph and uses its own frontier envelope validator.
