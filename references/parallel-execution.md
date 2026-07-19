# Dependency-parallel execution protocol

`dependency-parallel-v1` adds bounded leaf executors without changing `segmented-v1`.

## Plan fields

Each Segment keeps the existing route, acceptance, validation budget, and deterministic `attempt_id`, plus:

- `depends_on`: zero or more earlier Segment IDs;
- `work_estimate`: `short`, `normal`, or `long` planning weight, never observed timing;
- `access_mode`: `read` or `write`;
- `write_scopes`: concrete repository-relative paths required for writes;
- `conflict_keys`: shared mutable resources such as `git-index`, a lockfile, project file, migration target, deployment target, or shared simulator;
- resulting coarse `critical_path_work`.

The parallel object stores `parallelism_source=standard|smart-reduced|user-override`, requested/effective concurrency, observed total/free slots, coordinator reservation, running workers, scheduler, priority order, aggregation order, conflicts, and `stop-dispatch-drain-running`. These are hashed with the full coordinator plan. Workers receive only their bounded context capsule. Legacy `runtime_max_threads` worker-capacity envelopes remain readable.

## Normalization

1. Reject duplicate IDs, forward/unknown dependencies, invalid enums, or more than 16 candidates.
2. Route every candidate independently to GPT-5.6 Sol, Terra, or Luna and effort.
3. Merge at most three short siblings only when route, predecessors, successors, task class, access mode, and conflict keys match and write scopes are disjoint.
4. Require concrete write scopes. Add an earlier-to-later dependency for overlapping write scopes or shared conflict keys.
5. Enforce the existing routed Segment budget: 4 standard, 6 only for a complex/large basis, or user override through the absolute limit of 8.
6. Set automatic requested concurrency to 4. Compute `available_worker_slots = observed_total_slots - coordinator_slots - running_workers`, then `effective=min(requested, available_worker_slots, useful independent width)`.
7. Without observed capacity, begin with one worker and refill only after a free slot is confirmed. A user value above 4 requires observed free-worker capacity and matching useful width. Never use a documented/default limit to authorize expansion.

Do not split a long task merely to fill slots. Split it only when independently executable boundaries have separate dependencies, acceptance checks, and non-conflicting ownership.

## Dispatch and wait-any

The Coordinator is the sole scheduler. It keeps the full plan/chat, validates the frontier and free capacity, claims the Segment, then launches the exact GPT-5.6 executor preset with a bounded context capsule. Executors stay within ownership and never plan, route, advance, or delegate.

When any worker returns, the Coordinator records its bounded result, updates the frontier, confirms the slot is free, and creates only the next highest-priority ready worker. There is no wave barrier and no pre-created executor queue. After all work finishes, it reports results in normalized Segment order, not arrival order.

At the first failed worker, stop dispatching new tasks and drain all already-running workers. Preserve their verified results, mark undispatched work skipped, and aggregate deterministically. Do not retry through another model.

## Ledger evidence

The default Apply brief is current-run only. Query/history output is explicitly labeled a historical aggregate. Canonical wall clock uses the coordinator's monotonic clock from first dispatch confirmation through last result receipt.

- `parallel_plan` records configured intent: protocol, `parallelism_source`, requested/effective caps, planned worker count, and planned model counts.
- Each verified Segment `execution` may record the real active `concurrency` when task metadata or the user confirms it.
- `parallel_worker_start` and `parallel_worker_finish` record runtime-captured monotonic boundaries for each Segment.
- Schema-v2 `parallel_execution` stores every worker interval and derives wall clock, cumulative duration, peak concurrency, and worker count from them.

Call `router_runtime.py worker-start` immediately after a dispatch is confirmed and `worker-finish` immediately after its result is received. Neither command accepts timing numbers. At the terminal aggregate, `finish` reads those events and writes at most one verified run. Missing, reversed, or incomplete traces stay `pending`; aggregate-only legacy records remain readable but never enter verified metrics.

Use the returned `parallel_execution_brief` verbatim in the Apply response. Do not independently calculate or format the line.

The final chat brief reports concurrency effectiveness without requiring a serial baseline. With verified timing, show `并发：峰值 <n>｜墙钟：<wall>｜累计 worker：<worker>｜有效并发倍率：<factor>x｜并发利用率：<util>%` (`parallel_utilization`). Without reliable timing fields, show `并发：<effective>/<requested>｜测量：待记录`. Never display obsolete compression metrics, and never call factor or utilization speedup.
Keep plans separate from execution statistics. Never treat coarse weights as seconds, infer worker start time from ledger append timestamps, or record configured targets as actual model use.
