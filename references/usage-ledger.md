# Usage ledger

Store project-local history at `.codex/model-routing-history.jsonl`. Keep one compact JSON object per line. Do not store prompts, source code, secrets, or conversation text.

## Event types

- `segment_claim`: one atomic pre-execution claim with `route_id`, `segment_id`, `attempt_id`, and optional `task_id`. The first append wins; a repeated claim means the envelope was already consumed and must not execute again.
- `skill_run`: one invocation. Fields: `event_id`, `timestamp`, `mode`, `analysis_model`, `effort`, and optional fallback fields.
- `execution`: one confirmed Segment attempt. Fields: `event_id`, optional `task_id`, optional `route_id`, optional `segment_id`, `timestamp`, `model`, `effort`, `task_class`, `outcome`, optional non-negative `duration_seconds`, `source`, `verification` (`deterministic`, `manual`, `none`, or `unknown`), and fallback fields. Older records without Segment identifiers remain valid and are treated as whole-task attempts.
- `allocation`: one recommended snapshot. Fields: `event_id`, `timestamp`, `basis`, and `allocation`, whose percentages total 100.

Use `source=user-confirmed` when the user supplies actual usage and `source=task-metadata` only when Codex exposes reliable metadata. Never convert a recommendation into an `execution` event. Use exact model names when known; otherwise use `available-default (unverified)`.

For segmented execution, atomically `claim` before any project work, then supply both `route_id` and `segment_id` when recording the outcome. The ledger derives stable event IDs and rejects repeated natural keys for both claims and executions. If `claim` returns false, stop without tools or edits because that Segment envelope was already consumed. Legacy whole-task events without either identifier remain readable but are reported separately and do not affect Segment proportions or automatic retuning.

## Query rules

Report three independent views:

1. **Actual Segment execution ratio:** non-cancelled segmented `execution` attempts backed by task metadata or user confirmation, grouped by exact model. This is the answer to “各模型实际使用比例”. Also show model × effort. One Segment is one attempt; do not add a second whole-request event for the same work.
2. **Analysis ratio:** `skill_run` events grouped by analysis model. Keep this separate so router invocations do not distort implementation usage.
3. **Recommended ratio:** the newest `allocation` event. Label it planned, not actual.

Show counts with percentages. Report success, pressure, median duration, and P75 duration within comparable task-class/model/effort groups. If there are fewer than five confirmed attempts, label the ratio as an early sample. If there are none, say there is insufficient observed data.

## Retuning rules

- Prefer observed outcomes and durations over heuristic allocation.
- Raise only after at least 5 comparable attempts and at least 40% failed, escalated, or reworked outcomes.
- Lower only after at least 10 comparable attempts, at least 90% completion, no failed/escalated/reworked outcomes, and deterministic verification.
- Do not compare durations across substantially different task classes as if they were equivalent.
- Preserve the old recommendation in history by appending a new allocation; never rewrite old JSONL events.
- Record availability fallbacks so later queries can distinguish intentional routing from forced substitution.

The script validates enums and durations, assigns event IDs, deduplicates supplied event IDs, locks concurrent reads/writes, skips malformed lines with warnings, and never rewrites ledger history.

Use:

- `claim --ledger <path> --route-id <id> --segment-id <id> --attempt-id <id>` before Segment work.
- `summary --ledger <path>` for JSON aggregation.
- `record` or `allocation` for append-only updates.
- `render --ledger <path> --report <path>` to replace only the block between `<!-- MODEL_USAGE_START -->` and `<!-- MODEL_USAGE_END -->`. Never let an LLM edit that block directly.
