# Codex Auto Model Router — Dynamic Per-Segment Routing

[![Codex Skill](https://img.shields.io/badge/OpenAI%20Codex-Skill-111827)](https://github.com/openai/skills)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Automatic, dynamic per-segment model, reasoning, and concurrency routing for GPT-5.6 in OpenAI Codex.** Evidence-calibrated routing sends each bounded task to Sol, Terra, or Luna at the lowest sufficient effort—with no external API or API key.

[中文说明](README.zh-CN.md)

## Why this tool?

GPT-5.6 adds three model tiers and several reasoning levels to Codex. This Skill automatically re-evaluates each useful Segment, dynamically switches only when the work benefits, and restores a verified original GPT-5.6 route when finished.

## Quick start

Send this in Codex:

```text
$skill-installer Install Codex Auto Model Router from https://github.com/orange-the-weak/codex-auto-model-router
```

Restart Codex afterward. To install all 24 optional custom-agent presets or migrate from the old name:

```bash
git clone https://github.com/orange-the-weak/codex-auto-model-router.git
cd codex-auto-model-router
./install.sh
```

## Evidence-backed routing

The current policy is calibrated from OpenAI coding results, the independent Artificial Analysis Coding Agent Index, and the DeepSWE, Terminal-Bench, and SWE-Bench Pro methodologies. API per-effort measurements inform only relative capability, latency, and output growth; they are not treated as Codex wall time or subscription cost.

| Route | Default use |
|---|---|
| **Luna low** | Clear mechanical edits and deterministic checks |
| **Luna medium** | Large repetitive batches |
| **Terra low** | Bounded ordinary work with deterministic verification |
| **Terra medium** | Ordinary work with interacting files or constraints |
| **Sol medium** | Bounded complex work |
| **Sol high** | High ambiguity, coupling, judgment, or consequence |
| **Sol xhigh** | A failed complex attempt, or explicit user choice |

Task evidence and user overrides always win. The benchmark snapshot is versioned, offline, and valid for 90 days; missing, invalid, or stale evidence falls back to deterministic rules without blocking work. See the [full evidence report](references/benchmark-evidence.md) and [machine-readable snapshot](references/benchmark-evidence.json).

For an illustrative mixed workload, the current policy estimates **15–30% faster AI-work turnaround** than using Sol/medium everywhere. This is a conservative hypothesis—not a universal Codex benchmark—and should be refined from local usage history.

## How it works

- Re-evaluates every applicable request instead of inheriting the previous route.
- Uses a one-Segment fast path: a locally matched route skips the full DAG, cursor, replay claim, and Restore chain. Multi-Segment state gates are combined into one `begin` and one `finish` call.
- Splits analysis, implementation, verification, or review only when different routes materially help.
- Caps automatic concurrency at 4, then reduces it to useful independent width and observed free workers. Total agent slots reserve the coordinator and subtract running workers.
- Without observed capacity, dispatches one worker and refills only after another slot is confirmed. Requests above 4 require proven free capacity; no pre-created queue.
- Uses critical-path-priority wait-any scheduling to reduce tail latency. Compatible short siblings may merge; long tasks split only at real independent boundaries.
- Keeps the full conversation in the coordinator; workers receive only a bounded context capsule with necessary decisions, scope, acceptance, and immutable IDs.
- Requires disjoint write scopes and serializes Git index, lockfiles, project files, migrations, deploy targets, shared simulators, and other mutable resources through conflict keys.
- Uses a standard 4-segment/4-switch budget, adaptive 6/6 for genuinely complex or large plans, and an explicit hard limit of 8/8. Restore counts as a switch.
- Keeps fallback inside GPT-5.6: Sol tries Terra then Luna; Terra tries Sol then Luna; Luna tries Terra then Sol. GPT-5.5 is allowed only when the complete 5.6 family is unavailable.
- Announces the selected model and reasoning once per segment, stops on failure, and restores a verified original GPT-5.6 route once.
- Records only verified execution in a local JSONL ledger; recommendations never count as observed use.
- Separates configured parallel plans from verified model × concurrency, wall-clock, cumulative worker time, and peak-concurrency statistics.
- Tracks verified routing, queue, startup, switch/Restore, useful-execution, round-trip, and state-gate overhead without guessing missing data.
- Ends each task brief with effective parallel factor and utilization. These use observed worker and wall time, so no serial baseline is required; actual speedup remains optional controlled A/B evidence.

## Use

```text
$codex-auto-model-router Analyze this repository and recommend routes.
$codex-auto-model-router Implement this feature with dynamic segment routing.
$codex-auto-model-router Use GPT-5.6 Terra high for this task.
$codex-auto-model-router Query usage ratios and retune from observed outcomes.
```

Example notice:

```text
Codex automatic routing | Segment 1/3: Analyze the change | Model: GPT-5.6 Sol | Reasoning: high | High ambiguity
Codex automatic routing | Parallel plan: 3 tasks | Concurrency: 3/4 | Free workers: 3 | Source: smart-reduced | Critical-path priority
Concurrency: peak 3 | Wall: 120s | Worker total: 288s | Effective parallel factor: 2.4x | Utilization: 80%
```

Reports are written to `docs/codex-model-routing-report.md`; verified usage is stored in `.codex/model-routing-history.jsonl`. The ledger contains routing metadata and outcomes, not prompts, source code, secrets, or conversation text.

## A personal note

This is my first open-source project. I built it after spending too much time making the same model-choice decision across Codex projects. Practical feedback, issue reports, and small improvements are very welcome.

## Compatibility and development

This project requires Codex with personal Skill support. Same-task overrides and custom agents depend on the active surface. While any GPT-5.6 route is selectable, the Skill neither falls back nor restores to GPT-5.5 or an ambiguous `available-default`. If a task starts on 5.5 and successfully enters 5.6, it stays on the verified 5.6 route. A 5.5 fallback is recorded and shown only when Sol, Terra, and Luna are all unavailable.

```bash
python3 -m unittest discover -s tests -v
python3 tests/validate_distribution.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [LICENSE](LICENSE). This independent community project is not affiliated with or endorsed by OpenAI.
