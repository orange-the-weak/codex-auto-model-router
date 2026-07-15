# Routing criteria

Use this reference to choose the lowest sufficient Codex model and reasoning effort. These are operational heuristics, not permanent capability guarantees.

These criteria primarily route follow-on execution tasks. For the assessment itself, default to `GPT-5.6 Sol` / `medium`, honor the user's model or effort override, and otherwise select `low`, `medium`, `high`, or `xhigh` using the task-difficulty rules and exact presets in `SKILL.md`.

## Model tiers

| Tier | Best fit | Common examples | Avoid when |
|---|---|---|---|
| Luna | Mechanical, repetitive, narrow, high-volume, easy to verify | formatting, copy edits, renames with clear scope, fixture generation, file inventory, simple test updates, applying an established pattern | requirements are ambiguous, behavior spans modules, or failure is costly |
| Terra | Normal engineering default balancing capability and speed | bounded features, localized bug fixes, ordinary refactors, UI iteration, test authoring, log analysis, dependency updates with clear migration notes | architecture is unsettled, root cause is unclear across systems, or risk is high |
| Sol | Complex professional work with ambiguity, coupling, novelty, or high consequence | architecture, cross-layer migrations, concurrency and state bugs, security/privacy review, data-loss risks, unfamiliar large-codebase synthesis, hard root-cause analysis | the task can first be reduced to bounded and independently verifiable units |

Official model guidance describes Sol as the frontier tier for complex professional work, Terra as the balance tier, and Luna as the cost-sensitive high-volume tier. In Codex usage, translate “cost-sensitive” into minimizing unnecessary model capacity and latency; do not produce API pricing or integration advice.

## Reasoning effort

| Effort | Use when | Typical pairing |
|---|---|---|
| low | Task is bounded, familiar, and locally verifiable | Luna or Terra; default for routine work |
| medium | Several constraints interact or a multi-file plan must remain coherent | Terra or Sol; default for genuine analysis |
| high | Ambiguity, deep coupling, or high consequence requires careful alternatives and validation | Sol |
| xhigh | A demonstrably difficult problem resisted a well-scoped attempt or needs exhaustive analysis | Sol, exceptional |

Never choose an effort merely because the model supports it. Prefer `low` over `medium`, and `medium` over `high`, unless a named risk or dependency requires more.

## Five routing signals

Score each task qualitatively; do not invent false numeric precision.

1. **Ambiguity:** Are desired behavior and acceptance criteria explicit?
2. **Scope:** Is the change mechanical, localized, multi-file, cross-module, or architectural?
3. **Coupling:** How many state, data, service, platform, or lifecycle boundaries interact?
4. **Verification:** Is there a fast deterministic check, or does correctness require broad integration and judgment?
5. **Consequence:** Would failure be cosmetic, reversible, user-visible, production-impacting, or security/data-loss sensitive?

Route to Luna when all five signals are low. Route to Terra when most are low or moderate and verification is clear. Route to Sol when any consequence is high or several other signals are high.

## Escalation ladder

Escalate one dimension at a time:

1. Clarify acceptance criteria and shrink scope.
2. Increase reasoning effort within the same model.
3. Move Luna to Terra or Terra to Sol.
4. Use `xhigh` only after recording why the prior scoped attempt was insufficient.

Do not escalate because a command failed for an environmental reason such as missing dependencies, permissions, simulator state, network access, or credentials. Fix or report the environment first.

## Common project patterns

| Work pattern | Starting recommendation |
|---|---|
| Documentation, localization, metadata, deterministic config edits | Luna low |
| Repeated changes following an accepted example | Luna low |
| Small UI behavior or styling change with a clear preview path | Terra low |
| Bounded feature inside one subsystem | Terra low |
| Multi-file refactor with stable tests and unchanged architecture | Terra medium |
| Unclear bug spanning async state, persistence, networking, or lifecycle | Sol medium/high |
| Schema, authentication, authorization, privacy, payments, destructive data migration | Sol high |
| Architecture selection or broad legacy migration | Sol high; decompose follow-on execution to Terra/Luna |
| Independent review of a high-risk change | Sol medium/high |

## Speed safeguards

- Inspect representative files before reading whole trees.
- Avoid generated folders and dependencies.
- Reuse repository instructions and existing verification commands.
- Do not run builds or test suites during routing unless the user asks for empirical benchmarking.
- Use one segment by default; add a boundary only when a dependent stage needs a materially different route or verification contract.
- Re-evaluate each applicable Apply request independently. Treat model-switch latency as small relative to route fit; move both downward from an unnecessarily strong route and upward from an insufficient route.
- Batch adjacent tasks assigned to the same model and effort. Use the 4/4 standard budget, expand to 6/6 only for a normalized plan with a concrete complex or large basis, and require a user override for anything above that up to the 8/8 hard limit.

## Efficiency estimate

Estimate improvement against this default baseline: **all follow-on AI work uses GPT-5.6 Sol with medium reasoning and no task-specific routing**. Measure expected end-to-end AI work turnaround or productive throughput, not application runtime and not API cost.

Prefer measured repository-specific timing or evaluation evidence when it exists. Otherwise produce a clearly labeled heuristic range:

1. Estimate the share of likely recurring work in three groups whose percentages total 100%:
   - **Fast lane:** Luna or Terra at low, with deterministic or quick local verification.
   - **Optimized normal lane:** Terra medium or Sol low, where bounded scope reduces unnecessary reasoning.
   - **Escalation lane:** Sol high/xhigh, where extra analysis may be slower but prevents costly rework.
2. Apply conservative improvement bands relative to the baseline:
   - Fast lane: 25–50% faster or more productive.
   - Optimized normal lane: 10–25%.
   - Escalation lane: -10–0% direct speed improvement.
3. Weight the lower and upper bounds by the task mix. Clamp the overall range to 0–60% and round each bound to the nearest 5 percentage points.
4. Subtract observed model-switch and Restore/Return time. Treat it as a normal bounded overhead rather than a reason to inherit the previous route; if it is not measured, state that the estimate excludes unknown routing overhead and do not claim a measured gain.
5. Explain the task-mix assumptions and identify the two or three changes contributing most to the result.

Exclude unavoidable external waiting such as dependency downloads, network services, simulator or device delays, approval waits, and full builds unless the repository contains measured evidence showing that the proposed workflow changes them. Do not present generic model-tier marketing claims as benchmarks. If evidence is too weak to estimate the task mix, report `预计增效：暂无法可靠估算` and state what evidence is missing instead of inventing a percentage.
