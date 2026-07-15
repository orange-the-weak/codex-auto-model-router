# Segmented execution state machine

Use this state machine for Apply:

`CLASSIFY -> PLAN -> NORMALIZE -> CAPABILITY_CHECK -> SEGMENT_READY -> EXECUTE -> VERIFY -> RECORD -> ADVANCE | STOP -> RESTORE -> RETURN`

Assess and Retune skip `PLAN`, `NORMALIZE`, and `ADVANCE`. Query and Record use their local fast paths.

## Invariants

- One invocation has one mode and one immutable `route_id`.
- Apply has one normalized linear plan under an immutable adaptive budget.
- Each segment has one stable `segment_id`, one selected route, one goal, one predecessor at most, and one verification budget.
- The cursor advances only after the current segment succeeds; an atomic pre-execution claim prevents the same Segment envelope from executing twice.
- Adjacent segments with the same model and effort are merged before execution.
- Every new Apply request and every candidate Segment is routed from its own evidence. A previous request or Segment route never biases selection in either direction: simple work can move down, and complex work can move up.
- The standard budget is 4/4, eligible complex or large plans may expand to 6/6, and explicit user budgets may reach the absolute 8/8 hard limit. Switch counts include final Restore.
- Dispatch performs at most one same-task continuation per segment boundary and at most one explicitly model-selectable subagent fallback per segment.
- Only reliable task metadata or explicit user confirmation establishes actual model identity.
- Never make a persistent same-task switch when the original model or effort is unknown.
- A failed segment stops the plan. Never retry by cycling through routes or re-planning.
- The verified original model and effort remain immutable across intermediate switches. Make one Restore attempt only when the final/failed Segment is not already on that route.
- `RETURN` is terminal and cannot execute or advance a segment.
- Report or ledger persistence failure does not invalidate otherwise completed work.

## Plan normalization

The policy script validates a JSON array and returns `protocol=segmented-v1`, a unique `route_id`, the normalized segments, dispatch decisions, switch count, and Restore requirement.

Normalize in this order:

1. Validate IDs, required fields, linear dependencies, enums, and overrides.
2. Choose the lowest sufficient model and effort for each candidate segment.
3. Compare each independently selected route with the current execution route only to choose local execution or a switch.
4. Merge adjacent segments with the same route.
5. Rebuild indexes and linear dependencies.
6. Select the immutable budget: standard 4/4; adaptive 6/6 only with a concrete complex or large basis; or a user override from 1 to 8. Reject any over-budget plan.

Do not mutate the returned plan after execution starts. If new work appears, finish or stop the current route and require a new user invocation.

## Transitions

| State | Success | Failure |
|---|---|---|
| CLASSIFY | PLAN for Apply; SELECT for Assess/Retune | ask only for conflicting or unsupported explicit values |
| PLAN | NORMALIZE | reduce to the smallest useful linear plan |
| NORMALIZE | CAPABILITY_CHECK | stop on invalid IDs, dependencies, overrides, segment count, or switch budget |
| CAPABILITY_CHECK | SEGMENT_READY using same-task, explicit preset, or local route | use current model; disclose only high-risk fallback |
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
4. If no segment remains, return directly when already on the original route; otherwise Restore that immutable route once and return the accumulator.

On failure, do not increment the cursor. Mark remaining segments skipped, Restore once when required, and return the partial result.

## Fallback chain

When persistent same-task switching is unavailable or unsafe:

1. Use an executor preset only if the subagent interface explicitly proves the selected model/preset.
2. Give the executor only one segment with `ROUTE_PROJECT_MODELS_EXECUTOR=1`, `route_id`, and `segment_id`.
3. Let the Coordinator validate the result and advance the cursor.
4. If no explicit selector exists, execute locally with the current model.

Never treat a generic subagent name as model evidence. Never count a configured route as actual use.

## Backward compatibility

`ROUTED_MODE=APPLY_ONESHOT` is accepted only as a one-segment plan. It executes once and proceeds directly to Restore; it cannot create or advance additional implementation segments.
