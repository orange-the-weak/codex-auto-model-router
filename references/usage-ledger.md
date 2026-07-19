# Usage ledger

Store project-local history at `.codex/model-routing-history.jsonl`. Keep one compact JSON object per line. Do not store prompts, source code, secrets, or conversation text.

Resolve this path from the nearest Git root with `python3 scripts/model_usage_ledger.py resolve-ledger --repository <path>`, so parent and child repositories never share a ledger. Apply briefs cover the selected current `route_id` only; Query/history must say when values are historical aggregates.

## Event types

- `route_contract`: one immutable runtime anchor for `route_id + plan_hash + protocol + contract_version`; later calls cannot redefine or downgrade the route.
- `segment_claim`: one atomic `prepared` claim with `route_id`, `plan_hash`, `segment_id`, `attempt_id`, and optional identity-bound `capability_decision_hash`. Parallel begin writes the claim and `parallel_dispatch_reservation` under the same lock. A prepared claim may be recovered only before `parallel_worker_start` confirms dispatch; confirmed or consumed claims cannot replay.
- `skill_run`: one invocation. Fields: `event_id`, `timestamp`, `mode`, `analysis_model`, `effort`, and optional fallback fields.
- `execution`: one confirmed Segment attempt. Fields: `event_id`, optional `task_id`, optional `route_id`, optional `segment_id`, `timestamp`, `model`, `effort`, `task_class`, `outcome`, optional non-negative `duration_seconds`, `source`, `verification` (`deterministic`, `manual`, `none`, or `unknown`), and fallback fields. Older records without Segment identifiers remain valid and are treated as whole-task attempts.
- `parallel_plan`: configured intent for one `dependency-parallel-v1` route. Fields: `route_id`, `protocol`, `parallelism_source` (`standard`, `smart-reduced`, or `user-override`; legacy `adaptive-extended` remains readable), `requested_max_parallelism`, `effective_max_parallelism`, `planned_worker_count`, and `model_plan`. This is never actual use or timing.
- `parallel_dispatch_reservation`: the atomic pre-launch boundary. It checks the failure latch while holding the same lock; a later latch blocks new reservations but lets already reserved/running work drain.
- `parallel_worker_start` / `parallel_worker_finish`: coordinator-captured monotonic boundaries for one complete attempt identity; callers supply no timing values. `worker-start` only confirms an existing reservation for new runs. The first failed finish also writes one route-level `parallel_stop_latch` in the same lock.
- `segment_result`: one terminal result committed with its `execution` and `routing_efficiency` derivatives in a recoverable transaction. An identical retry fills only missing events after interruption; a changed payload is rejected. Runtime advancement is derived from these ledger results, never from caller-supplied cursor/completed IDs.
- Schema-v2 `parallel_execution`: one verified run with `worker_intervals`, derived aggregates, `measurement_boundary=dispatch-confirmed-to-result-received`, `timing_provenance=coordinator-monotonic-v1`, and `clock_source=python-monotonic-ns`. Older aggregate-only records remain readable under `legacy_unverified` and never affect verified metrics.
- `routing_efficiency`: observed orchestration metrics from task metadata or user confirmation. Optional fields cover routing, queue wait, executor startup, model switch, Restore, useful execution, model/tool round trips, and state-gate stops. Never fill missing fields with estimates.
- `allocation`: one recommended snapshot. Fields: `event_id`, `timestamp`, `basis`, and `allocation`, whose percentages total 100.

Use `source=user-confirmed` when the user supplies actual usage and `source=task-metadata` only when Codex exposes reliable metadata. Never convert a recommendation into an `execution` event. Use exact model names when known; otherwise use `available-default (unverified)`. An unverified default never authorizes a GPT-5.5 fallback while any GPT-5.6 route is selectable.

For continued or delegated execution, atomically prepare a claim before project work, then bind every worker and result event to `route_id + plan_hash + segment_id + attempt_id`. A same-turn local matched `apply-fast-v1` Segment skips the claim because it cannot replay. The ledger derives stable event IDs and rejects repeated or conflicting identities. Legacy whole-task events remain readable but do not affect Segment proportions or retuning.

## Query rules

Report three independent views:

1. **Actual Segment execution ratio:** non-cancelled segmented `execution` attempts backed by task metadata or user confirmation, grouped by exact model. This is the answer to “各模型实际使用比例”. Also show model × effort. One Segment is one attempt; do not add a second whole-request event for the same work.
   When verified, also group Segment attempts by model × active concurrency. Keep `parallel_plan` configured ratios separate from actual execution.
2. **Analysis ratio:** `skill_run` events grouped by analysis model. Keep this separate so router invocations do not distort implementation usage.
3. **Recommended ratio:** the newest `allocation` event. Label it planned, not actual.

Show counts with percentages. Report success and pressure within comparable task-class/model/effort groups. If there are fewer than five confirmed attempts, label the ratio as an early sample. If there are none, say there is insufficient observed data.

Show total verified actual elapsed time, cumulative parallel-task duration, and peak concurrency only from schema-v2 `parallel_execution`. Coarse work estimates, plan creation time, and aggregate values supplied by model text are not runtime evidence.

Derive `并行省时估算 = 1 - actual elapsed / cumulative parallel-task duration` and slot utilization from verified runs. Raw `peak_concurrency` and `leaf_parallel_utilization_percent` stay leaf-task-only for schema compatibility; Query and chat use `visible_peak_concurrency = peak_concurrency + 1` and `parallel_utilization_percent`, which include one coordinator interval. The saving is an overlap estimate against concatenating the captured task intervals, not a controlled A/B speedup. Display whole-unit durations and percentages while retaining raw seconds/nanoseconds internally.

## Retuning rules

- Prefer observed outcomes and durations over heuristic allocation.
- Raise only after at least 5 comparable attempts and at least 40% failed, escalated, or reworked outcomes.
- Lower only after at least 10 comparable attempts, at least 90% completion, no failed/escalated/reworked outcomes, and deterministic verification.
- Do not compare durations across substantially different task classes as if they were equivalent.
- Preserve the old recommendation in history by appending a new allocation; never rewrite old JSONL events.
- Record availability fallbacks so later queries can distinguish intentional routing from forced substitution.
- For GPT-5.5, require `fallback_reason=gpt56-family-unavailable` plus a verified structured `capability_decision` bound to the complete attempt identity. It must show either a complete model surface with no GPT-5.6 route or pre-execution rejection of Sol, Terra, and Luna; free text alone is rejected.

The script validates enums and durations, assigns event IDs, deduplicates supplied event IDs, locks concurrent reads/writes, skips malformed lines with warnings, and never rewrites ledger history. Warnings from unrelated malformed historical lines do not block a complete current-route aggregate.

Use:

- `python3 scripts/model_usage_ledger.py claim --ledger <path> --route-id <id> --plan-hash <hash> --segment-id <id> --attempt-id <id>` before legacy serial Segment work.
- `python3 scripts/model_usage_ledger.py parallel-plan --ledger <path> --route-id <id> --parallelism-source <source> --requested-max-parallelism <n> --effective-max-parallelism <n> --planned-worker-count <n> --model-plan '<json>'` for configured intent.
- `python3 scripts/router_runtime.py worker-start --ledger <path> --route-id <id> --plan-hash <hash> --segment-id <id> --attempt-id <id>` immediately after a reserved dispatch is confirmed.
- `python3 scripts/router_runtime.py worker-finish --ledger <path> --route-id <id> --plan-hash <hash> --segment-id <id> --attempt-id <id> --outcome <outcome>` after result receipt.
- The legacy `parallel-execution` CLI remains import-compatible, but its aggregate-only records are unverified and excluded.
- `python3 scripts/model_usage_ledger.py efficiency --ledger <path> --route-id <id> --source task-metadata|user-confirmed ...` for observed routing overhead and blocking evidence.
- `python3 scripts/model_usage_ledger.py summary --ledger <path>` for JSON aggregation.
- `python3 scripts/model_usage_ledger.py record ...` or `python3 scripts/model_usage_ledger.py allocation ...` for append-only updates.
- `python3 scripts/model_usage_ledger.py render --ledger <path> --report <path>` to replace only the block between `<!-- MODEL_USAGE_START -->` and `<!-- MODEL_USAGE_END -->`. Never let an LLM edit that block directly.
