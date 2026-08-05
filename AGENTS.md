# Project Agent Rules

## Model routing

- Use `codex-auto-model-router` automatically for code changes, tests, and reviews. Skip routing for simple questions, copy confirmation, explanations, and read-only lookups.
- Use the default fail-open benefit-gated path. Run `scripts/router_lite.py decide` once, then execute locally or with the returned model-specific leaf. The returned `recommended_route` is advice until a `delegate` or `reuse` action is actually dispatched and observed. The coordinator keeps its own model and never needs Restore.
- Automatically create or reuse a child agent when the route-fit, quality, latency, or resource benefit clearly outweighs bounded startup and aggregation overhead. Do not ask for additional permission. Honor an explicit request to avoid child agents with `--no-subagents`; keep `--allow-subagents` only as a compatibility input, not an authorization gate.
- Run independent safe tool or process calls concurrently in the coordinator when they do not depend on one another or share mutable files, Git state, builds, simulators, devices, approval boundaries, or external side effects. Prefer bounded programmatic `Promise.all` orchestration when supported. Tool concurrency uses the same coordinator model and reasoning effort and creates no child-agent UI entries. Keep reasoning-dependent and conflicting steps serial.
- Match every visible routing notice to the language of the user's current request. Use `Codex 自动路由｜任务：<name>｜建议：<model>/<effort>｜执行：<当前主模型|子智能体 model/effort>｜<reason>` for Chinese and `Codex auto route | Task: <name> | Recommendation: <model>/<effort> | Execution: <current coordinator|model/effort leaf agent> | <reason>` for English. Translate labels concisely for other languages. Never report a recommendation as actual model use.
- In automatic benefit-gated subagent mode, use `fork_turns="none"` with explicit agent types, keep capsules bounded and self-contained, never let leaves delegate, and require them to send one final result and end the current turn immediately after acceptance without extra validation, commentary, or parent confirmation. Reuse remains same-request-only with exact identity and safety checks. If startup fails, continue locally within 15 seconds when safe.
- Treat `completed` as terminal and never interrupt it. Refresh live status after wait updates; a child `task_complete` overrides a stale parent `running` label. A timeout alone is not a stall during normal execution.
- Before the parent final response after any subagent use, stop dispatch, disable reuse, clear the current-request reuse registry, refresh the current task tree, interrupt every optional, superseded, or otherwise unneeded child still genuinely `running`, and refresh once more. If a required result remains necessary, wait for it or complete it locally without duplicate writes before interrupting that child. Finalize only after all children owned by this request are terminal. This applies only to the current task tree; no collaboration tool deletes completed child-agent UI history, so never claim that historical cards were cleared.
- Never make hashes, runtime state, environment markers, capability probes, or usage ledgers prerequisites for ordinary work. Record only observed execution metadata; ledger failure is non-blocking and normally invisible.
- Enter the legacy strict state machine only when the user explicitly requests strict routing, replay protection, strict ledger auditing, or a reproducible routing experiment. Do not silently use `router_runtime.py` for normal work.
- Never auto-select Ultra. Explicit Ultra disables Router-managed parallelism. Stay inside GPT-5.6 while any GPT-5.6 executor is available; disclose GPT-5.5 fallback once only after the complete GPT-5.6 family is proven unavailable.

## Editing and verification

- Preserve unrelated worktree changes. Use `apply_patch` for edits.
- Keep public English and Chinese documentation aligned with the distributed Skill and installed behavior.
- Match validation to risk. Small documentation or policy changes do not require unrelated builds.
- Run unit tests, distribution validation, Skill quick validation, Python compilation, and `git diff --check` before release.
- Run `install.sh` after distributed files change, then verify source/install parity. Restart Codex to refresh the installed Skill and presets.
- Do not commit or push unless the user explicitly requests it.
