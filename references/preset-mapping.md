# Explicit custom-agent preset mapping

Use this mapping when the automatic benefit gate selects a model-specific leaf and the agent interface accepts an agent type. No extra permission prompt is required. Local decisions return no Apply `agent_type`; selecting a generic task name does not apply a model preset.

## Assess and Retune (read-only router)

| Model | low | medium | high | xhigh | max |
|---|---|---|---|---|---|
| Sol | `codex_auto_model_router_low` | `codex_auto_model_router` | `codex_auto_model_router_high` | `codex_auto_model_router_xhigh` | `codex_auto_model_router_max` |
| Terra | `codex_auto_model_router_terra_low` | `codex_auto_model_router_terra` | `codex_auto_model_router_terra_high` | `codex_auto_model_router_terra_xhigh` | `codex_auto_model_router_terra_max` |
| Luna | `codex_auto_model_router_luna_low` | `codex_auto_model_router_luna` | `codex_auto_model_router_luna_high` | `codex_auto_model_router_luna_xhigh` | `codex_auto_model_router_luna_max` |

## Apply (workspace-write executor)

| Model | low | medium | high | xhigh | max |
|---|---|---|---|---|---|
| Sol | `codex_auto_model_executor_low` | `codex_auto_model_executor` | `codex_auto_model_executor_high` | `codex_auto_model_executor_xhigh` | `codex_auto_model_executor_max` |
| Terra | `codex_auto_model_executor_terra_low` | `codex_auto_model_executor_terra` | `codex_auto_model_executor_terra_high` | `codex_auto_model_executor_terra_xhigh` | `codex_auto_model_executor_terra_max` |
| Luna | `codex_auto_model_executor_luna_low` | `codex_auto_model_executor_luna` | `codex_auto_model_executor_luna_high` | `codex_auto_model_executor_luna_xhigh` | `codex_auto_model_executor_luna_max` |

The benefit-gated subagent path gives each Apply executor a direct bounded task: goal, relevant paths and decisions, acceptance criteria, constraints, validation budget, stop condition, and recovery budget. Treat the capsule as self-contained: do not load unrelated memory or add redundant validation after acceptance is proven. It does not send IDs, hashes, tickets, ledgers, environment markers, or the full chat. The executor reads applicable project instructions, performs only that task, never delegates, sends one final result, and ends its current turn immediately.

For agent-parallel work, every executor is still a leaf using exactly one Apply preset. The Coordinator alone owns dependencies, write-scope conflicts, free capacity, wait-any refill, failure handling, aggregation, and final cleanup. A parallel worker must not spawn another agent even when its model supports proactive delegation.

All presets intentionally target GPT-5.6. If one preset is unavailable, choose another 5.6 preset using Sol → Terra → Luna, Terra → Sol → Luna, or Luna → Terra → Sol. Do not substitute a generic GPT-5.5 agent while any listed 5.6 preset remains selectable.

The legacy strict ticket protocol remains documented in [execution-state-machine.md](execution-state-machine.md) and is used only after explicit strict-mode selection.

`max` is a single-route reasoning effort. `ultra` is disabled by default and has no Router preset. It is used only after an explicit user opt-in for one bounded Sol or Terra task, with Router-managed parallelism disabled because native Ultra may delegate proactively.
