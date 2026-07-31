# Community launch kit

Use these drafts as starting points. Keep the final posts personal and answer early feedback yourself.

## GitHub settings

**Description**

> Evidence-calibrated GPT-5.6 model, reasoning, and concurrency routing for OpenAI Codex—no external API required.

**Topics**

`openai-codex`, `codex`, `codex-skill`, `gpt-5-6`, `model-routing`, `reasoning`, `ai-coding-agent`, `developer-tools`

## First release

**Suggested tag:** `v0.1.0`

**Title:** `v0.1.0 — Evidence-calibrated dynamic routing for Codex`

**Notes**

> First public release of Codex Auto Model Router.
>
> - Selects GPT-5.6 Sol, Terra, or Luna and reasoning effort per task segment.
> - Re-evaluates every applicable request instead of inheriting the previous route.
> - Uses bounded dependency-aware concurrency only when useful independent work exists.
> - Keeps fallback inside GPT-5.6 whenever any 5.6 model remains available.
> - Calibrates defaults from versioned public benchmark evidence while task evidence and user overrides remain primary.
> - Records verified routing and concurrency outcomes locally without prompts, source code, telemetry, or external APIs.
>
> This is my first open-source project. Real routing examples—especially wrong or inefficient choices—are the most useful feedback.

## Reddit or OpenAI Developer Community

**Title**

> I built a benchmark-calibrated GPT-5.6 model router for Codex

**Post**

> Codex now offers Sol, Terra, Luna, several reasoning levels, and parallel agents. I kept spending time deciding which combination was enough for each task, so I built an open-source Skill that makes the choice per task segment.
>
> It routes clear mechanical work toward Luna, bounded ordinary work toward Terra, and complex or high-consequence work toward Sol. It can use dependency-aware concurrency, but only when the task has useful independent boundaries and verified capacity.
>
> The defaults are calibrated from public coding-agent evidence. Task-specific evidence and explicit user choices still take priority. The Skill runs entirely inside Codex and does not require an external API, API key, or telemetry service.
>
> This is my first open-source project. I am mainly looking for real examples where the route was too strong, too weak, fragmented, or blocked—not just stars.
>
> Repository: https://github.com/orange-the-weak/codex-auto-model-router

## LINUX DO

**标题**

> 做了一个基于公开测评的 Codex GPT-5.6 自动模型路由 Skill

**正文**

> Codex 现在有 Sol、Terra、Luna、多档推理强度和并行子任务。我在不同项目里反复判断“这个任务该用哪档”，所以把这套判断整理成了一个开源 Skill。
>
> 它会按当前任务段重新选择模型和推理强度：机械任务倾向 Luna，边界清晰的普通任务倾向 Terra，复杂、高歧义或高后果任务使用 Sol。存在真正独立的任务边界时才启用并发，不会为了凑数量强行拆分。
>
> 默认策略参考公开 coding-agent 测评，但具体任务证据和用户指定始终优先。整个过程在 Codex 内完成，不需要外部 API、API Key 或遥测服务。
>
> 这是我的第一个开源项目。我更希望收集“选强了、选弱了、拆多了、阻塞了”的真实案例，而不只是 Star。
>
> GitHub：https://github.com/orange-the-weak/codex-auto-model-router

## What to ask testers for

Ask for only:

1. The visible one-line routing notice.
2. The route they expected.
3. Task shape, outcome, and whether rework or blocking occurred.
4. Codex surface/version and Router release or commit.

Do not ask for prompts, source code, credentials, personal paths, or private project data.
