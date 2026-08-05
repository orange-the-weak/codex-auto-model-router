---
name: codex-auto-model-router
description: Recommend and execute an efficient GPT-5.6 Sol, Terra, or Luna route with low-through-max reasoning for Codex project work. Prefer bounded direct tool concurrency, but automatically create or reuse a model-specific leaf agent when route-fit benefit clearly exceeds startup and aggregation overhead; no extra user permission is required. Use for code changes, tests, reviews, routed implementation, model recommendations, usage queries, retuning, and requests to disable, exit, restore, or check this Skill for the current project. Use the legacy strict state machine only when the user explicitly requests strict ledger auditing. Never auto-select Ultra or create a new top-level Codex task.
---

# Codex Auto Model Router

Use the default fail-open benefit-gated path. Keep the coordinator on its current model, choose a recommended route once, and execute directly when that route is already sufficient or executor overhead would dominate. When a different model or effort provides clear route-fit benefit that outweighs bounded startup and aggregation cost, automatically create or reuse a model-specific leaf agent without asking for extra permission. A Router, ledger, model-capability, or executor-startup failure must not block ordinary project work.

Do not route simple questions, copy confirmation, explanation, or read-only lookup that needs no project execution. Do not commit, push, deploy, upload, or send messages unless the user separately requests it.

## Project exit and restore

If the user asks to exit, disable, stop using, restore, re-enable, or check this Skill for the current project, handle that request before normal routing:

- Exit: run `python3 <skill-dir>/scripts/router_lite.py project-disable --repository <project-root>`.
- Restore: run `python3 <skill-dir>/scripts/router_lite.py project-enable --repository <project-root>`.
- Status: run `python3 <skill-dir>/scripts/router_lite.py project-status --repository <project-root>`.

`project-disable` adds one managed `[[skills.config]]` entry to the trusted project's `.codex/config.toml`, preserves unrelated settings, and disables this Skill by its absolute `SKILL.md` path. Normal `decide`, `plan`, and `record` commands also inspect that entry and return `action=disabled` immediately, so an already-loaded task stops routing without waiting for a restart. Restart Codex before the next task so project configuration can prevent normal Skill loading. Do not edit global `~/.codex/config.toml` for a project exit. `--no-subagents` is only a per-command agent opt-out and is not a project exit.

After a successful exit, stop all Router classification, notices, delegation, reuse, planning, and ledger actions for that project. Only the explicit restore or status entry remains available. If Codex still injects already-loaded Skill text in the current conversation, do not treat that as permission to resume routing.

## Default workflow

1. Let `decide` check project exit state first. If it returns `action=disabled`, stop using this Skill for the project. Otherwise classify the smallest useful task with `task_kind=mechanical|ordinary|complex`, `risk`, `size`, and only material ambiguity, coupling, verification, consequence, latency, or prior-failure signals. Include a conservative `estimated_seconds` when the work is bounded enough to estimate.
2. Run `python3 scripts/router_lite.py decide ... --estimated-seconds <n>` once. Use only the documented enum values; compatibility aliases are fail-open protection, not preferred input. Pass `--no-subagents` only when the user explicitly disables child agents. Treat `recommended_route` as advice until a returned `delegate` or `reuse` action is actually dispatched and observed.
3. Show one line before execution in the language of the user's current request. Keep English as the only canonical template and translate it naturally when the request uses another language:
   - Local: `Codex auto route | Task: <name> | Recommendation: <model>/<effort> | Execution: current coordinator <model>/<effort> | No automatic switch: <execution_reason>`
   - Delegated: `Codex auto route | Task: <name> | Recommendation: <model>/<effort> | Execution: leaf agent <model>/<effort> | Switch reason: <execution_reason>`
   - Render `main-model-fixed-leaf-startup-cost-exceeds-benefit` as `main conversation model is fixed; leaf startup cost exceeds expected benefit`. Translate that explanation instead of exposing the machine token.
4. Execute by action:
   - `local`: continue in the coordinator. Do not claim that the recommended model or effort actually ran.
   - Directly run independent safe tool or process calls concurrently when their results do not determine one another and they do not share mutable files, build state, simulators, devices, approval boundaries, or external side effects. Prefer one programmatic tool call with bounded `Promise.all` orchestration when supported. This concurrency uses the coordinator's same model and reasoning effort and creates no child-agent UI entries. Keep reasoning-dependent steps sequential.
   - `native-ultra`: only after an explicit user request for Ultra; never add Router-managed parallelism.
   - `reuse` or `delegate`: use the returned model-specific leaf only when `delegation_gate.benefit_clear=true`. No separate permission question is required. Follow the bounded lifecycle below.
5. Prefer direct tool concurrency when it is enough. Call `router_lite.py plan` and collaboration lifecycle tools only for real independent reasoning work whose measured or conservatively estimated net benefit clears the gate.
6. Do not record a recommended route as actual model use. Record only verified execution metadata after an observed leaf run or when the current task's model is directly observed. Treat every ledger error as a non-blocking warning and normally omit it from the user response.

The coordinator never changes its own model. A leaf executor is a separate reasoning stream, not a model switch inside the current conversation, so there is no Restore step.

The Router still evaluates every applicable request. It may report `tiny-local-fast-path`, `tool-bound-local-fast-path`, `startup-aware-local-fast-path`, `route-benefit-not-proven`, or `subagents-disabled-by-user`. A recommendation never proves actual model use, and a user model override remains the preferred recommendation.

## Model gradient

Use the offline policy in `route_policy.py`; task evidence and explicit user overrides win.

- Luna/medium: deterministic mechanical work.
- Luna/high: ordinary bounded implementation and normal research.
- Luna/xhigh: large bounded scans or reviews with low-to-normal consequence.
- Luna/max: large deterministic deep work with low-to-normal consequence.
- Terra/high: explicit latency priority.
- Sol/low: explicit user override or compatibility testing only; never automatic.
- Sol/medium: bounded complex work.
- Sol/high: high ambiguity, coupling, or consequence.
- Sol/xhigh: classified reasoning/verification failure on complex work or explicit choice.

Never select Ultra automatically. Keep fallback inside GPT-5.6 whenever any GPT-5.6 executor is available. GPT-5.5 is allowed only after the complete GPT-5.6 family is proven unavailable, and that fallback must be disclosed once.

## Direct tool concurrency

Prefer concurrency without child agents when it can perform the work. Group only independent, safe, bounded tool or process calls. Start them together in one coordinator tool turn when the interface supports it, cap the batch to the observed tool/runtime capacity, collect all results, and then resume model reasoning once. Typical candidates are independent file reads, repository searches, metadata queries, and tests that do not share build state. Keep writes to overlapping paths, Git mutation, deployments, approval-requiring actions, and shared simulator/device/build resources serial.

Direct tool concurrency does not create a second reasoning stream. Every result is interpreted by the same coordinator model and effort. If one result determines the next command or requires semantic judgment, keep that sequence serial. Never describe concurrent commands as multi-model execution or claim speedup without a controlled serial comparison.

## Automatic benefit-gated subagent mode

Enter this mode automatically when the selected model or effort differs and route-fit, quality, latency, or resource benefit clearly exceeds bounded startup and aggregation overhead. The user does not need to grant separate permission: a leaf agent is a normal routing mechanism, not an external side effect. Honor an explicit request to avoid child agents by passing `--no-subagents` and staying local. The legacy `--allow-subagents` flag remains accepted only for caller compatibility and is not an authorization gate.

Run `router_lite.py decide ...` for a single routed leaf or `router_lite.py plan ...` for independent parallel reasoning. Use `reuse` and `delegate` only when the emitted benefit gate permits them. An explicit `agent_type` always requires `fork_turns="none"`; never combine it with full-history inheritance. Give each leaf a bounded self-contained capsule with the goal, relevant paths/decisions, acceptance, constraints, validation budget, stop condition, and at most one recovery attempt. When acceptance is proven, the leaf sends one final result and ends the current turn immediately. It must not continue validating, add commentary, or wait for parent confirmation. If elevated permission is required, the leaf returns a limited result instead of requesting approval.

If agent creation is rejected, violates the spawn contract, or reports a startup failure, continue locally within 15 seconds. Do not retry a contract mismatch, rebuild an envelope, or treat normal asynchronous execution as a startup failure. After a delegated or reused result is ready, call `router_lite.py record` once with observed execution metadata.

Before the coordinator sends its final response, enter a bounded finalization phase for the current task tree: stop new dispatch, disable reuse, clear the current-request reuse registry, and refresh live child status. Accept `completed`, `failed`, and `interrupted` as terminal. Interrupt every optional, superseded, or otherwise unneeded child that is still genuinely `running`, then refresh once after the interrupt. If a required result is still needed, wait for that result or complete it locally without duplicating writes, then interrupt the now-unneeded child. Do not send the parent final response until every child owned by this request is terminal. If interruption fails or status cannot be verified, report that limitation instead of claiming cleanup.

This cleanup is limited to the current task tree. Collaboration tools do not expose deletion of completed child-agent UI history, so never claim to remove or clear historical cards. Do not interrupt a completed child merely to change its display state.

### Agent parallelism safeguards

Use `router_lite.py plan --tasks-json ...` only when one request has real independent boundaries and the estimated net benefit clears the automatic gate. Agent parallelism requires:

- at least two ready tasks expected to take roughly 90 seconds each;
- independent acceptance criteria and non-overlapping write scopes;
- verified free worker capacity;
- expected overlap that exceeds agent startup and aggregation cost by both 30 seconds and 15% under the configurable planning estimate.

Use conservative first-action priors of 40 seconds for a fresh executor and 10 seconds for a compatible reused executor, plus 10 seconds initial coordination, 8 seconds for each additional back-to-back dispatch, and 10 seconds aggregation. Local black-box probes measured 31.3–31.6 seconds of fixed fresh-task context initialization, 35.5–39.6 seconds to a fresh first tool, and 2.7–9.4 seconds to a reused first tool; these are planning data, not a platform SLA. Pass only coordinator-prequalified candidates through `--reuse-candidates-json`. Two fresh 90-second tasks remain candidates, while two compatible reused 90-second tasks may clear the benefit gate.

Reuse is an in-memory optimization, never a persistent pool. Clear candidates on every new user request. Bind each candidate to exact request ID, repository realpath, permission fingerprint, sandbox fingerprint, model, and effort; boolean "same" claims are insufficient. Require an idle leaf with no pending tool call, an accepted result, released ownership, and explicit false attestations for interruption, failure, prior failure, independent review, authentication, deployment, external action, sensitive data, and high consequence. Missing or mismatched identity only rejects that candidate. Recheck immediately before `followup_task`; on a race, spawn fresh or continue locally. Allow two follow-ups per executor by default, and send a new self-contained capsule each time. Set `fresh_context_required` for blind or independent review.

`router_lite.py` emits coordination protocol only; it does not claim to call native collaboration tools. Treat `completed` as a normal terminal state and never interrupt it. Parent/UI state may lag behind a child terminal event: refresh live status after a wait update and once before the parent final response, and reconcile an observed child `task_complete` over a stale parent `running` label. A wait timeout alone is not a stall. Suggest `interrupt_agent` during execution only after that refresh while an executor remains `running` with no reasoning, tool, or test activity beyond the `last_activity`-based stall threshold. Every such activity refreshes the timer. A completed executor may still pass same-request reuse prequalification until parent finalization begins; finalization disables reuse, clears the registry, and makes every still-running unneeded child interruptible regardless of the ordinary stall threshold.

Default to at most four total tasks including the coordinator, then reduce to observed capacity. Do not create a waiting agent queue. Use the returned route-aware executor lanes. Order ready tasks longest-first, dispatch the complete initial batch immediately after one compact notice, and refill a compatible lane as soon as its result arrives. Do not insert ledger/state work or commentary between individual dispatches. Name agents from their content, not random or ordinal labels. If capacity is unknown, run one leaf as a probe or stay serial.

Mark every result required or optional before dispatch. Once all required results satisfy acceptance, stop optional stragglers that can no longer change the answer. Never downgrade a user-required source to optional. A failed source or tool gets at most one alternate recovery method by default, then returns a bounded limitation instead of open-ended probing.

Treat the supplied stop condition, validation budget, and recovery count as hard execution limits. Once acceptance is proven, return immediately; do not add redundant validation methods merely to increase confidence on a low-risk task.

The coordinator owns dependencies, conflicts, waiting, and aggregation. Leaf agents may not delegate. On the first failure, start nothing else, drain active agents, and continue locally only when doing so cannot duplicate or conflict with writes or external actions.

Before dispatch, render the canonical English notice in the user's current language: `Codex auto route | Concurrency: <total including coordinator> tasks | Scheduling: refill on completion`.

Before a reused follow-up, render the canonical English notice in the user's current language at most once per executor: `Codex auto route | Executor: reuse <name> | Model: <model> | Reasoning: <effort> | same-request follow-up`.

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

Lead with the project outcome. Mention the recommended route once, distinguish it from the observed current model, and report relevant checks and remaining project risk. Do not expose hashes, IDs, state gates, environment flags, model identity warnings, or ledger failures during normal successful work.
