# Project Agent Rules

## Model routing

- Use `codex-auto-model-router` automatically for code changes, tests, and reviews. Skip routing for simple questions, copy confirmation, explanations, and read-only lookups.
- Use Router Lite by default. Run `scripts/router_lite.py decide` once, then execute locally when matched or delegate once to the returned explicit executor type. The coordinator keeps its model and never needs Restore.
- Pass a conservative `estimated_seconds` to Router Lite when the work is bounded enough to estimate. Keep tiny mechanical work, deterministic tool-bound chains, and estimated work below the default 90-second delegation break-even local when the current verified GPT-5.6 route is sufficient. A weaker route never wins; explicit user choices always win.
- Never make hashes, runtime state, environment markers, capability probes, or usage ledgers prerequisites for ordinary project work. If routing or executor startup fails, continue locally once unless that could duplicate writes, deployment, uploads, or another dangerous external action.
- Give a delegated agent only the bounded goal, relevant paths and decisions, acceptance criteria, constraints, validation budget, stop condition, and one recovery attempt by default. Treat it as self-contained: do not load global memory, unrelated project history, or extra sources unless explicitly required. Stop as soon as acceptance is proven; do not add redundant validation methods. Do not send a full plan, route hash, cursor, ledger path, or complete conversation.
- Use `scripts/router_lite.py plan` only for two or more independent tasks with non-overlapping write scopes, verified free slots, and predicted net benefit after activation, dispatch, aggregation, and tail imbalance. Use 40 seconds for a fresh first action and 10 seconds for a compatible reused first action. Default to four total tasks including the coordinator and reduce to observed capacity. Never create a waiting agent queue.
- Keep a reuse registry only in coordinator memory for the current user request. Clear it when a new user request starts. A reusable leaf must match repository realpath, model, effort, permissions, and sandbox; be idle with no pending tool call; have a successful accepted result; and own no unresolved write scope or conflict key. Exclude interrupted, failed, external-action, authentication, deployment, and sensitive-data leaves. Allow one follow-up per executor by default.
- Pass only those prequalified leaves to `router_lite.py plan --reuse-candidates-json`. Recheck eligibility immediately before `followup_task`; if it raced busy or stale, spawn fresh or continue locally. Every reused follow-up receives a new self-contained capsule and may not rely on prior conclusions.
- After the compact route/concurrency notice, dispatch the selected route-aware initial batch longest-first without intervening reads, ledger/state work, repeated commentary, or extra planning. Refill a compatible executor immediately when its result releases capacity; otherwise create a fresh executor only when the plan still predicts benefit.
- Mark parallel outputs required or optional before dispatch. Stop optional stragglers after all required acceptance checks pass; never treat a user-required source as optional.
- The coordinator owns dependencies, conflicts, waiting, aggregation, Git operations, shared simulators, deployment targets, and other shared mutable resources. Leaf agents may not delegate.
- Keep visible notices short: `Codex 自动路由｜任务：<name>｜模型：<model>｜推理：<effort>｜<reason>`. For parallel work add `Codex 自动路由｜并发：<total including coordinator> 个任务｜调度：完成即补位`.
- Record actual execution through `router_lite.py record` only after the result is ready. Ledger failure is non-blocking and normally invisible. Never infer actual use or speedup from a recommendation.
- Enter the legacy strict state machine only when the user explicitly requests strict routing, replay protection, strict ledger auditing, or a reproducible routing experiment. Do not silently use `router_runtime.py` for normal work.
- Never auto-select Ultra. Explicit Ultra disables Router-managed parallelism. Stay inside GPT-5.6 while any GPT-5.6 executor is available; disclose GPT-5.5 fallback once only after the complete GPT-5.6 family is proven unavailable.

## Editing and verification

- Preserve unrelated worktree changes. Use `apply_patch` for edits.
- Keep public English and Chinese documentation aligned with the distributed Skill and installed behavior.
- Match validation to risk. Small documentation or policy changes do not require unrelated builds.
- Run unit tests, distribution validation, Skill quick validation, Python compilation, and `git diff --check` before release.
- Run `install.sh` after distributed files change, then verify source/install parity. Restart Codex to refresh the installed Skill and presets.
- Do not commit or push unless the user explicitly requests it.
