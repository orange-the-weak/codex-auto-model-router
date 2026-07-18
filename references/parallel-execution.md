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

The parallel object stores `parallelism_source=standard|smart-reduced|user-override`, requested and effective concurrency, observed or default `runtime_max_threads`, deterministic capacity evidence, scheduler, priority order, initial frontier, aggregation order, serialized conflicts, coordinator/worker ownership, timing kind, and `stop-dispatch-drain-running` failure policy. All are hashed with the full DAG and selected routes and echoed in worker envelopes. Legacy `adaptive-extended` plans and plans without the source remain valid.

## Normalization

1. Reject duplicate IDs, forward/unknown dependencies, invalid enums, or more than 16 candidates.
2. Route every candidate independently to GPT-5.6 Sol, Terra, or Luna and effort.
3. Merge at most three short siblings only when route, predecessors, successors, task class, access mode, and conflict keys match and write scopes are disjoint.
4. Require concrete write scopes. Add an earlier-to-later dependency for overlapping write scopes or shared conflict keys.
5. Enforce the existing routed Segment budget: 4 standard, 6 only for a complex/large basis, or user override through the absolute limit of 8.
6. Set automatic requested model concurrency to 4 and never auto-expand it. Compute the maximum dependency-independent model width after merging and conflict serialization. Set `effective=min(4, runtime max_threads, useful independent width)` and use `smart-reduced` whenever the result is below 4.
7. A user `--max-parallelism` override up to 4 may still be reduced by runtime or useful width. A value above 4 is valid only when an observed `runtime_max_threads` and the normalized useful width both meet the request; otherwise reject it. Never use a documented/default capacity to authorize expansion.

Do not split a long task merely to fill slots. Split it only when independently executable boundaries have separate dependencies, acceptance checks, and non-conflicting ownership.

## Dispatch and wait-any

The Coordinator is the sole scheduler. It validates a worker envelope against the immutable plan, completed/running sets, dependencies, free capacity, and attempt ID; atomically claims the Segment; shows the concurrency notice and per-Segment route notice; then launches the exact GPT-5.6 executor preset. Executors require `ROUTE_PROJECT_MODELS_EXECUTOR=1`, `route_id`, and `segment_id`, stay within write ownership, preserve unrelated changes, and never plan, route, advance, or delegate.

When any worker returns, the Coordinator records its bounded result, updates the frontier, confirms the slot is free, and creates only the next highest-priority ready worker. There is no wave barrier and no pre-created executor queue. After all work finishes, it reports results in normalized Segment order, not arrival order.

At the first failed worker, stop dispatching new tasks and drain all already-running workers. Preserve their verified results, mark undispatched work skipped, and aggregate deterministically. Do not retry through another model.

## Ledger evidence

- `parallel_plan` records configured intent: protocol, `parallelism_source`, requested/effective caps, planned worker count, and planned model counts.
- Each verified Segment `execution` may record the real active `concurrency` when task metadata or the user confirms it.
- `parallel_execution` records verified wall clock, cumulative worker duration, peak concurrency, worker count, outcome, and source.

The final chat brief always states concurrency and speedup status. With verified timing, report cumulative worker time divided by wall clock as the effective parallel factor and label the resulting compression as non-A/B. Call a ratio actual speedup only when a comparable serial wall-clock run is independently verified.
Keep plans separate from execution statistics. Never treat coarse weights as seconds, infer worker start time from ledger append timestamps, or record configured targets as actual model use.
