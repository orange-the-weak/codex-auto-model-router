---
name: codex-auto-model-router
description: Select an efficient GPT-5.6 Sol, Terra, or Luna model and low-through-max reasoning for Codex project work, with optional useful parallel leaf agents and best-effort usage history. Use for code changes, tests, reviews, routed implementation, model recommendations, usage queries, and retuning. Default to the fail-open Lite path; use the legacy strict state machine only when the user explicitly requests strict ledger auditing. Never auto-select Ultra or create a new top-level Codex task.
---

# Codex Auto Model Router

Use Router Lite by default. Keep the coordinator on its current model, choose a route once, and execute through the current task or an explicitly selected leaf agent. A Router, ledger, model-capability, or agent-startup failure must not block ordinary project work.

Do not route simple questions, copy confirmation, explanation, or read-only lookup that needs no project execution. Do not commit, push, deploy, upload, or send messages unless the user separately requests it.

## Default workflow

1. Classify the smallest useful task with `task_kind=mechanical|ordinary|complex`, `risk`, `size`, and only material ambiguity, coupling, verification, consequence, latency, or prior-failure signals. Include a conservative `estimated_seconds` when the work is bounded enough to estimate.
2. Run `python3 scripts/router_lite.py decide ... --estimated-seconds <n>` once. Use its model, effort, action, and `agent_type` as authoritative advice; omit the estimate instead of inventing one.
3. Show one line before execution:
   `Codex 自动路由｜任务：<name>｜模型：<model>｜推理：<effort>｜<reason>`
4. Execute by action:
   - `local`: continue in the coordinator. Do not create an agent. Tiny mechanical work, deterministic tool-bound chains, and estimated work below the default 90-second delegation break-even stay local when the current verified GPT-5.6 route is an accepted route or fallback.
   - `delegate`: after the one visible routing line, immediately start exactly one bounded leaf agent with the returned `agent_type`. During a multi-task request, reuse an eligible idle leaf with the exact route through `followup_task`; otherwise spawn a fresh leaf. Do not insert file reads, ledger work, more planning, or per-leaf commentary before dispatch. Give it the goal, relevant paths/decisions, acceptance, constraints, validation budget, stop condition, and at most one recovery attempt unless the user requires more. Treat every fresh or reused capsule as self-contained: do not load global memory, unrelated project history, or extra sources unless the task explicitly requires them. Do not send a plan, hash, cursor, environment guard, ledger path, or full chat.
   - `native-ultra`: only after an explicit user request for Ultra; never add Router-managed parallelism.
5. If agent creation is explicitly rejected or reports a startup failure, continue locally within 15 seconds. Do not treat normal asynchronous execution as a startup failure. Do not rebuild an envelope, retry through another model, or expose internal routing diagnostics unless the requested action is dangerous.
6. After the project result is ready, call `router_lite.py record` when useful. Treat every ledger error as a non-blocking warning and normally omit it from the user response.

The coordinator never changes its own model for Lite execution, so Lite has no Restore step.

Lite still evaluates every applicable request. It may intentionally keep a sufficient current verified GPT-5.6 route and report `tiny-local-fast-path`, `tool-bound-local-fast-path`, or `startup-aware-local-fast-path`. A weaker current route never replaces the selected route, and a user model override always wins.

## Model gradient

Use the offline policy in `route_policy.py`; task evidence and explicit user overrides win.

- Luna/medium: deterministic mechanical work.
- Luna/high: ordinary bounded implementation and normal research.
- Luna/xhigh: large bounded scans or reviews.
- Luna/max: large deterministic deep work with low consequence.
- Terra/high: explicit latency priority.
- Sol/medium: bounded complex work.
- Sol/high: high ambiguity, coupling, or consequence.
- Sol/xhigh: classified reasoning/verification failure on complex work or explicit choice.

Never select Ultra automatically. Keep fallback inside GPT-5.6 whenever any GPT-5.6 executor is available. GPT-5.5 is allowed only after the complete GPT-5.6 family is proven unavailable, and that fallback must be disclosed once.

## Useful parallelism

Use `router_lite.py plan --tasks-json ...` only when one request has real independent boundaries. Automatic parallelism requires:

- at least two ready tasks expected to take roughly 90 seconds each;
- independent acceptance criteria and non-overlapping write scopes;
- verified free worker capacity;
- expected overlap that exceeds agent startup and aggregation cost by both 30 seconds and 15% under the configurable planning estimate.

Use conservative first-action priors of 40 seconds for a fresh executor and 10 seconds for a compatible reused executor, plus 10 seconds initial coordination, 8 seconds for each additional back-to-back dispatch, and 10 seconds aggregation. Local black-box probes measured 31.3–31.6 seconds of fixed fresh-task context initialization, 35.5–39.6 seconds to a fresh first tool, and 2.7–9.4 seconds to a reused first tool; these are planning data, not a platform SLA. Pass only coordinator-prequalified candidates through `--reuse-candidates-json`. Two fresh 90-second tasks remain candidates, while two compatible reused 90-second tasks may clear the benefit gate.

Reuse is an in-memory optimization, never a persistent pool. Clear candidates on every new user request. A candidate must belong to this request and repository, match model and effort exactly, use the same permissions and sandbox, be idle with no pending tool call, have a successful accepted result, and own no unresolved write scope or conflict key. Do not reuse an interrupted, failed, external-action, authentication, deployment, or sensitive-data leaf. Recheck immediately before `followup_task`; on a race, spawn fresh or continue locally. Allow one follow-up per executor by default, and send a new self-contained capsule to limit context contamination.

Default to at most four total tasks including the coordinator, then reduce to observed capacity. Do not create a waiting agent queue. Use the returned route-aware executor lanes. Order ready tasks longest-first, dispatch the complete initial batch immediately after one compact notice, and refill a compatible lane as soon as its result arrives. Do not insert ledger/state work or commentary between individual dispatches. Name agents from their content, not random or ordinal labels. If capacity is unknown, run one leaf as a probe or stay serial.

Mark every result required or optional before dispatch. Once all required results satisfy acceptance, stop optional stragglers that can no longer change the answer. Never downgrade a user-required source to optional. A failed source or tool gets at most one alternate recovery method by default, then returns a bounded limitation instead of open-ended probing.

Treat the supplied stop condition, validation budget, and recovery count as hard execution limits. Once acceptance is proven, return immediately; do not add redundant validation methods merely to increase confidence on a low-risk task.

The coordinator owns dependencies, conflicts, waiting, and aggregation. Leaf agents may not delegate. On the first failure, start nothing else, drain active agents, and continue locally only when doing so cannot duplicate or conflict with writes or external actions.

Before dispatch, show:
`Codex 自动路由｜并发：<total including coordinator> 个任务｜调度：完成即补位`

Before a reused follow-up, show at most once per executor:
`Codex 自动路由｜执行器：复用 <name>｜模型：<model>｜推理：<effort>｜同请求内续派`

At completion, summarize concurrency only from observed timing. Never claim speedup without a controlled serial comparison.

## Strict compatibility mode

Use the legacy `route_policy.py` plus `router_runtime.py` state machine only when the user explicitly requests `strict routing`, strict ledger auditing, replay protection, or a reproducible routing experiment. Read [execution-state-machine.md](references/execution-state-machine.md), [preset-mapping.md](references/preset-mapping.md), and [usage-ledger.md](references/usage-ledger.md) first.

Strict mode may use hashes, claims, tickets, finish, and Restore. Even there, ledger failure after project completion is non-blocking. Never silently enter strict mode for normal code, build, test, review, or research work.

## Assess, Query, Record, Retune

- Assess and Retune use Sol/high unless the user overrides them. Save the full report to `docs/codex-model-routing-report.md`; keep chat output brief.
- Query and Record use local scripts and never create agents.
- Use [routing-criteria.md](references/routing-criteria.md) when changing model assignments and [benchmark-evidence.md](references/benchmark-evidence.md) when changing evidence-derived lanes.
- Use [usage-ledger.md](references/usage-ledger.md) for historical summaries. Recommendations are not proof of actual model use.

## User-facing result

Lead with the project outcome. Mention the selected route once, relevant checks, and remaining project risk. Do not expose hashes, IDs, state gates, environment flags, model identity warnings, or ledger failures during normal successful work.
