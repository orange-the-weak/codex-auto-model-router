# Reviewed model catalog and updates

The default Lite path is Sol-first: GPT-6.1 Sol handles ordinary and complex project work, Luna handles mechanical work (and economy's ordinary/scanning lanes), and Astra is reserved for classified complex reasoning/verification failure escalation or explicit choice. See the authoritative [profile matrix and pipeline](routing-profiles.md). GPT-6 Sol and GPT-5.6 Sol are compatibility fallbacks before Astra for an unavailable Sol 6.1 route. Existing GPT-5.6 presets, explicit IDs and historical evidence remain intact; `--model-policy legacy` retains the old recommendations and Terra/high latency lane. Current latency lanes are policy preferences, not measured speed guarantees.

This policy is a task-fit choice, not a claim that benchmarks prove model equivalence. Astra defaults to low, including explicit model-only requests and automatic fallback from another model. Classified reasoning/verification failure may select medium. High, xhigh and max require an explicit user effort request; never infer that request from task difficulty. Use `decide --model gpt-6-astra` for the low default or explicitly provide `--effort` to override it. Explicit model choices never silently fall back. Automatic Astra fallback is marked `quality_degraded`; disclose it before execution. Unsupported efforts fail open locally rather than being rewritten. Native Ultra remains in legacy mode only.

## Availability and dispatch

Historical evidence expiration changes its audit status, not canonical legacy local-substitute eligibility. Expired snapshots stay expired; tests of active evidence use a fixed fixture date rather than extending the snapshot lifetime. Current profile tables remain independent of historical benchmark freshness.

GPT-6.1 Terra is the specialist role for bounded visual understanding, computer use, supplied-material writing, or scoped fixes selected by `task_focus`. It is not a generic replacement for Sol, and complex/high-consequence work still follows Sol-first policy. See [specialist focus](routing-profiles.md#terra-specialist-focus). GPT-6 Luna remains the current efficient model; GPT-5.6 Terra is compatibility-only. Three-role catalogs remain readable; `specialist` is an optional fourth role. API `none` effort is intentionally outside the Router's low-through-max preset contract.

Pass repeated `--available-model <exact-id>` values only for a complete, freshly observed model surface from the actual execution tool. A partial listing must not be treated as complete. Omission means unknown, not unavailable. API documentation, a model picker, or installed preset files alone do not establish that a child agent can run a model. Confirm the returned agent type exists in the current tool surface before spawning. If it does not, use an explicitly supported model override on a bounded non-inherited leaf when available, or continue locally; never invent an agent type or claim it ran.

`recommended_route` is advisory. `execution_route`, leaf types, executor lanes and reuse all follow the resolved route. No executable model means local/deferred work, never an agent dispatch. Before spawning say `Planned executor`; only after an observed successful dispatch say `Execution`. Validate semantic task names against `^[a-z0-9][a-z0-9_]{0,47}$` and use `fork_turns="none"` with an explicit preset.

## Explicit update entry

When the user says “update model catalog” / “更新模型目录”, inspect the current execution model surface and official model documentation, then present additions, removals, effort support, proposed roles and compatibility impact. A request to update authorizes the reviewed catalog/preset/test/documentation edits, not installation, publishing or changing the main conversation model. Preserve explicit pins and Astra's frontier role unless the user asks to change them. Unknown models must not acquire a role based on names or version numbers. Update catalog entries, matching leaf presets, installer payload and tests together; validate before installing or releasing. Catalog changes are ordinary version-controlled files and can be reviewed/reverted independently.

## Lightweight change hint

On the first applicable use in a conversation, if a complete current execution surface is already exposed, compare it without a network call:

```sh
python3 scripts/model_catalog.py --available-models-json '["gpt-6-astra","gpt-6-sol","gpt-6-luna"]'
```

For a later comparison, pass the prior observed list using `--previous-models-json`. The command is read-only and emits additions, removals, unknown IDs and `update_suggested`; it never updates the catalog, enables a model, or writes global state. Warn once per distinct change in the current conversation and offer the explicit update entry. If no complete surface is available, skip the hint and continue work. A list of API models is not a substitute for the Codex execution surface.

There is no background polling or recurring automation. A seven-day cadence can be used as a conversational reminder to re-check when a fresh list is naturally available, not as a claim that a timer or durable monitor exists. Do not repeatedly prompt merely because time passed, and do not interrupt ordinary work to fetch a list.

## Sources and contribution

Official model references: [Astra](https://developers.openai.com/api/docs/models/gpt-6-astra), [Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Terra](https://developers.openai.com/api/docs/models/gpt-6.1-terra), [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), and [model selection](https://developers.openai.com/api/docs/guides/model-selection). Sol/Terra/Luna guidance checked 2026-10-27: the documented task fit supports this project's role choices, not a claim of equal performance or guaranteed Codex-plan savings. Runtime access is independently determined by the host tools.

The role/catalog separation and preferred-versus-executable route design were informed by Davidsoff's [PR #2](https://github.com/orange-the-weak/codex-auto-model-router/pull/2). This implementation retains Astra for [Issue #1](https://github.com/orange-the-weak/codex-auto-model-router/issues/1), preserves legacy compatibility, and covers availability-aware plan/reuse regressions instead of merging the two-model replacement unchanged.
