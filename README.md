# Codex Auto Model Router

[![Validate](https://github.com/orange-the-weak/codex-auto-model-router/actions/workflows/validate.yml/badge.svg)](https://github.com/orange-the-weak/codex-auto-model-router/actions/workflows/validate.yml)

**A lightweight GPT-5.6 model and reasoning router for OpenAI Codex.** It selects Sol, Terra, or Luna, chooses low through max reasoning, and uses bounded parallel agents only when they should actually help.

[简体中文](README.zh-CN.md) · [Routing feedback](https://github.com/orange-the-weak/codex-auto-model-router/issues/new?template=routing-feedback.yml) · [Bug report](https://github.com/orange-the-weak/codex-auto-model-router/issues/new?template=bug-report.yml)

GPT-5.6 gives Codex many useful model and reasoning combinations. Choosing one for every task quickly became its own chore. I built this Skill to make that choice automatic—and then learned that a router which blocks the real work is worse than no router at all.

Version 2 therefore defaults to a fail-open Lite architecture: choose quickly, delegate once when useful, and keep bookkeeping out of the critical path. This is my first open-source project; practical feedback is genuinely welcome.

**Automatic model routing**

```text
Request
└─ Re-evaluate the task itself
   ├─ Mechanical, ordinary, or bounded scan → Luna
   ├─ Explicit latency priority → Terra
   └─ Complex, ambiguous, or consequential → Sol
      ↓
   Current route is sufficient or work is short → run locally
   Otherwise → start or safely reuse a matching executor
```

**Adaptive parallelism**

```text
Task
├─ Independent, substantial, non-conflicting subtasks?
│  ├─ No → run serially
│  └─ Yes → check free capacity and startup/aggregation cost
│     ├─ No net benefit → run serially
│     └─ Net benefit → run in parallel and refill on completion
└─ Shared files, build resources, or external actions → run serially
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

## Router Lite

Every applicable request follows one of three paths:

| Path | Behavior |
|---|---|
| Fast | The current route already matches, or the work is cheaper than agent startup; execute locally. |
| Delegate | Start or safely reuse one explicitly selected internal agent; the coordinator keeps its model. |
| Parallel | Run only worthwhile independent tasks that fit verified free capacity. |

There is no model Restore, plan hash, cursor, environment guard, or blocking ledger on the default path. If routing or agent startup fails, ordinary work continues locally once. The legacy strict state machine remains available only when the user explicitly requests strict auditing or replay protection.

Tiny mechanical edits, deterministic tool-bound chains, and bounded work estimated below 90 seconds stay local when the current verified GPT-5.6 route is already sufficient. A weaker current route never replaces the recommendation, and an explicit user choice always wins.

Delegated agents receive a self-contained task capsule and stop as soon as acceptance is proven. Within the same request, an idle agent may be reused once only when repository, route, permissions, and ownership still match. Reuse never crosses user requests.

Automatic parallelism requires independent work, non-overlapping writes, verified capacity, and positive net benefit after activation and aggregation. Local probes separated the old 40-second estimate into 35.5–39.6 seconds to a fresh first tool versus 2.7–9.4 seconds when reusing the same agent. Planning therefore uses conservative 40-second fresh and 10-second reused priors, requires at least 30 seconds and 15% benefit, and refills compatible agents immediately. These are local planning estimates, not a platform SLA or speedup claim.

## What changed in v0.2

- Router Lite removes Restore, hashes, state gates, and blocking ledgers from normal work.
- Short or deterministic work stays local when the current GPT-5.6 route is sufficient.
- Parallel planning now distinguishes fresh and reused executors, schedules route-aware lanes, and refills completed compatible agents without a new task cold start.
- Reuse is limited to one safe follow-up in the same request; route changes, stale ownership, failures, and sensitive external actions stay fresh or local.
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

Usage history is written after execution on a best-effort basis. It records observed model mix and concurrency without making analytics a prerequisite for the project result.

## Development

```bash
python3 -m unittest discover -s tests
python3 tests/validate_distribution.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for privacy-safe feedback and development guidance.
