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

> First public release of Codex Auto Model Router. It started with me repeatedly second-guessing the same Sol, Terra, or Luna choice in Codex, then deciding to turn that little decision loop into a Skill.
>
> - Selects GPT-5.6 Sol, Terra, or Luna with low through max reasoning per task segment; Ultra is opt-in only and disables Router-managed parallelism.
> - Re-evaluates every applicable request instead of inheriting the previous route.
> - Uses bounded dependency-aware concurrency only when useful independent work exists. The full plan is persisted once; executors receive lightweight, hash-bound tickets instead of rebuilt envelopes.
> - Stores bounded worker results in an atomic route inbox. When the last dependency finishes, it can return the synthesis ticket immediately instead of waiting through another planning round.
> - Routes ordinary scans to Luna/high, large bounded scans to Luna/xhigh, deterministic deep work to Luna/max, and keeps genuinely ambiguous or consequential work on Sol.
> - Keeps fallback inside GPT-5.6 whenever any 5.6 model remains available.
> - Calibrates defaults from versioned public benchmark evidence while task evidence and user overrides remain primary.
> - Persists routing state so context compaction cannot force finish/restore to rebuild the full plan.
> - Records verified routing and concurrency outcomes locally without prompts, source code, telemetry, or external APIs. Parallel reports now separate task overlap from orchestration gaps instead of presenting a proxy percentage as measured speedup.
>
> This is my first open-source project. If it sends a task down the wrong path or makes a clumsy split, that concrete example is the feedback I would value most.

## Reddit or OpenAI Developer Community

**Title**

> I built a benchmark-calibrated GPT-5.6 model router for Codex

**Post**

> I kept bouncing between Sol, Terra, and Luna in Codex: this task looked small, but was it really? Did it need more reasoning, or was I just overthinking it? After doing that loop one too many times, I decided to turn my own way of choosing into an open-source Skill.
>
> It uses Luna/medium for mechanical work, Luna/high for ordinary work and normal scans, Luna/xhigh for large bounded scans, and Luna/max only for large deterministic deep work. Terra/high is a latency specialist; real complexity or consequence stays on Sol. Parallel work persists the plan once and gives each executor a hash-bound bounded ticket, so workers start with less repeated context and fewer state-gate surprises.
>
> Native Ultra is deliberately off by default. If you explicitly enable it for one bounded task, the Router steps back from its own parallel scheduler instead of stacking two orchestration systems.
>
> The defaults are calibrated from public coding-agent evidence. Task-specific evidence and explicit user choices still take priority. The Skill runs entirely inside Codex and does not require an external API, API key, or telemetry service.
>
> This is my first open-source project. If you try it and the route feels like overkill, comes up short, splits the work awkwardly, or gets blocked, I would genuinely like to hear about it. Those real routing mistakes are more useful to me than a star.
>
> Repository: https://github.com/orange-the-weak/codex-auto-model-router

## LINUX DO

**标题**

> 做了一个基于公开测评的 Codex GPT-5.6 自动模型路由 Skill

**正文**

> 说实话，Codex 有了 Sol、Terra、Luna、多档推理强度和并行子任务之后，我常常会在几个选项之间来回切：这个活到底该上哪档？是任务真复杂，还是我有点上头了？这样纠结久了，我干脆把自己这套判断整理成了一个开源 Skill。
>
> 它会按当前任务段重新选择模型和推理强度：机械任务用 Luna/medium，普通任务和常规扫描用 Luna/high，大型有界扫描用 Luna/xhigh，只有大型确定性深度任务才升 Luna/max；Terra/high 只负责低延迟，真正复杂或高后果的工作留给 Sol。并发时完整计划只保存一次，每个执行器只拿一张有界票据，少重复读上下文，也少在状态门里兜圈子。
>
> 原生 Ultra 默认关闭。只有用户为单个有界任务显式开启时才使用，同时停掉 Router 自己的并发，避免两套调度互相打架。
>
> 默认策略参考公开 coding-agent 测评，但具体任务证据和用户指定始终优先。整个过程在 Codex 内完成，不需要外部 API、API Key 或遥测服务。
>
> 这是我的第一个开源项目。要是你用下来发现它选强了、选弱了、拆多了，或者莫名卡住了，欢迎直接告诉我；别光点 Star，这些真实案例对我更有用。
>
> GitHub：https://github.com/orange-the-weak/codex-auto-model-router

## What to ask testers for

Ask for only:

1. The visible one-line routing notice.
2. The route they expected.
3. Task shape, outcome, and whether rework or blocking occurred.
4. Codex surface/version and Router release or commit.

Do not ask for prompts, source code, credentials, personal paths, or private project data.
