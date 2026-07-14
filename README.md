# Codex Model Router

[![Codex Skill](https://img.shields.io/badge/OpenAI%20Codex-Skill-111827)](https://github.com/openai/skills)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Task-aware model routing and execution for OpenAI Codex.** Analyze a repository, execute bounded task segments across GPT-5.6 Sol, Terra, and Luna, tune reasoning effort from `low` to `xhigh`, track actual usage, and continuously improve the allocation from observed outcomes.

[中文说明](README.zh-CN.md)

Codex Model Router is a reusable Codex skill for developers who want faster AI-assisted engineering without sending requests through an external API. It combines repository analysis, LLM model routing, adaptive reasoning effort, multi-agent orchestration, usage analytics, safe fallback behavior, and Markdown efficiency reports inside Codex.

## Why use it?

Using the strongest model at high reasoning for every task is usually unnecessary. This skill routes work by ambiguity, scope, coupling, verification difficulty, and consequence of error:

- **Luna** for mechanical, repetitive, high-volume work with deterministic checks.
- **Terra** for ordinary features, localized bugs, UI iteration, tests, and bounded refactors.
- **Sol** for architecture, security, migrations, concurrency, cross-system diagnosis, and high-risk review.
- **Adaptive reasoning** uses `medium` as the normal default, then moves to `low`, `high`, or `xhigh` only when task scope, risk, and verification difficulty justify it.

The generated report estimates productivity improvement against an all-Sol/medium baseline. Repository-specific measurements replace the heuristic after enough comparable history exists.

## Features

- Repository-aware model and reasoning-effort recommendations.
- Apply mode executes work requested in the same invocation through Codex's native same-task `model` × `thinking` override instead of leaving the routing plan as documentation only.
- Visible per-segment route notices in the Codex conversation, including model, reasoning effort, purpose, and fallback status.
- Same-task routed continuations; no new top-level Codex task.
- Fast local Query and Record modes that do not start an analysis agent.
- Persistent model × effort usage ratios in `.codex/model-routing-history.jsonl`.
- Evidence-based Retune mode using success, failure, escalation, rework, median duration, and P75 duration.
- Deterministic report updates that preserve unrelated Markdown content.
- GPT-5.6 availability fallback with honest model labeling.
- Optional custom-agent presets for Codex surfaces that explicitly support selecting named agents; generic subagent names are never treated as proof of a model switch.
- No API key, external model gateway, or API integration required.

## Install

Clone the repository and run the installer:

```bash
git clone https://github.com/<your-github-username>/codex-model-router.git
cd codex-model-router
./install.sh
```

The installer copies:

- this skill to `${CODEX_HOME:-~/.codex}/skills/codex-model-router`
- the twelve router and twelve executor agents to `${CODEX_HOME:-~/.codex}/agents`

Restart Codex after installation so it refreshes skills and custom agents.

The installer only copies files into `CODEX_HOME`; it does not modify project code, call an API, or remove existing files.

## Usage

Invoke the skill in Codex with `$codex-model-router`.

```text
$codex-model-router Analyze this repository and optimize model routing.

$codex-model-router Query the actual model usage ratio.

$codex-model-router Record: Terra low completed a UI task in 90 seconds.

$codex-model-router Retune task allocation from the observed history.

$codex-model-router Use GPT-5.6 Terra high for this assessment.

$codex-model-router Apply the saved routing plan and implement the requested feature.
```

Before each distinct routed segment, the skill shows a compact notice such as:

```text
Codex 自动路由｜任务段：Repository assessment｜模型：GPT-5.6 Sol｜推理：medium｜Codex 根据项目范围自动选择
```

It announces again only when the route or responsibility materially changes, so the conversation stays readable. In Codex Desktop, routed work is sent back to the same task with explicit model and reasoning fields; it never creates a separate task. A separate future Codex task must invoke the skill again or explicitly continue under the saved report.

Chinese prompts work too:

```text
$codex-model-router 分析当前项目并优化模型分配
$codex-model-router 查询各模型实际使用比例
$codex-model-router 根据历史成功率和耗时微调任务分配
```

## Outputs

The skill keeps the chat response short and writes the full evidence to:

```text
docs/codex-model-routing-report.md
```

Confirmed usage history is stored as append-only JSONL:

```text
.codex/model-routing-history.jsonl
```

Actual execution, router-analysis usage, and recommended allocation are reported separately. Recommendations are never counted as actual use.

## Retuning thresholds

- Raise a route after at least five comparable attempts with at least 40% failure, escalation, or rework pressure.
- Lower a route after at least ten comparable attempts, at least 90% completion, no pressure events, and deterministic verification.
- Preserve assignments when evidence is below threshold.

## Repository layout

```text
SKILL.md                       Codex workflow and routing contract
agents/openai.yaml             Skill UI metadata
references/                    Routing and usage-ledger rules
scripts/model_usage_ledger.py  Safe append, aggregation, and report rendering
codex-agents/                  Optional named-agent compatibility presets
tests/                         Distribution and ledger tests
install.sh                     Local Codex installer
```

## Privacy and safety

- The ledger stores model, effort, task class, outcome, optional duration, and fallback metadata.
- It does not store prompts, source code, secrets, or conversation text.
- Repository analysis is read-only and does not run builds or tests merely to create a routing plan.
- The skill cannot silently observe unrelated Codex tasks; actual use is recorded only from reliable task metadata or user confirmation.

## Compatibility

This project is designed for Codex installations that support personal skills and custom subagents. If a named GPT-5.6 preset is unavailable, the workflow continues with the current available Codex model and records the fallback instead of pretending the requested model ran.

## Development

Run the standard-library tests:

```bash
python3 -m unittest discover -s tests -v
```

Validate the public distribution:

```bash
python3 tests/validate_distribution.py
```

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).

This is an independent community project and is not affiliated with or endorsed by OpenAI.
