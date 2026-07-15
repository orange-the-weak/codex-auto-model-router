# Codex Auto Model Router

[![Codex Skill](https://img.shields.io/badge/OpenAI%20Codex-Skill-111827)](https://github.com/openai/skills)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Automatic GPT-5.6 model and reasoning selection for OpenAI Codex.** Split a request into the few useful execution segments, switch Sol, Terra, or Luna at segment boundaries, and use only the reasoning effort each stage needs—without an external API or API key.

[中文说明](README.zh-CN.md)

## Why this tool?

GPT-5.6 gives Codex users Sol, Terra, Luna, and several reasoning levels. Choosing the right combination repeatedly—and deciding when a switch is worth the delay—becomes work of its own. This Skill creates the smallest useful segment plan, selects a route for each stage, switches inside the same Codex task, and restores the original settings at the end.

## Quick start

In Codex, send:

```text
$skill-installer Install the Codex Auto Model Router skill from https://github.com/orange-the-weak/codex-auto-model-router
```

Restart Codex afterward. This installs the core Skill. For all 24 optional custom-agent presets or migration from the old name, use:

```bash
git clone https://github.com/orange-the-weak/codex-auto-model-router.git
cd codex-auto-model-router
./install.sh
```

## Routing at a glance

| Route | Best fit | Default reasoning |
|---|---|---|
| **GPT-5.6 Luna** | Repetitive edits, formatting, file moves, and other deterministic work | `medium`, lowered to `low` when checks are clear |
| **GPT-5.6 Terra** | Features, localized bugs, tests, UI iteration, and bounded refactors | `medium` |
| **GPT-5.6 Sol** | Architecture, security, migrations, concurrency, cross-system diagnosis, and high-risk review | `medium`, raised to `high` or `xhigh` only when justified |

Explicit user choices always win. Every applicable request is evaluated independently: simple work can move from Sol to Terra or Luna, and complex work can move from Luna or Terra to Sol.

## What it does

- Builds the smallest deterministic linear plan; simple requests remain one segment, while genuinely complex or large plans can use more stages.
- Selects a model and reasoning level for each segment, switches through native same-task overrides, and restores the verified original route once at the end.
- Re-evaluates every Segment from its own evidence, then merges adjacent same-route results. The default budget is 4 segments/4 switches, eligible plans can expand to 6/6, and users can set a bounded limit up to 8/8.
- Stops on segment failure instead of cycling through models; falls back to an explicitly selectable custom agent or the current model when native switching is unavailable.
- Shows one clear routing line at each segment boundary, including the automatically selected model, reasoning effort, and reason.
- Tracks verified per-segment model and reasoning usage in a local JSONL ledger.
- Retunes allocations from completion, failure, escalation, rework, and duration evidence.
- Writes a full Markdown routing report while keeping the chat summary short.
- Works entirely inside Codex without an external model gateway or API integration.

Budget behavior is explicit: `4/4` is the normal ceiling; Codex expands to `6/6` only when the normalized plan actually needs it and contains a `complex` or `large` stage. Risk alone does not expand the plan. A user can set one shared limit or separate Segment/switch limits from `1` to `8`; switch counts include the final restore.

## Recent updates

- **Dynamic segmented Apply:** analysis, implementation, verification, and review can use different routes when that improves the task; simple work stays in one segment.
- **Adaptive bounded switching:** most work stays within 4/4, complex or large plans can expand to 6/6, and explicit user limits can reach the hard 8/8 ceiling.
- **Fresh routing per request:** new simple work actively moves down, and new complex work actively moves up; the current route affects dispatch, not model choice.
- **Safer switching:** same-task overrides use verified task metadata and restore the original model and reasoning level once after the chain.
- **Consistent fallback:** selectable custom-agent presets are tried only when their model is explicit; otherwise work continues locally with honest labeling.
- **Clear handoffs:** each segment announces its route once; routine runtime-identity warnings remain hidden on normal completion.
- **Measurable tuning:** actual segment execution, analysis calls, and recommended allocation are recorded separately and can be queried or retuned later.
- **Clean rename migration:** the installer upgrades the former `codex-model-router` name and replaces its legacy presets without touching unrelated Codex files.

## Use

Invoke `$codex-auto-model-router` in Codex:

```text
$codex-auto-model-router Analyze this repository and recommend model routing.
$codex-auto-model-router Apply the saved routing plan and implement this feature.
$codex-auto-model-router Apply this migration with at most 7 segments and 7 switches.
$codex-auto-model-router Use at most 6 segments, but no more than 4 switches.
$codex-auto-model-router Use GPT-5.6 Terra high for this task.
$codex-auto-model-router Query actual model and reasoning usage.
$codex-auto-model-router Record: Terra low completed the UI update in 90 seconds.
$codex-auto-model-router Retune allocation from observed outcomes.
```

At each segment boundary, Codex displays one compact notice:

```text
Codex automatic routing | Segment 1/3: Analyze the change | Model: GPT-5.6 Sol | Reasoning: high | Selected from task ambiguity
```

The next segment can switch to Terra for implementation and Luna for deterministic checks without creating a new top-level Codex task. The chain stops on failure and restores the original route once. If model-aware same-task continuation is unavailable, the Skill uses an explicit custom-agent route when available, then falls back to the current model.

## Reports, history, and privacy

- Full report: `docs/codex-model-routing-report.md`
- Local usage ledger: `.codex/model-routing-history.jsonl`

Actual segment execution, routing analysis, and recommendations remain separate. Recommendations are never counted as observed use. The ledger stores routing metadata and outcomes—not prompts, source code, secrets, or conversation text.

Automatic retuning is deliberately conservative: raise a route after at least five comparable attempts with 40% pressure, and lower it only after at least ten attempts with 90% completion, deterministic verification, and no pressure events.

## A personal note

This is my first open-source project. I built it after spending too much time making the same model-choice decision across different Codex projects. I am still learning how to make the workflow clearer and more reliable, so practical feedback, issue reports, and small improvements are especially welcome.

## Compatibility

This project targets Codex installations that support personal Skills. Native same-task model overrides and named custom agents depend on the capabilities exposed by the current Codex surface. When a requested GPT-5.6 route is unavailable, the workflow continues with an available model and records the fallback instead of claiming a switch that cannot be verified.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 tests/validate_distribution.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) to contribute or report a security issue.

## License

MIT. See [LICENSE](LICENSE).

This independent community project is not affiliated with or endorsed by OpenAI.
