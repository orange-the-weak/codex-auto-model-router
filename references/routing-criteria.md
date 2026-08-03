# Routing criteria

Use this reference to choose the lowest sufficient Codex model and reasoning effort. Task evidence comes first; the versioned offline prior in [benchmark-evidence.md](benchmark-evidence.md) breaks ties and calibrates effort. It expires after 90 days and never creates a runtime network dependency.

These criteria primarily route follow-on execution tasks. Assess and Retune default to `GPT-5.6 Sol` / `high` for stable policy analysis; an explicit user model or effort override still wins.

## Model tiers

| Tier | Best fit | Common examples | Avoid when |
|---|---|---|---|
| Luna | Cheap mechanical work plus bounded reasoning with deterministic verification | literal edits, established patterns, coherent low-consequence refactors, test-backed multi-file implementation | requirements are ambiguous, coupling is high, verification is judgment-based, or failure is costly |
| Terra | Low-latency ordinary engineering when fast return is explicitly valuable | localized bug fixes, UI iteration, interactive diagnosis, log analysis | latency is not important, architecture is unsettled, root cause is unclear across systems, or risk is high |
| Sol | Complex professional work with ambiguity, coupling, novelty, or high consequence | architecture, cross-layer migrations, concurrency and state bugs, security/privacy review, data-loss risks, unfamiliar large-codebase synthesis, hard root-cause analysis | the task can first be reduced to bounded and independently verifiable units |

OpenAI's coding-agent results and the independent Coding Agent Index support Sol as the strongest tier. Current Codex token credits make Luna 25× cheaper than Sol per input, cached-input, and output token. CursorBench 3.2 shows Luna/high as the useful middle step and places Luna/max near Sol/medium and Sol/high on ambiguous multi-file tasks, but max uses far more tokens and steps. ChatBench category scores are weighted proxies derived from Artificial Analysis API metrics rather than an independent Agent harness; use them only for relative speed and cost context. API and benchmark costs are never substituted for the user's actual Codex plan cost.

## Reasoning effort

| Effort | Use when | Typical pairing |
|---|---|---|
| low | Explicit user override or compatibility testing; never an automatic lane | Any supported model by explicit request |
| medium | Mechanical execution or bounded complex work | Luna for mechanical work; Sol for bounded complex work |
| high | Ordinary bounded reasoning, explicit latency priority, or difficult consequential work | Luna by default, Terra for latency, Sol for difficulty or consequence |
| xhigh | A large bounded evidence scan/review needs more coverage without max's startup cost, or a difficult complex problem has comparable reasoning-failure evidence | Luna for bounded scans; Sol for failed complex reasoning |
| max | Demanding bounded work benefits from more exploration and verification, and extra latency/tokens are acceptable | Luna for low-consequence deterministic deep work; other models by explicit override |

Never choose an effort merely because the model supports it. Luna/max is justified by boundedness, deterministic verification, and low consequence—not by Luna's low token rate alone. Ultra is disabled by default and never appears in automatic lanes. If the user explicitly enables native Ultra, use one bounded Sol or Terra task and disable Router-managed parallelism; Luna/ultra is unsupported.

## Six routing signals

Score each task qualitatively; do not invent false numeric precision.

1. **Ambiguity:** Are desired behavior and acceptance criteria explicit?
2. **Scope:** Is the change mechanical, localized, multi-file, cross-module, or architectural?
3. **Coupling:** How many state, data, service, platform, or lifecycle boundaries interact?
4. **Verification:** Is there a fast deterministic check, or does correctness require broad integration and judgment?
5. **Consequence:** Would failure be cosmetic, reversible, user-visible, production-impacting, or security/data-loss sensitive?
6. **Latency priority:** Does the user explicitly need a fast return, or can deeper reasoning trade latency for fewer revisions?

Automatic routing uses exactly eight lanes. Use Luna/medium as the floor for mechanical work and Luna/high for ordinary bounded work, including normal-size read-only evidence scans. Use Luna/xhigh for a large bounded scan/review when coverage matters but max's much larger startup and token expansion do not. Raise to Luna/max only for genuinely large deterministic deep work with low consequence and acceptable latency. Use Terra/high only when `latency_priority=high` and the task does not cross a Sol boundary. Route bounded complex work to Sol/medium. `verification=judgment` alone is not a Sol/high trigger; high ambiguity, coupling, or consequence is. Use Sol/xhigh only after a classified reasoning/verification failure on comparable complex work or by explicit user request. Infrastructure and unclassified failures do not escalate.

## Escalation ladder

Escalate one dimension at a time:

1. Clarify acceptance criteria and shrink scope.
2. Increase reasoning effort within the same model.
3. Move Luna to Terra/high only for explicit latency priority; move either family to Sol when task evidence crosses a complexity or consequence boundary.
4. Use Sol/xhigh only after recording why the prior scoped attempt was insufficient. Use max only for its bounded-deep lane or explicit override.

Do not escalate because a command failed for an environmental reason such as missing dependencies, permissions, simulator state, network access, or credentials. Fix or report the environment first.

Capability fallback preserves lane intent, not the effort label: Luna/high or Luna/xhigh first falls to Terra/high, Luna/max to Sol/medium, Terra/high to Luna/high, Sol/medium to Terra/xhigh, and Sol/high/xhigh to Terra/max. Use the second canonical substitute only if the first is unavailable. Mark fallback policy version and whether quality degraded; never use GPT-5.5 while any GPT-5.6 family route remains available.

## Common project patterns

| Work pattern | Starting recommendation |
|---|---|
| One literal replacement, tiny metadata edit, or formatting-only change | Luna medium |
| Documentation, localization, config edits, or repeated changes following an accepted example | Luna medium |
| Clear bounded implementation/refactor with low consequence and deterministic tests | Luna high |
| Large bounded source scan or review with low coupling | Luna xhigh |
| Large or genuinely deep deterministic implementation where latency is acceptable | Luna max |
| UI iteration or interactive diagnosis where fast return is explicit | Terra high |
| Bounded feature inside one subsystem with deterministic checks | Luna high |
| Multi-file refactor with stable tests and unchanged architecture | Luna high or Luna max by depth |
| Bounded cross-file diagnosis with stable verification | Sol medium |
| Unclear bug spanning async state, persistence, networking, or lifecycle | Sol high |
| Schema, authentication, authorization, privacy, payments, destructive data migration | Sol high |
| Architecture selection or broad legacy migration | Sol high; decompose follow-on execution to Terra/Luna |
| Independent review of a high-risk change | Sol medium/high |

## Speed safeguards

- Inspect representative files before reading whole trees.
- Avoid generated folders and dependencies.
- Reuse repository instructions and existing verification commands.
- Do not run builds or test suites during routing unless the user asks for empirical benchmarking.
- Never fetch external benchmark data during Apply. Record the active snapshot ID in new plans; stale, invalid, or missing evidence uses the deterministic fallback.
- Use one segment by default; add a boundary only when a dependent stage needs a materially different route or verification contract.
- Re-evaluate each applicable Apply request independently. Treat model-switch latency as small relative to route fit; move both downward from an unnecessarily strong route and upward from an insufficient route.
- Preserve adjacent task boundaries even when routes match. Merge only an explicit semantic `merge_group` with identical route source and task evidence. Use the 4/4 standard budget, expand to 6/6 only for a concrete complex or large basis, and require a user override above that up to 8/8.
- Parallelize only useful independent work. Automatically use at most 4 leaf executors and reduce from observed `agents.max_threads` plus dependency-independent width. Permit a user request above 4 only when both runtime capacity and useful ready work are confirmed; never pre-create a waiting executor queue. Prefer read-heavy parallelism; require disjoint write scopes and serialize shared mutation through conflict keys.
- Balance tail latency with coarse short/normal/long estimates and critical-path-priority wait-any scheduling. Merge only compatible short siblings; split a long Segment only across genuine independent ownership and verification boundaries.

## Efficiency estimate

Estimate improvement against this default baseline: **all follow-on AI work uses GPT-5.6 Sol with medium reasoning and no task-specific routing**. Measure expected end-to-end AI work turnaround or productive throughput, not application runtime and not API cost.

When verified token telemetry is compared, preserve input-cache categories: cached input is a context-reuse/repetition indicator with lower cost, not a standalone reason to suppress concurrency. Focus optimization decisions on uncached input, output, and reasoning tokens; do not use total tokens alone, and never map API prices to Codex subscription cost.

Prefer measured repository-specific timing or evaluation evidence when it exists. Otherwise produce a clearly labeled heuristic range:

1. Estimate the share of likely recurring work in four groups whose percentages total 100%:
   - **Fast lane:** Luna medium for mechanical work, or Terra high for explicit latency priority.
   - **Bounded reasoning lane:** Luna high; Luna max only when unusual depth may reduce rework and is not assumed faster.
   - **Optimized normal lane:** Sol medium where bounded scope avoids unnecessary escalation.
   - **Escalation lane:** Sol high/xhigh, where extra analysis may be slower but prevents costly rework.
2. Apply conservative improvement bands relative to the baseline:
   - Fast lane: 25–50% faster or more productive.
   - Bounded reasoning lane: -10–10% direct speed; count rework reduction only when measured.
   - Optimized normal lane: 10–25%.
   - Escalation lane: -10–0% direct speed improvement.
3. Weight the lower and upper bounds by the task mix. Clamp the overall range to 0–60% and round each bound to the nearest 5 percentage points.
4. Subtract observed Lite classification, leaf-agent startup, and aggregation time. The coordinator does not switch or Restore. If overhead is not measured, state that the estimate excludes it and do not claim a measured gain.
5. Explain the task-mix assumptions and identify the two or three changes contributing most to the result.

Exclude unavoidable external waiting such as dependency downloads, network services, simulator or device delays, approval waits, and full builds unless the repository contains measured evidence showing that the proposed workflow changes them. Do not present generic model-tier marketing claims as benchmarks. If evidence is too weak to estimate the task mix, report `预计增效：暂无法可靠估算` and state what evidence is missing instead of inventing a percentage.
