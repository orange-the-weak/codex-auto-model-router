# Usage ledger

Store project-local history at `.codex/model-routing-history.jsonl`. Keep one compact JSON object per line. Do not store prompts, source code, secrets, or conversation text.

## Event types

- `segment_claim`: one atomic pre-execution claim with `route_id`, `segment_id`, `attempt_id`, and optional `task_id`. The first append wins; a repeated claim means the envelope was already consumed and must not execute again.
- `skill_run`: one invocation. Fields: `event_id`, `timestamp`, `mode`, `analysis_model`, `effort`, and optional fallback fields.
- `execution`: one confirmed Segment attempt. Fields: `event_id`, optional `task_id`, optional `route_id`, optional `segment_id`, `timestamp`, `model`, `effort`, `task_class`, `outcome`, optional non-negative `duration_seconds`, `source`, `verification` (`deterministic`, `manual`, `none`, or `unknown`), and fallback fields. Older records without Segment identifiers remain valid and are treated as whole-task attempts.
- `parallel_plan`: configured intent for one `dependency-parallel-v1` route. Fields: `route_id`, `protocol`, `parallelism_source` (`standard`, `smart-reduced`, or `user-override`; legacy `adaptive-extended` remains readable), `requested_max_parallelism`, `effective_max_parallelism`, `planned_worker_count`, and `model_plan`. This is never actual use or timing.
- `parallel_execution`: one verified parallel run. Fields: `route_id`, `wall_clock_seconds`, `cumulative_worker_seconds`, `peak_concurrency`, `worker_count`, `outcome`, and reliable `source`.
- `allocation`: one recommended snapshot. Fields: `event_id`, `timestamp`, `basis`, and `allocation`, whose percentages total 100.

Use `source=user-confirmed` when the user supplies actual usage and `source=task-metadata` only when Codex exposes reliable metadata. Never convert a recommendation into an `execution` event. Use exact model names when known; otherwise use `available-default (unverified)`. An unverified default never authorizes a GPT-5.5 fallback while any GPT-5.6 route is selectable.

For segmented execution, atomically `claim` before any project work, then supply both `route_id` and `segment_id` when recording the outcome. The ledger derives stable event IDs and rejects repeated natural keys for both claims and executions. If `claim` returns false, stop without tools or edits because that Segment envelope was already consumed. Legacy whole-task events without either identifier remain readable but are reported separately and do not affect Segment proportions or automatic retuning.

## Query rules

Report three independent views:

1. **Actual Segment execution ratio:** non-cancelled segmented `execution` attempts backed by task metadata or user confirmation, grouped by exact model. This is the answer to “各模型实际使用比例”. Also show model × effort. One Segment is one attempt; do not add a second whole-request event for the same work.
   When verified, also group Segment attempts by model × active concurrency. Keep `parallel_plan` configured ratios separate from actual execution.
2. **Analysis ratio:** `skill_run` events grouped by analysis model. Keep this separate so router invocations do not distort implementation usage.
3. **Recommended ratio:** the newest `allocation` event. Label it planned, not actual.

Show counts with percentages. Report success and pressure within comparable task-class/model/effort groups. If there are fewer than five confirmed attempts, label the ratio as an early sample. If there are none, say there is insufficient observed data.

Show total verified parallel wall clock, cumulative worker duration, and peak concurrency only from `parallel_execution`. Coarse work estimates, plan creation time, claim time, and ledger append timestamps are not runtime evidence. Do not infer worker start or stop times.

Derive `effective_parallel_factor = cumulative_worker_seconds / wall_clock_seconds` and worker-time compression from verified parallel runs. Label both as effective concurrency measurements, not controlled serial A/B speedup. Report actual speedup only when a comparable serial wall-clock baseline is independently verified.

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
- `parallel-execution --ledger <path> --route-id <id> --wall-clock-seconds <s> --cumulative-worker-seconds <s> --peak-concurrency <n> --worker-count <n> --outcome <outcome> --source <source>` only for verified runtime evidence.
- `summary --ledger <path>` for JSON aggregation.
- `record` or `allocation` for append-only updates.
- `render --ledger <path> --report <path>` to replace only the block between `<!-- MODEL_USAGE_START -->` and `<!-- MODEL_USAGE_END -->`. Never let an LLM edit that block directly.
