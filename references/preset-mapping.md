# Explicit custom-agent preset mapping

Use this compatibility mapping only when the subagent interface explicitly accepts a preset or agent name. Selecting a generic task name does not apply a preset.

## Assess and Retune (read-only router)

| Model | low | medium | high | xhigh |
|---|---|---|---|---|
| Sol | `codex_auto_model_router_low` | `codex_auto_model_router` | `codex_auto_model_router_high` | `codex_auto_model_router_xhigh` |
| Terra | `codex_auto_model_router_terra_low` | `codex_auto_model_router_terra` | `codex_auto_model_router_terra_high` | `codex_auto_model_router_terra_xhigh` |
| Luna | `codex_auto_model_router_luna_low` | `codex_auto_model_router_luna` | `codex_auto_model_router_luna_high` | `codex_auto_model_router_luna_xhigh` |

## Apply (workspace-write executor)

| Model | low | medium | high | xhigh |
|---|---|---|---|---|
| Sol | `codex_auto_model_executor_low` | `codex_auto_model_executor` | `codex_auto_model_executor_high` | `codex_auto_model_executor_xhigh` |
| Terra | `codex_auto_model_executor_terra_low` | `codex_auto_model_executor_terra` | `codex_auto_model_executor_terra_high` | `codex_auto_model_executor_terra_xhigh` |
| Luna | `codex_auto_model_executor_luna_low` | `codex_auto_model_executor_luna` | `codex_auto_model_executor_luna_high` | `codex_auto_model_executor_luna_xhigh` |

Every Apply prompt includes `route_id`, `segment_id`, exact bounded goal, repository path, acceptance criteria, and validation budget. Apply uses an executor preset with only `ROUTE_PROJECT_MODELS_EXECUTOR=1`; the coordinator validates the result and advances the immutable plan cursor. Assess and Retune use a router preset with only `ROUTE_PROJECT_MODELS_SUBAGENT=1`. Never send both markers. The selected agent must not plan, route, advance, or delegate again.

For `dependency-parallel-v1`, every executor is still a leaf using exactly one Apply preset. Add immutable dependencies, plan hash, access mode, `write_scopes`, `conflict_keys`, and the selected Segment route to its prompt. The Coordinator alone owns the frontier, wait-any loop, failure transition, and deterministic aggregation. A parallel worker must not spawn another agent even when its model supports proactive delegation.

All presets intentionally target GPT-5.6. If one preset is unavailable, choose another 5.6 preset using Sol → Terra → Luna, Terra → Sol → Luna, or Luna → Terra → Sol. Do not substitute a generic GPT-5.5 agent while any listed 5.6 preset remains selectable.
