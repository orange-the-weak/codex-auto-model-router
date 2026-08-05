# Codex Auto Model Router

[![Validate](https://github.com/orange-the-weak/codex-auto-model-router/actions/workflows/validate.yml/badge.svg)](https://github.com/orange-the-weak/codex-auto-model-router/actions/workflows/validate.yml)

**A lightweight GPT-5.6 model and reasoning router for OpenAI Codex.** It recommends Sol, Terra, or Luna and low through max reasoning, prefers low-overhead direct tool concurrency, and automatically uses a model-specific leaf when the route benefit is clearly larger than its overhead.

[简体中文](README.zh-CN.md) · [Routing feedback](https://github.com/orange-the-weak/codex-auto-model-router/issues/new?template=routing-feedback.yml) · [Bug report](https://github.com/orange-the-weak/codex-auto-model-router/issues/new?template=bug-report.yml)

GPT-5.6 gives Codex many useful model and reasoning combinations. Choosing one for every task quickly became its own chore. I built this Skill to make that choice automatic—and then learned that a router which blocks the real work is worse than no router at all.

Version 2 therefore uses a fail-open, benefit-gated default: choose quickly, keep bookkeeping out of the critical path, and create a bounded subagent automatically when model-switch benefit outweighs startup and aggregation cost. This is my first open-source project; practical feedback is genuinely welcome.

**Automatic model routing**

```text
Request
└─ Re-evaluate the task itself
   ├─ Mechanical, ordinary, scan, or deterministic deep work → Luna
   ├─ Explicit latency priority → Terra
   └─ Complex, coupled, ambiguous, or consequential → Sol
      ↓
   Recommendation matches or switching does not pay → run locally
   Recommendation differs and route benefit clears overhead → use that model's leaf agent
```

**Low-overhead concurrency**

```text
Task
├─ Independent, safe tool/process calls → run concurrently in the coordinator
├─ Reasoning-dependent or conflicting work → run serially
└─ Independent reasoning with clear net route benefit → automatic agent mode
```

## Quick start

Ask Codex:

> Install the `codex-auto-model-router` Skill from `https://github.com/orange-the-weak/codex-auto-model-router`.

Or install manually:

```bash
git clone https://github.com/orange-the-weak/codex-auto-model-router.git
cd codex-auto-model-router
./install.sh
```

Restart Codex after installation.

## How it works

Every applicable request follows one of three paths:

| Path | Behavior |
|---|---|
| Local | Recommend a route, then complete the work in the current coordinator. |
| Tool concurrency | Run independent safe tool or process calls together without creating child agents. |
| Benefit-gated subagents | Automatically delegate, reuse, or use multi-model reasoning when route benefit clearly exceeds bounded overhead. |

There is no model Restore, plan hash, cursor, environment guard, or blocking ledger on the default path. Routing or executor startup failure does not block ordinary work. The legacy strict state machine remains available only when the user explicitly requests strict auditing or replay protection.

Visible routing notices follow the language of the current request. English prompts receive English labels, Chinese prompts receive Chinese labels, and model, effort, and reason values remain unchanged.

The recommendation does not switch the current task's model. A routed leaf is a separate task running the recommended model, not a change to the already-running coordinator. Direct tool concurrency shares the coordinator's model and reasoning effort; it creates no child-agent cards or independent reasoning streams.

Safe direct concurrency includes independent file reads, searches, metadata queries, and tests that do not share build state. Reasoning-dependent calls, overlapping writes, Git mutation, deployment, approvals, and shared simulator, device, or build resources remain serial.

Subagent mode is automatic when route-fit, quality, latency, or resource benefit clearly exceeds bounded startup and aggregation overhead; no additional user permission prompt is required. Users can explicitly disable it with `--no-subagents`. Delegated agents keep bounded lifecycle safeguards: `completed` is terminal, child `task_complete` overrides stale parent `running`, a timeout alone is not a stall, and reuse never crosses user requests.

Before the coordinator's final response, any subagent run stops new dispatch, disables reuse, clears the current-request reuse registry, refreshes the current task tree, interrupts every optional or otherwise unneeded child still genuinely `running`, and refreshes once more. The coordinator finalizes only after every child owned by that request is terminal. This can end current-task children, but Codex exposes no collaboration operation for deleting completed child-agent UI history; historical cards may remain visible and are never reported as cleared.

The CLI enables benefit-gated subagents by default. `--no-subagents` is the explicit opt-out. The legacy `--allow-subagents` flag remains accepted for wrapper compatibility but is not permission and is no longer required. Executor presets are selected automatically only after the benefit gate clears; they are never prewarmed or queued speculatively.

## What changed in v0.2

- The default path automatically uses a model-specific leaf when switching benefit clearly exceeds bounded overhead.
- Independent safe tools and processes may run concurrently without extra model contexts or child-agent UI entries.
- `--no-subagents` explicitly disables delegate, reuse, and agent-parallel plans; no permission prompt is otherwise required.
- Recommendations are clearly separated from the current task's observed model.
- Ultra remains opt-in, and fallback stays inside GPT-5.6 while any Sol, Terra, or Luna route is available.

## Model gradient

| Work | Default route |
|---|---|
| Deterministic mechanical work | Luna / medium |
| Ordinary bounded work | Luna / high |
| Large bounded scans or reviews | Luna / xhigh |
| Large deterministic deep work | Luna / max |
| Explicit latency priority | Terra / high |
| Bounded complex work | Sol / medium |
| High ambiguity, coupling, or consequence | Sol / high |
| Failed complex reasoning or verification | Sol / xhigh |

Ultra is never automatic. Explicit Ultra uses its native orchestration and disables Router-managed parallelism. GPT-5.5 is used only after the complete GPT-5.6 family is proven unavailable.

## Evidence and history

Routing is calibrated with offline public coding-agent evidence from OpenAI, Artificial Analysis, CursorBench, ChatBench, DeepSWE, SWE-Bench Pro, and Terminal-Bench. Task evidence and user overrides remain primary. API effort data is only a relative prior, not measured Codex subscription cost or wall-clock time.

See [benchmark evidence](references/benchmark-evidence.md) and the [machine-readable snapshot](references/benchmark-evidence.json). The snapshot is optional at runtime; missing, invalid, or stale evidence falls back to deterministic rules without blocking work.

Only observed execution is recorded; a recommendation is never written as actual model use. Benefit-gated subagent mode returns a machine-readable spawn contract: an explicit executor type must use `fork_turns="none"`, and a contract mismatch falls back locally without retry. History never becomes a prerequisite for the project result.

## Development

```bash
python3 -m unittest discover -s tests
python3 tests/validate_distribution.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for privacy-safe feedback and development guidance.
