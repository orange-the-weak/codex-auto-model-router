# Usage ledger

Store project-local history at `.codex/model-routing-history.jsonl`. Keep one compact JSON object per line. Do not store prompts, source code, secrets, or conversation text.

Resolve this path from the nearest Git root with `python3 scripts/model_usage_ledger.py resolve-ledger --repository <path>`, so parent and child repositories never share a ledger. Apply briefs cover the selected current `route_id` only; Query/history must say when values are historical aggregates.

## Event types

- `segment_claim`: one atomic pre-execution claim with `route_id`, `segment_id`, `attempt_id`, and optional `task_id`. The first append wins; a repeated claim means the envelope was already consumed and must not execute again.
- `skill_run`: one invocation. Fields: `event_id`, `timestamp`, `mode`, `analysis_model`, `effort`, and optional fallback fields.
- `execution`: one confirmed Segment attempt. Fields: `event_id`, optional `task_id`, optional `route_id`, optional `segment_id`, `timestamp`, `model`, `effort`, `task_class`, `outcome`, optional non-negative `duration_seconds`, `source`, `verification` (`deterministic`, `manual`, `none`, or `unknown`), and fallback fields. Older records without Segment identifiers remain valid and are treated as whole-task attempts.
- `parallel_plan`: configured intent for one `dependency-parallel-v1` route. Fields: `route_id`, `protocol`, `parallelism_source` (`standard`, `smart-reduced`, or `user-override`; legacy `adaptive-extended` remains readable), `requested_max_parallelism`, `effective_max_parallelism`, `planned_worker_count`, and `model_plan`. This is never actual use or timing.
- `parallel_worker_start` / `parallel_worker_finish`: coordinator-captured monotonic boundaries for one `route_id` + `segment_id`; callers supply no timing values.
- Schema-v2 `parallel_execution`: one verified run with `worker_intervals`, derived aggregates, `measurement_boundary=dispatch-confirmed-to-result-received`, `timing_provenance=coordinator-monotonic-v1`, and `clock_source=python-monotonic-ns`. Older aggregate-only records remain readable under `legacy_unverified` and never affect verified metrics.
- `routing_efficiency`: observed orchestration metrics from task metadata or user confirmation. Optional fields cover routing, queue wait, executor startup, model switch, Restore, useful execution, model/tool round trips, and state-gate stops. Never fill missing fields with estimates.
- `allocation`: one recommended snapshot. Fields: `event_id`, `timestamp`, `basis`, and `allocation`, whose percentages total 100.

Use `source=user-confirmed` when the user supplies actual usage and `source=task-metadata` only when Codex exposes reliable metadata. Never convert a recommendation into an `execution` event. Use exact model names when known; otherwise use `available-default (unverified)`. An unverified default never authorizes a GPT-5.5 fallback while any GPT-5.6 route is selectable.

For continued or delegated execution, atomically `claim` before project work, then supply both `route_id` and `segment_id` when recording the outcome. A same-turn local `apply-fast-v1` Segment skips the claim because it cannot replay. The ledger derives stable event IDs and rejects repeated natural keys. If `claim` returns false, stop without tools or edits. Legacy whole-task events remain readable but do not affect Segment proportions or retuning.

## Query rules

Report three independent views:

1. **Actual Segment execution ratio:** non-cancelled segmented `execution` attempts backed by task metadata or user confirmation, grouped by exact model. This is the answer to “各模型实际使用比例”. Also show model × effort. One Segment is one attempt; do not add a second whole-request event for the same work.
   When verified, also group Segment attempts by model × active concurrency. Keep `parallel_plan` configured ratios separate from actual execution.
2. **Analysis ratio:** `skill_run` events grouped by analysis model. Keep this separate so router invocations do not distort implementation usage.
3. **Recommended ratio:** the newest `allocation` event. Label it planned, not actual.

Show counts with percentages. Report success and pressure within comparable task-class/model/effort groups. If there are fewer than five confirmed attempts, label the ratio as an early sample. If there are none, say there is insufficient observed data.

Show total verified parallel wall clock, cumulative worker duration, and peak concurrency only from schema-v2 `parallel_execution`. Coarse work estimates, plan creation time, and aggregate values supplied by model text are not runtime evidence.

Derive the effective parallel factor and utilization from verified runs using canonical wall clock (first worker confirmed started through last result received). These describe observed overlap and slot use without needing a serial baseline. Never display obsolete compression metrics; do not call either metric actual speedup.

## Retuning rules

- Prefer observed outcomes and durations over heuristic allocation.
- Raise only after at least 5 comparable attempts and at least 40% failed, escalated, or reworked outcomes.
- Lower only after at least 10 comparable attempts, at least 90% completion, no failed/escalated/reworked outcomes, and deterministic verification.
- Do not compare durations across substantially different task classes as if they were equivalent.
- Preserve the old recommendation in history by appending a new allocation; never rewrite old JSONL events.
- Record availability fallbacks so later queries can distinguish intentional routing from forced substitution.
- For GPT-5.5, require `fallback_reason=gpt56-family-unavailable`; do not record 5.5 as a valid fallback when Sol, Terra, or Luna remained selectable.

The script validates enums and durations, assigns event IDs, deduplicates supplied event IDs, locks concurrent reads/writes, skips malformed lines with warnings, and never rewrites ledger history.

Use:

- `claim --ledger <path> --route-id <id> --segment-id <id> --attempt-id <id>` before Segment work.
- `parallel-plan --ledger <path> --route-id <id> --parallelism-source <source> --requested-max-parallelism <n> --effective-max-parallelism <n> --planned-worker-count <n> --model-plan '<json>'` for configured intent.
- `router_runtime.py worker-start --ledger <path> --route-id <id> --segment-id <id>` after dispatch confirmation.
- `router_runtime.py worker-finish --ledger <path> --route-id <id> --segment-id <id> --outcome <outcome>` after result receipt.
- The legacy `parallel-execution` CLI remains import-compatible, but its aggregate-only records are unverified and excluded.
- `efficiency --ledger <path> --route-id <id> --source task-metadata|user-confirmed ...` for observed routing overhead and blocking evidence.
- `summary --ledger <path>` for JSON aggregation.
- `record` or `allocation` for append-only updates.
- `render --ledger <path> --report <path>` to replace only the block between `<!-- MODEL_USAGE_START -->` and `<!-- MODEL_USAGE_END -->`. Never let an LLM edit that block directly.
