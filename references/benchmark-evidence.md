# Benchmark evidence and routing implications

Snapshot: `gpt56-routing-evidence-2026-07-31-r3`. The machine-readable source is
[`benchmark-evidence.json`](benchmark-evidence.json). It expires after 90 days; a stale,
missing, or invalid snapshot disables evidence-derived lanes and falls back to the
deterministic task policy. Apply never fetches the network.

## What counts as evidence

Evidence is ranked by how closely it matches Codex work:

1. **High weight:** OpenAI's coding results and Codex rate card, Artificial Analysis's
   Coding Agent Index, and CursorBench 3.2. CursorBench uses ambiguous multi-file tasks
   from real Cursor sessions; its cost field is not Codex subscription cost.
2. **Medium weight:** Artificial Analysis Intelligence Index results by reasoning effort.
   These are API measurements, so they inform relative capability, latency, and output
   growth only. They are not Codex wall time or Codex subscription cost.
3. **Low weight:** ChatBench v0.2.0 category scores. They are weighted proxies derived
   from Artificial Analysis intelligence, context, tool, speed, and price data—not
   independent Coding or Agent task runs. Use only for relative latency and cost context.
4. **Supporting:** the original DeepSWE, Terminal-Bench, and SWE-Bench Pro papers explain
   task construction and validity. Community anecdotes and this repository's easy local
   fixtures do not create hard routing rules.

The Coding Agent Index v1.1 covers 321 tasks across DeepSWE (113), Terminal-Bench v2
(84 compatible tasks), and SWE-Atlas-QnA (124), with three repeats per task. Its public
methodology reports pass@1 plus pooled token and wall-time telemetry.

## Coding-agent results

| Model | AA Coding Agent Index | SWE-Bench Pro | DeepSWE v1.1 | Terminal-Bench 2.1 |
| --- | ---: | ---: | ---: | ---: |
| GPT-5.6 Sol | 80.0 | 64.6% | 72.7% | 88.8% |
| GPT-5.6 Terra | 77.4 | 63.4% | 69.6% | 87.4% |
| GPT-5.6 Luna | 74.6 | 62.7% | 67.2% | 84.7% |
| GPT-5.5 | 76.4 | 59.4% | 67.0% | 85.6% |

This supports three tiers, but not a blanket rule that every complex task needs Sol/high:
Terra and Luna remain close on coding-agent pass rates, while Sol is the strongest choice
when ambiguity, coupling, or consequences increase.

Sol Ultra's 91.9% Terminal-Bench 2.1 result is excluded from the automatic routing matrix
because it is a multi-agent variant. Ultra is disabled by default and available only when
the user explicitly enables one bounded Sol or Terra Apply Segment. That request disables
Router-managed parallelism so native and Router orchestration never stack. `max` remains
a normal single-route effort and is included below.

## Current Codex credits

The OpenAI Codex rate card observed on 2026-07-31 lists credits per 1M input / cached
input / output tokens:

| Model | Input | Cached input | Output |
| --- | ---: | ---: | ---: |
| GPT-5.6 Sol | 125 | 12.5 | 750 |
| GPT-5.6 Terra | 50 | 5 | 300 |
| GPT-5.6 Luna | 5 | 0.5 | 30 |

Luna therefore uses 4% of Sol's credits at each token type. Actual task credits still
depend on token mix and agent activity; low token price alone never justifies more
reasoning.

## Effort findings

The independent API surface shows a consistent trade-off. Sol rises from 49 intelligence
at low to 54/56/58/59 at medium/high/xhigh/max. Artificial Analysis reports Luna/max at
51 intelligence, about 184 output tokens/second, 116.5 seconds TTFT, and 130M aggregate
evaluation output tokens. It is capable but not a quick-start lane.

CursorBench 3.2 reports ambiguous multi-file Agent results from real Cursor sessions:

| Route | Score | Avg cost | Tokens | Steps |
| --- | ---: | ---: | ---: | ---: |
| Sol max | 67.2% | $5.69 | 28,320 | 48 |
| Terra max | 64.9% | $2.31 | 32,969 | 47 |
| Sol xhigh | 64.5% | $3.88 | 19,699 | 38 |
| Sol high | 63.5% | $2.79 | 13,867 | 32 |
| Luna max | 61.1% | $0.39 | 87,973 | 61 |
| Sol medium | 60.0% | $1.95 | 9,747 | 27 |
| Terra xhigh | 59.2% | $1.15 | 16,089 | 29 |
| Luna xhigh | 57.7% | $0.23 | 22,480 | 48 |
| Luna high | 56.8% | $0.16 | 15,141 | 40 |
| Terra high | 54.2% | $0.71 | 9,468 | 23 |
| Sol low | 52.6% | $1.01 | 5,104 | 19 |
| Terra medium | 50.3% | $0.49 | 6,222 | 20 |
| Luna medium | 47.7% | $0.08 | 7,095 | 28 |
| Terra low | 46.9% | $0.42 | 5,312 | 19 |
| Luna low | 37.6% | $0.03 | 3,209 | 17 |

The public page does not disclose the exact task count or category-level scores, and
small score differences may not be statistically meaningful. Cursor cost applies
published API pricing to task tokens; it is not Codex subscription cost. Luna/high gains
9.1 points over Luna/medium at moderate work growth, while xhigh adds only 0.9 points.
Luna/max approaches Sol/medium-to-high quality but expands to 87,973 tokens and 61 steps.
That supports a high intermediate lane and a much narrower max lane.

ChatBench's Coding proxy places Luna/high, xhigh, and max close together at 78.1, 78.6,
and 79.4. Its underlying API response totals diverge sharply: about 11.2, 45.6, and
119.4 seconds. Terra/low and medium are nearly tied on API response time at about 5.4
and 5.6 seconds, while CursorBench gives medium a 3.4-point quality advantage. ChatBench
does not publish a Luna/low snapshot; that cell remains missing rather than inferred.
These values are proxy context only, not Codex task wall-clock measurements.

The updated automatic frontier removes three weak defaults. Luna/medium scores 47.7%
versus Luna/low at 37.6%; with Luna already using only 4% of Sol's Codex credits, the
10.1-point quality loss is not justified as an automatic saving. Terra/low scores 46.9%
at a $0.42 API-cost proxy, while Luna/medium scores 47.7% at $0.08. Terra/medium improves
to 50.3%, but Luna/high reaches 56.8% at $0.16. Terra remains useful at high: it scores
54.2% versus Sol/low at 52.6%, costs $0.71 versus $1.01 on CursorBench, and ChatBench's
API response proxy is about 6.3 seconds versus 11.1 seconds. This does not prove Codex
wall-clock speed, but it supports one explicit latency-specialist Terra lane.

Therefore:

- use Luna/medium as the automatic floor for mechanical and repeatable work;
- use Luna/high as the ordinary bounded default;
- raise to Luna/max only for genuinely deep or large deterministic work whose latency
  budget can absorb the much larger token and step count;
- use Terra/high only when fast return is explicitly prioritized and the task remains
  below a Sol complexity or consequence boundary;
- use Sol/medium for bounded complex work;
- use Sol/high for high ambiguity, high coupling, judgment-heavy verification, or high
  consequences;
- use Sol/xhigh only when a complex attempt has already failed or the user explicitly asks.

These are the seven automatic lanes. The complete low-through-max matrix remains available
for explicit user overrides and compatibility experiments; automatic removal is not a
claim that the underlying model-effort combinations are unsupported.

GPT-5.5 is retained as a comparison baseline. This snapshot has stable low, medium, and
high observations, but no stable xhigh observation; that cell is deliberately missing
rather than inferred. GPT-5.5 is not a normal routing lane: while any GPT-5.6 model is
available, availability fallback must remain inside Sol, Terra, or Luna. After verified
GPT-5.6 execution, an original GPT-5.5 setting is audit metadata, not a Restore target.

## Efficiency hypothesis

Against an all-Sol/medium baseline, the illustrative mix is 25% mechanical, 40% bounded
ordinary, 5% latency-priority ordinary, 25% bounded complex, and 5% uncertain or
high-consequence work. It reduces the weighted Artificial Analysis TTFT proxy by about 9%,
the ChatBench response proxy by about 19%, and the Cursor cost proxy by about 62%. The
Intelligence Index output proxy rises by about 92% because Luna/high produces much more
output; that may improve quality but is not counted as a speed gain. None of these are
Codex end-to-end measurements, and API cost is not Codex subscription cost. The conservative
planning estimate is therefore **10–20% faster AI-work turnaround** for a similar mixed
workload. Luna/max is not counted as a speed gain; its potential rework benefit must be
validated from the local Segment ledger. Treat the range as a hypothesis, not a universal
benchmark.

Task evidence and user overrides always outrank this snapshot. A benchmark prior never
weakens a high-consequence route and never forces a runtime network request.

## Sources

- [OpenAI: GPT-5.6](https://openai.com/index/gpt-5-6/)
- [OpenAI: Codex subagent model and reasoning guidance](https://learn.chatgpt.com/docs/agent-configuration/subagents#choosing-models-and-reasoning)
- [OpenAI: Codex rate card](https://help.openai.com/en/articles/20001106-codex-rate-card)
- [CursorBench 3.2](https://cursor.com/cn/cursorbench)
- [CursorBench methodology](https://cursor.com/blog/cursorbench)
- [ChatBench v0.2.0](https://benchmarks.chatbench.org/)
- [ChatBench Coding snapshot](https://benchmarks.chatbench.org/snapshots/leaderboards/coding/latest.json)
- [Artificial Analysis: GPT-5.6 results](https://artificialanalysis.ai/articles/gpt-5-6-has-landed/)
- [Artificial Analysis: GPT-5.6 Luna max](https://artificialanalysis.ai/models/gpt-5-6-luna)
- [Artificial Analysis: Coding Agent Index methodology](https://artificialanalysis.ai/methodology/coding-agents-benchmarking)
- [Artificial Analysis: Coding Agent leaderboard](https://artificialanalysis.ai/agents/coding-agents)
- [Artificial Analysis: Intelligence Index methodology](https://artificialanalysis.ai/methodology/intelligence-benchmarking)
- [DeepSWE paper](https://arxiv.org/abs/2607.07946)
- [Terminal-Bench paper](https://arxiv.org/abs/2601.11868)
- [SWE-Bench Pro paper](https://arxiv.org/abs/2509.16941)

The per-effort source URL pattern is stored with the metrics in the JSON snapshot. Refresh
the snapshot before its expiry and rerun the full validators before publishing a new policy.
