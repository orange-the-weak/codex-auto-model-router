# Codex Auto Model Router

[![Validate](https://github.com/orange-the-weak/codex-auto-model-router/actions/workflows/validate.yml/badge.svg)](https://github.com/orange-the-weak/codex-auto-model-router/actions/workflows/validate.yml)

**A lightweight Astra/Sol/Luna model and reasoning router for OpenAI Codex.** It recommends Astra, Sol, or Luna (with GPT-5.6 compatibility) and low through max reasoning, prefers low-overhead direct tool concurrency, and automatically uses a model-specific leaf when the route benefit is clearly larger than its overhead.

[简体中文](README.zh-CN.md) · [Routing feedback](https://github.com/orange-the-weak/codex-auto-model-router/issues/new?template=routing-feedback.yml) · [Bug report](https://github.com/orange-the-weak/codex-auto-model-router/issues/new?template=bug-report.yml)

GPT-5.6 gives Codex many useful model and reasoning combinations. Choosing one for every task quickly became its own chore. I built this Skill to make that choice automatic—and then learned that a router which blocks the real work is worse than no router at all.

Version 2 therefore uses a fail-open, benefit-gated default: choose quickly, keep bookkeeping out of the critical path, and create a bounded subagent automatically when model-switch benefit outweighs startup and aggregation cost. This is my first open-source project; practical feedback is genuinely welcome.

**Automatic model routing**

```text
Request
└─ Re-evaluate the task itself
   ├─ Mechanical, ordinary, scan, or deterministic deep work → Luna
   ├─ Explicit latency priority → Terra
   └─ Bounded complex → Sol; highly ambiguous or consequential → Astra
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

Restart Codex after installation. To also install the global prompt hook, opt in with `./install.sh --install-hook` (PowerShell: `./install.ps1 -InstallHook`). The hook asks Codex to apply the Skill when relevant; it does not change the active conversation's model. Use `/hooks` to review, trust, or disable it, then restart Codex.

## Routing profiles

`balanced` preserves the default routes. `economy` favors Luna for more bounded work; `quality` favors Sol for ordinary work and scans. These existing profiles keep Astra at low, or medium after a reasoning/verification failure. Higher Astra effort requires an explicit effort override (including a configured lane override).

Optional `plus` and `pro` profiles must be explicitly selected. They are routing preferences, not subscription detection or service-tier enforcement. Installation preserves existing selections and defaults. Saved selections persist until explicitly changed; `--profile` affects only that invocation. Account details, entitlements, and available models never select a profile.

- Plus: GPT-6 Luna/high for light mechanical tasks, Luna/xhigh by default, GPT-6.1 Sol/high for bounded complexity, then Sol/xhigh for deeper work. No automatic Astra, including fallback; explicit overrides remain available.
- Pro: the same Luna tiers, then GPT-5.6 Sol/xhigh for complex scoped implementation, existing iteration, UI, or careful maintenance, or GPT-6.1 Sol/xhigh for large-repository work, autonomous investigation, complex planning, or deep multi-module work. Only a substantive failure of the corresponding Sol/xhigh branch or genuinely extreme/high-consequence work permits GPT-6 Astra/xhigh. There is no intermediate Astra medium/high step. Selecting Pro opts into potentially substantially higher budget use.

```bash
python3 scripts/router_lite.py profile-show --repository .
python3 scripts/router_lite.py profile-set quality --scope project --repository .
python3 scripts/router_lite.py decide --profile economy --repository .
python3 scripts/router_lite.py profile-set plus --scope project --repository .
python3 scripts/router_lite.py decide --profile pro --task-kind complex --task-subtype ui --repository .
```

For Pro failure escalation, classify the failure with `--prior-failure --prior-failure-kind reasoning` (or `verification`) and supply the observed `--prior-failure-model` and `--prior-failure-effort xhigh`. Missing/wrong model or effort evidence, Luna failure, and infrastructure failure cannot authorize Astra. Ordinary scoped work remains on Luna; generic complexity or ambiguity alone requires Sol first. Generated/cached report recommendations are reclassified under the selected profile; explicit user pins still win. See [routing profiles](references/routing-profiles.md) for task subtypes, global settings, TOML lane overrides, and precedence. Profiles and the optional prompt hook are adapted from [David Soff's contributions](https://github.com/Davidsoff) in PRs #4 and #6.

## Exit for one project

Tell Codex “stop using this Skill in the current project,” or run:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/codex-auto-model-router/scripts/router_lite.py" project-disable --repository .
```

This preserves unrelated settings and adds one managed `[[skills.config]]` entry to the project's `.codex/config.toml`. Router commands stop immediately; restart Codex before the next task so a trusted project can prevent normal Skill loading. The setting applies only to that project and does not change global `~/.codex/config.toml`.

Restore or inspect it with:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/codex-auto-model-router/scripts/router_lite.py" project-enable --repository .
python3 "${CODEX_HOME:-$HOME/.codex}/skills/codex-auto-model-router/scripts/router_lite.py" project-status --repository .
```

`--no-subagents` is different: it disables child agents for one Router command but does not exit the Skill. Project-scoped configuration follows Codex's official [`config.toml` behavior](https://developers.openai.com/codex/config-reference/).

## How it works

Every applicable request follows one of three paths:

| Path | Behavior |
|---|---|
| Local | Recommend a route, then complete the work in the current coordinator. |
| Tool concurrency | Run independent safe tool or process calls together without creating child agents. |
| Benefit-gated subagents | Automatically delegate, reuse, or use multi-model reasoning when route benefit clearly exceeds bounded overhead. |

There is no model Restore, plan hash, cursor, environment guard, or blocking ledger on the default path. Routing or executor startup failure does not block ordinary work. The legacy strict state machine remains available only when the user explicitly requests strict auditing or replay protection.

Visible routing notices follow the language of the current request. English prompts receive English labels, Chinese prompts receive Chinese labels, and model, effort, and reason values remain unchanged.

When execution stays local despite a different recommendation, the notice gives the concise reason: `main conversation model is fixed; leaf startup cost exceeds expected benefit`. Delegated execution similarly labels the switch reason, so a recommendation is never confused with observed model use. The Skill stores only the English canonical template and translates it to the user's current language at runtime.

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
- Explicit models remain pinned; automatic Astra fallback is disclosed. Legacy strict mode retains its GPT-5.6 family guard.

## Model gradient

| Work | Default route |
|---|---|
| Deterministic mechanical work | Luna / medium |
| Ordinary bounded work | Luna / high |
| Large bounded scans or reviews | Luna / xhigh |
| Large deterministic deep work | Luna / max |
| Explicit latency priority | Terra / high |
| Bounded complex work | Sol / medium |
| High ambiguity, coupling, or consequence | Astra / low |
| Failed complex reasoning or verification | Astra / medium |

In the existing default profiles, Astra defaults to low; automatic escalation stops at medium. High, xhigh and max require an explicit user effort request or configured lane override. The explicitly selected Pro top tier above is the sole built-in exception. Choosing Astra alone does not opt into a higher effort. Plus/Pro fallback cannot promote a non-Astra recommendation to Astra.

Current defaults: GPT-6 Luna, GPT-6.1 Sol and GPT-6 Astra; GPT-6 Sol and explicit GPT-5.6 routes remain compatible. Terra/high stays the legacy latency specialist. Ultra and GPT-5.5 fallback are legacy-mode features only. See [model updates](references/model-updates.md) for explicit updates, availability checks and read-only change hints. No background monitor or automatic catalog rewrite is installed.

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
