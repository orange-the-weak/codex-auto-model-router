# Project Agent Rules

## Model routing

- 所有代码修改、测试、代码审查、重构、调试和验证任务，自动调用 `$route-project-models` 的 Apply 路径。
- Apply 路径必须先读取或刷新 `docs/codex-model-routing-report.md`，再根据报告把任务拆成最少的可验证任务段。
- 根据报告为每个任务段选择 Luna、Terra 或 Sol，以及匹配的 `low`、`medium`、`high` 或 `xhigh` 推理强度；不得为了展示切换而强行拆分任务。
- 在每个模型或推理强度发生变化的任务段开始前，在当前 Codex 对话框显示模型和推理强度。优先使用 Codex 原生同任务模型覆盖，不创建新的顶层任务。
- 如果所选模型不可用，按 `route-project-models` 的回退规则记录实际可验证的模型；不得把配置模型冒充成实际运行模型。
- 简单问答、文案确认、解释说明和只读查询不走 Apply 路径，也不启动模型路由，以避免额外延迟。
- 只读查询模型使用比例或记录已完成任务时，使用 `route-project-models` 的 Query/Record 快速路径。

## Verification

- 遵守本仓库已有的验证说明；验证范围与任务风险相称。
- 每个 Apply 任务完成后，报告修改文件、执行的检查、剩余风险，并更新项目本地路由账本。
