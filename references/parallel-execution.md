# Benefit-gated subagent parallel execution protocols

Use this reference when automatic routing identifies independent reasoning work whose model-route or overlap benefit clearly exceeds bounded executor startup and aggregation overhead. Ordinary concurrency still uses bounded direct tool or process calls in the coordinator, shares the current model and reasoning effort, and creates no child agents.

The benefit-gated subagent path passes direct bounded tasks to selected leaf agents, tracks live agents with the native task interface, refills a free slot when any result arrives, and records analytics only after the project result. It does not create route hashes, claims, tickets, ledgers, or a waiting agent queue. Agent parallelism requires at least two independent tasks of roughly 90 seconds, non-overlapping writes, verified free capacity, and estimated net benefit after cold start, dispatch, aggregation, and tail imbalance; otherwise stay serial. No extra user permission prompt is required, but `--no-subagents` is an explicit opt-out. Each task declares whether its result is required and defaults to one alternate recovery attempt. After all required acceptance checks pass, cancel optional stragglers that cannot change the answer.

## Explicit-mode activation gate

`router_lite.py decide --estimated-seconds N` may delegate automatically when its `delegation_gate.benefit_clear` value is true. `--no-subagents` forces local execution and suppresses reuse or spawn contracts. The legacy `--allow-subagents` flag remains accepted only for wrapper compatibility.

Fresh and reused executors have different costs. Three current Codex App probes measured fresh context materialization at 31.3–31.6 seconds, fresh session-to-first-tool at 35.5–39.6 seconds, and same-agent follow-up-to-first-tool at 2.7–9.4 seconds. `router_lite.py plan` therefore uses conservative configurable priors of 40 seconds for a fresh first action and 10 seconds for a reused first action, plus 10 seconds initial coordination, 8 seconds per additional back-to-back dispatch, and 10 seconds aggregation. The sample is small and local; these values are planning priors, not platform guarantees.

The coordinator may pass `--reuse-candidates-json` to either `decide` or `plan` only after qualifying each candidate from the live task interface. Bind the call and candidate to exact request ID, repository realpath, permission fingerprint, sandbox fingerprint, model, and effort; boolean "same" claims are not identity. The candidate also includes `followups_used`, positive idle/result/ownership attestations, and explicit false values for pending tools, interruption, failure, prior failure, independent review, authentication, deployment, external action, sensitive data, and high consequence. It is not persistent state. Missing or mismatched identity makes only that candidate ineligible. Clear the registry when a new user request starts. Once parent finalization begins, disable reuse and interrupt every no-longer-needed child still genuinely running before the final response.

Router Lite returns coordination protocol rather than performing native collaboration calls. `completed` is a normal terminal state: accept its result and never interrupt it merely because the executor is no longer reusable. Parent/UI state can lag behind the child, so refresh live status after wait updates; an observed child `task_complete` reconciles stale parent `running` to completed. A wait timeout is not itself a stall. During normal execution, only `running` after refresh and beyond the configured `last_activity` threshold is interruptible. Continuing reasoning, tool calls, and tests reset that timer.

Parent finalization is a separate bounded phase. Stop new dispatch, disable reuse, clear the current-request registry, refresh the current task tree, interrupt every optional, superseded, or otherwise unneeded child still genuinely `running`, and refresh once after interruption. Required children either return their result or become unnecessary after a safe local takeover before interruption. Do not finalize until every child owned by the current request is terminal. This protocol cannot operate on another task tree and cannot delete completed child-agent UI history because no collaboration deletion operation is exposed.

`decide` may return `reuse` for an exact-route eligible executor, including a sequential task that would otherwise stay on a stronger sufficient coordinator route solely because it is below the 90-second fresh-start threshold. Reuse uses the 10-second prior; tiny and tool-bound local fast paths remain local when sufficient. The planner assigns tasks to route-aware executor lanes. A matching candidate or compatible completed lane pays the reused prior; a new lane, route change, exhausted allowance, or exclusion pays the fresh prior. Two follow-ups per executor are the default. Before `followup_task`, recheck identity, live state, and ownership; a race falls back fresh or local without a state gate. Every follow-up receives a new self-contained capsule and must not rely on prior conclusions.

Planning still requires at least 30 seconds and 15% benefit against estimated serial work. Two fresh 90-second tasks remain below the gate; two independently qualified reused 90-second tasks may pass. The result exposes `dispatch_now`, `executor_lanes`, activation counts, and `reuse_policy`, and labels its estimate `planning-only-not-measured-speedup`.

After one compact visible notice, launch every `dispatch_now` task without intervening reads, state gates, ledger writes, repeated commentary, or additional planning. Refill a released compatible lane immediately through the existing task; otherwise start fresh only when the planned benefit remains positive. This removes coordinator-created gaps without mistaking normal asynchronous startup for failure.

The `dependency-parallel-v1` protocol below is legacy strict mode. Use it only when the user explicitly requests strict ledger auditing, replay protection, or a reproducible routing experiment.

`dependency-parallel-v1` adds bounded leaf executors without changing `segmented-v1`.

## Plan fields

Each Segment requires an explicit content-based `segment_id` and keeps the existing route, acceptance, validation budget, and deterministic `attempt_id`, plus:

- `depends_on`: zero or more earlier Segment IDs;
- `work_estimate`: `short`, `normal`, or `long` planning weight, never observed timing;
- `access_mode`: `read` or `write`;
- `write_scopes`: concrete repository-relative paths required for writes;
- `conflict_keys`: shared mutable resources such as `git-index`, a lockfile, project file, migration target, deployment target, or shared simulator;
- `declared_dependencies`: the pre-conflict dependency list used to rebuild and verify automatic serialization;
- resulting coarse `critical_path_work`.
- `agent_task_name`, deterministically derived from the content-based `segment_id` by replacing `-` with `_`, for the Codex leaf-agent creation call. It must match `[a-z0-9_]+`; do not invent random or ordinal Router names.

The parallel object stores contract version 2, `parallelism_source=standard|smart-reduced|user-override`, requested/effective concurrency, planning capacity, `dispatch_capacity_policy=immediate-observation-or-single-probe`, coordinator reservation, scheduler, priority order, aggregation order, conflicts, and `stop-dispatch-drain-running`. These are hashed with the full coordinator plan. Validation independently checks the fixed protocol fields and GPT-5.6 task schema, then rebuilds conflict dependencies and `serialized_conflicts` from declared dependencies, resolved repository-relative write scopes, and conflict keys. On first accepted begin, runtime state atomically binds `route_id` to `plan_hash`, protocol, and contract version; every later gate checks that anchor, so a caller-recomputed hash cannot legalize altered semantics or downgrade a v2 route to legacy.

The mutable dispatch-capacity observation is never inserted into `plan_hash`. The Python CLI cannot independently attest Codex slot metadata: the Coordinator may pass `--trusted-dispatch-capacity-json` only when the current task interface actually exposes a live total/running-slot snapshot. New `prepare-dispatch` observations use schema v2 and bind `route_id`, `plan_hash`, and a one-use `observation_id`; reusing it cannot authorize another batch. A source string, documented default, or remembered capacity is not evidence; omit the argument and use one safe probe otherwise. Genuine legacy envelopes remain readable only when the route's first trusted binding records no contract version.

## Normalization

1. Reject missing, duplicate, ordinal-only (`segment-1`, `worker-2`, and similar), forward/unknown dependencies, invalid enums, or more than 16 candidates.
2. Route every candidate independently to GPT-5.6 Sol, Terra, or Luna and effort.
3. Merge at most three short siblings only when they share an explicit semantic `merge_group`, route source, complete task evidence, predecessors, successors, access mode, and conflict keys, and their write scopes are disjoint.
4. Require concrete write scopes. Resolve each to its real path under the repository before hashing and comparison; reject escapes. Add an earlier-to-later dependency for overlapping real write scopes or shared conflict keys.
5. Enforce the existing routed Segment budget: 4 standard, 6 only for a complex/large basis, or user override through the absolute limit of 8.
6. Set automatic requested concurrency to 4. Compute `available_worker_slots = observed_total_slots - coordinator_slots - running_workers`, then `effective=min(requested, available_worker_slots, useful independent width)`. Four total Codex slots normally mean one coordinator plus a peak of three parallel tasks.
7. Without observed capacity, begin with one task and refill only after a free slot is confirmed. A user value above 4 requires observed free-task capacity and matching useful width. Never use a documented/default limit to authorize expansion.

Do not split a long task merely to fill slots. Split it only when independently executable boundaries have separate dependencies, acceptance checks, and non-conflicting ownership.

## Dispatch and wait-any

The Coordinator is the sole scheduler. It passes the full plan once to `router_runtime.py prepare-dispatch`. Runtime persists the canonical plan, validates the current frontier and immediate capacity, atomically reserves a bounded ready batch, and returns hash-bound `dispatch-ticket-v1` capsules. A ticket contains the selected route, bounded goal, ownership, checks, immutable IDs, and hash—never the full plan or a second copy of concurrency metadata.

Launch only that batch. Each executor calls `router_runtime.py attach` with the ticket identity before project tools; attachment reads persisted state and does not reconstruct the plan or require an ambient shell marker. `worker-start` turns the prepared state into dispatch-confirmed. Before that boundary only, the same ticket may recover an interrupted launch. Executors stay within ownership and never plan, route, advance, or delegate.

If a recovered outstanding ticket appears after coordinator interruption, first query live agents by its stable `agent_task_name`. Reuse the matching execution instead of spawning a duplicate; spawn only when no matching task exists, then capture `worker-start` immediately.

When any parallel task returns, the Coordinator calls `worker-finish` and `finish` immediately. `finish` atomically stores the worker's bounded structured `handoff` in the route result inbox. A dependent executor receives only its declared dependency handoffs from `attach`, so the Coordinator does not repeat large result prose. If the completed worker releases a slot and makes a dependent node ready, `finish` returns one hash-bound continuation ticket; dispatch it before commentary. Use `prepare-dispatch --route-id ...` only to recover tickets or fill additional slots backed by a fresh observation. There is no wave barrier or pre-created executor queue. Final reporting follows normalized Segment order, not arrival order.

At the first failed task, atomically persist a route-level stop latch, stop dispatching new tasks, and drain all already-running tasks. Preserve their verified results, mark undispatched work skipped, and aggregate deterministically. Later claims for that route must fail. Do not retry through another model.

## Ledger evidence

The default Apply brief is current-run only. Query/history output is explicitly labeled a historical aggregate. Canonical elapsed time uses the coordinator's monotonic clock from first dispatch confirmation through last result receipt.

- `parallel_plan` records configured intent: protocol, `parallelism_source`, requested/effective caps, planned task count, and planned model counts.
- Each verified Segment `execution` may record the real active `concurrency` when task metadata or the user confirms it.
- `parallel_worker_start` and `parallel_worker_finish` record runtime-captured monotonic boundaries for each Segment.
- Schema-v2 `parallel_execution` stores every task interval and derives actual elapsed time, cumulative parallel-task duration, task overlap, orchestration gaps, peak concurrency, and task count from them.

Call `router_runtime.py worker-start` with `route_id + plan_hash + segment_id + attempt_id` immediately after a dispatch is confirmed and `worker-finish` with the same identity immediately after its result is received. Neither command accepts timing numbers. At the terminal aggregate, `finish` reads those events and writes at most one verified run. Missing, reversed, mismatched, or incomplete traces stay `pending`; aggregate-only legacy records remain readable but never enter verified metrics.

Use the returned `parallel_execution_brief` verbatim in the Apply response. Do not independently calculate or format the line.

Before dispatch, keep the visible plan compact and match the user's current language. Chinese: `Codex 自动路由｜并发计划：<N> 个任务（含主任务）｜来源：<source>｜调度：关键路径优先`. English: `Codex auto route | Parallel plan: <N> tasks including coordinator | Source: <source> | Scheduling: critical path first`. Do not expose the coordinator/leaf capacity equation in the chat.

The final chat brief needs no serial baseline. Count the coordinator in the visible peak: `并发：峰值 <leaf peak + 1>（含主任务）｜实际用时：<h时m分s秒>｜子任务累计：<h时m分s秒>｜任务重叠：<h时m分s秒>｜编排空档：<h时m分s秒>`. `任务重叠` is the sum of simultaneous task intervals; `编排空档` is time inside the measured wall-clock boundary when no worker was active. Neither is a controlled speedup claim. Do not display `1 - actual / cumulative` as time saved. Without reliable intervals, show `并发计划：<leaf cap + 1> 个任务（含主任务）｜测量：待记录`.
Keep plans separate from execution statistics. Never treat coarse weights as seconds, infer task start time from ledger append timestamps, or record configured targets as actual model use.
