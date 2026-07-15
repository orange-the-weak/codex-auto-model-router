---
name: codex-auto-model-router
description: Deterministically analyze, apply, query, record, and retune project model routing inside Codex. For Apply, create the smallest useful sequence of bounded task segments and automatically select GPT-5.6 Sol, Terra, or Luna plus low, medium, high, or xhigh reasoning for each segment; prefer native same-task overrides, continue segments in the same Codex task, restore the original route afterward when known, and fall back to an explicitly selectable subagent or the current model. Maintain a Markdown report and validated per-segment usage history. Use when the user invokes $codex-auto-model-router, asks which model should handle project work, requests dynamically routed implementation, queries usage ratios, records outcomes, or retunes assignments. Never create a new top-level Codex task.
---

# Codex Auto Model Router

Route simple requests as one segment. Split an Apply request only when distinct dependent stages materially benefit from different models or reasoning levels. Run the segments in order inside the same Codex task, stop on failure, and restore the verified original route once at the end. Skip switches whose latency would exceed their value. Query and Record stay local and fast. Never add API integration, estimate API spend, create a top-level Codex task, or commit/push unless the user separately requests it.

Run `scripts/route_policy.py` before Assess, Retune, or Apply. For Apply, pass a JSON segment plan with `--segments-json`. Read [execution-state-machine.md](references/execution-state-machine.md) for segment envelopes and transitions, [preset-mapping.md](references/preset-mapping.md) before custom-agent fallback, [usage-ledger.md](references/usage-ledger.md) before writing history, and [routing-criteria.md](references/routing-criteria.md) for model selection and efficiency estimates.

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
5. For Apply, create the smallest necessary linear segment plan, validate it with the policy script, then execute the returned plan without changing it.

## Apply segment planning

Use one segment by default. Add a boundary only when the next stage has a different objective, verification contract, or sufficient route. Common useful boundaries are analysis, implementation, deterministic verification, and high-risk review; do not add all four mechanically.

Each candidate segment must contain:

- `segment_id`: lowercase stable identifier unique within `route_id`
- `goal`: bounded work owned only by this segment
- `depends_on`: empty for the first segment, otherwise exactly the previous segment ID
- `task_kind`: `mechanical`, `ordinary`, or `complex`
- `risk`: `low`, `normal`, or `high`
- `size`: `tiny`, `normal`, or `large`
- `acceptance`: one or more concrete completion checks
- `validation_budget`: the maximum proportionate verification work
- optional segment-specific `model`, `effort`, and `route_source=report|user-override`; whole-request user overrides take precedence over report routes

Pass the JSON array to `scripts/route_policy.py --mode apply --segments-json '<json>'`. When the user sets a limit, add `--max-segments 1..8` and/or `--max-switches 1..8`; one supplied value applies to both dimensions unless both are supplied. A global saved-report route is valid only for a one-segment plan; for multi-segment plans, attach each matching report route to its segment. Treat the returned order, budgets, selected routes, dispatch values, `route_id`, `plan_hash`, per-segment `attempt_id`, and Restore decision as authoritative.

Adaptive budgets:

- Use the standard budget of four routed segments and four switches including final Restore.
- Expand automatically to six segments and six switches only when the normalized plan exceeds 4/4 and contains a concrete `task_kind=complex` or `size=large` basis. High risk alone does not expand the budget.
- Honor a user budget from 1 to 8. Eight segments and eight switches are absolute hard limits; never create an unbounded chain.
- Store `segment_budget`, `switch_budget`, and `budget_source=standard|adaptive-extended|user-override` in the immutable plan and envelope.
- Merge adjacent segments with the same model and effort.
- Keep a tiny mechanical segment on the current or previous route unless the user explicitly overrides it.
- Reject branches, cycles, non-linear dependencies, duplicate IDs, and conflicting overrides.
- Never re-plan after execution begins. A failed segment stops the chain; do not retry it by cycling through models.
- Do not add a review segment unless risk, ambiguity, or the user requires an independent review.

## Capability check and Dispatch

Use this order once for the complete plan:

1. Search available Codex task tools for `send_message_to_thread` (normally `codex_app__send_message_to_thread`). Use native same-task chaining only when the interface explicitly accepts `model` and `thinking`. Never call a thread/task creation capability. Use only the verified `current.thread_id` returned from `CODEX_THREAD_ID` metadata.
2. If the original model and effort are verified, execute a locally matched first segment or send the first mismatched segment to the same task with its exact model and effort. Each successful segment sends at most one follow-up for the next segment. This is intentional bounded continuation, not recursive planning.
3. If persistent same-task switching is unsafe or unavailable, execute segments sequentially through explicitly model-selectable executor presets when the subagent interface proves the selection. A task/agent name alone is not proof of model selection.
4. Otherwise execute the plan locally with the current model. Keep low-risk fallback silent, disclose high-risk fallback once, and never claim the configured route actually ran.

Never make a persistent same-task switch when the original model or effort is unknown. The policy returns `selectable-subagent-or-local` in that case.

## Segment envelope

Every same-task Apply continuation carries:

- `ROUTE_PROJECT_MODELS_ROUTED_TURN=1` and `ROUTED_MODE=APPLY_SEGMENT`
- one immutable `route_id`, protocol version, complete normalized plan, selected Segment/switch budgets and source, `plan_hash`, zero-based current cursor, and per-segment `attempt_id`
- current `segment_id`, index, selected model/effort, goal, dependencies, acceptance, and validation budget
- verified `original_model` and `original_effort`
- repository, report, and ledger paths
- accumulated completed-segment results and changed-file summary

Do not include unrelated future implementation details beyond the normalized plan. End the current turn after the next same-task continuation is accepted.

## Visible routing protocol

Immediately before every Assess, Retune, Apply segment, Query, or Record, show one compact commentary line:

`Codex 自动路由｜Segment <index>/<total>：<task segment>｜模型：<model|current-route>｜推理：<low|medium|high|xhigh|none|keep>｜<reason>`

- This means Codex automatically selected the route; never use an ambiguous bare `路由提示` label.
- Show the line once per executed segment, not once per command or file.
- For a one-segment request, use `Segment 1/1`.
- For a tiny segment kept local, say `Segment 较小，Codex 保持当前模型以避免切换延迟`.
- Label a configured route as configured, not observed, when reliable metadata is unavailable.
- A normal successful completion needs no separate model-identity or runtime-verification warning.
- Only for a high-risk fallback, show: `Codex 自动路由状态｜目标：<model/effort>｜当前对话不支持带模型续接，已用当前可用模型继续｜<reason>`.

## Routed Apply segment

When `ROUTED_MODE=APPLY_SEGMENT`:

1. Run `scripts/route_policy.py --validate-envelope-json '<json>'` to validate `route_id`, protocol, selected budgets and source, `plan_hash`, zero-based cursor, `segment_id`, `attempt_id`, original route, and the exact ordered list of completed Segment IDs. Never classify, plan, split, delegate, or change a later route.
2. Before any project tool or edit, run `scripts/model_usage_ledger.py claim` with the ledger path, `route_id`, `segment_id`, and `attempt_id`. If `claimed=false`, treat the envelope as a replay and stop without executing or advancing. If the ledger is unavailable, do not persistently chain this Segment; use an isolated executor or local fallback so replay cannot duplicate parent-task side effects.
3. Show the segment's visible routing line, then execute only its goal. Read applicable repository instructions, preserve unrelated changes, and stay within its validation budget.
4. Run `scripts/route_policy.py --inspect-current`. Record one `execution` event for this segment only when metadata matches the selected model/effort or the user confirms it. Include `route_id` and `segment_id`; the ledger derives a stable event ID so a replay cannot double-count the Segment. Never record a configured target as actual use.
5. On failure, record the verified outcome when possible, stop all remaining segments, and enter Restore with a concise partial result. Do not silently retry with another route.
6. On success, append the bounded result and changed-file summary to the accumulator. If another segment exists, send exactly one same-task continuation with the next model/effort and cursor, then end the turn.
7. After the final segment, run proportionate final checks only if they were assigned to that segment, then enter Restore.

`ROUTED_MODE=APPLY_ONESHOT` follows the same rules as a plan containing exactly one segment and cannot create another implementation segment.

## Executor fallback path

An executor preset requires `ROUTE_PROJECT_MODELS_EXECUTOR=1`, `route_id`, and `segment_id`. Execute only that bounded segment, do not route or delegate, and return status, changed files, checks, remaining risks, and exposed runtime model metadata to the coordinator. The coordinator alone advances the cursor. Read [preset-mapping.md](references/preset-mapping.md) for exact names.

## Query and Record fast path

Before Query or Record, use the visible line with `local-script` and `none`.

- Record the invocation as `skill_run` with the matching mode.
- Query runs `summary`, then `render` to update only the marked report section.
- Record appends only user-confirmed or reliable task-metadata execution, then summarizes and renders.
- Report actual execution proportions as verified Segment attempts, separate from analysis calls and latest recommended allocation.
- Never infer actual use from a recommendation or configured-but-unverified route.

## Routed Assess and Retune

Perform only the requested read-only analysis. Save the report to `<repository>/docs/codex-model-routing-report.md`, maintain `<repository>/.codex/model-routing-history.jsonl`, and enter Restore. Do not implement project work or recursively dispatch.

## Restore and Return

- Preserve the original model and effort from the Coordinator envelope; never replace them with an intermediate segment route.
- If the final/failed segment is already on the verified original route, return the accumulated result directly; it is already restored.
- Otherwise, after success or failure, if a persistent switch occurred and both original values are known, make exactly one Restore continuation with the original `model` and `thinking`, `ROUTED_MODE=RETURN`, the same `route_id`, and the accumulated result.
- If restoration is rejected, do not loop. Mention it only for high-risk work or when the user asks for an audit.
- `RETURN` is terminal: perform no tools, edits, tests, assessment, delegation, ledger writes, segment advancement, or additional routing.

## Assessment and routing principles

Inventory representative project evidence without builds or tests. Route each recurring task by ambiguity, scope, coupling, verification difficulty, and consequence of error. Luna fits mechanical, repetitive, locally verifiable work; Terra fits ordinary bounded engineering; Sol fits ambiguity, deep coupling, novelty, or high consequence. All three default to medium unless evidence supports low, high, or xhigh. Prefer a bounded segment over higher effort.

## Report and ledger output

Lead the report with the default route and state the actual analysis route separately. Include task evidence, model, effort, reason, upgrade trigger, fast path, Sol-only cases, dynamic segment examples, efficiency estimate, usage proportions, and confidence gaps. The efficiency estimate must state its baseline, task mix, switching overhead, calculation, `预计增效：约 X–Y%`, highest-impact optimization, and whether it is heuristic or measured.

Under `## Usage proportions`, include exactly one empty marker pair:

`<!-- MODEL_USAGE_START -->`

`<!-- MODEL_USAGE_END -->`

The ledger script owns the marker contents. Retune raises only after at least 5 comparable attempts with at least 40% failure/escalation/rework pressure, and lowers only after at least 10 attempts with at least 90% completion, deterministic verification, and no pressure events. The chat result stays brief: completion, key optimizations, checks, remaining risk, and report link when applicable.
