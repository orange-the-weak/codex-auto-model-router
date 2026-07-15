# Codex Auto Model Router

**面向 OpenAI Codex 的 GPT-5.6 自动模型与推理强度选择 Skill。** 将一次请求拆成最少的必要 Segment，在阶段边界切换 Sol、Terra 或 Luna，并为每段使用刚好够用的推理强度；不需要外部 API 或 API Key。

[English README](README.md)

## 为什么做这个工具？

GPT-5.6 在 Codex 中提供 Sol、Terra、Luna 和多档推理强度。反复判断“哪个组合够用、何时值得切换”也成了一项工作。这个 Skill 会生成最小必要 Segment 计划，为每段选择路由，在同一 Codex 任务内自动切换，并在结束后恢复原设置。

## 快速安装

在 Codex 中发送：

```text
$skill-installer 从 GitHub 安装 https://github.com/orange-the-weak/codex-auto-model-router
```

安装后重启 Codex。这会安装核心 Skill；如需 24 个可选自定义 Agent 预设，或从旧名称迁移，请使用：

```bash
git clone https://github.com/orange-the-weak/codex-auto-model-router.git
cd codex-auto-model-router
./install.sh
```

## 路由速览

| 路由 | 适合任务 | 默认推理 |
|---|---|---|
| **GPT-5.6 Luna** | 重复修改、格式整理、文件移动等可确定性验证的工作 | `medium`，检查明确时降到 `low` |
| **GPT-5.6 Terra** | 功能实现、局部 Bug、测试、UI 调整和边界清晰的重构 | `medium` |
| **GPT-5.6 Sol** | 架构、安全、迁移、并发、跨系统诊断和高风险审查 | `medium`，仅在有明确理由时升到 `high` 或 `xhigh` |

用户明确指定的模型或推理强度始终优先。对于很小的任务，如果切换和恢复比执行本身更慢，会保持当前路由。

## 主要能力

- 生成最小必要的确定性线性 Segment 计划；简单请求仍只用一段，确实复杂或大型的任务可以使用更多阶段。
- 为每段选择模型与推理强度，通过原生同任务覆盖依次切换，最后只恢复一次原路由。
- 合并相邻同路由 Segment，微小任务不切换。默认预算为 4 段/4 次切换，符合条件时自动扩到 6/6，用户可显式设置到 8/8。
- 任一 Segment 失败即停止，不循环换模型重试；原生切换不可用时才使用显式模型 Agent 或当前模型。
- 每个 Segment 边界在 Codex 对话框说明一次自动选择的模型、推理强度和原因。
- 用本地 JSONL 账本记录可验证的 Segment 模型与推理使用情况。
- 根据完成、失败、升级、返工和耗时证据微调分配。
- 完整分析写入 Markdown 报告，对话框只保留简短结论。
- 不接入外部模型网关，也不需要 API Key。

预算规则是明确的：通常上限为 `4/4`；只有归一化计划确实需要更多阶段，并且包含 `complex` 或 `large` 任务时，Codex 才自动扩到 `6/6`，高风险本身不会触发扩容。用户可以设置一个共用上限，也可以分别指定 `1–8` 的 Segment 与切换预算；切换次数包含最终恢复。

## 最近更新

- **动态 Segment Apply：** 分析、实现、验证和审查可以按需使用不同路由；简单任务不拆段。
- **自适应且有边界：** 通常保持 4/4，复杂或大型计划按需扩到 6/6，用户可在 8/8 硬上限内自选预算。
- **切换更稳：** 通过可靠任务元数据完成同任务覆盖，整条链路结束后只恢复一次原模型与推理强度。
- **回退一致：** 只有能明确选择模型时才使用自定义 Agent，否则继续使用当前模型并如实标注。
- **交接清楚：** 每段只显示一次路由说明，正常完成不再反复提示运行时身份状态。
- **可查询、可微调：** 实际 Segment 执行、分析调用和建议比例分开记录，可再次调用 Skill 查询或调整。
- **更名迁移完整：** 安装脚本会升级旧的 `codex-model-router` 名称和对应预设，不影响其他 Codex 文件。

## 使用

在 Codex 中调用 `$codex-auto-model-router`：

```text
$codex-auto-model-router 分析当前项目并推荐模型分配
$codex-auto-model-router 按已保存的路由规划实现这个功能
$codex-auto-model-router 执行这次迁移，最多使用 7 个 Segment 和 7 次切换
$codex-auto-model-router 最多使用 6 个 Segment，但不超过 4 次切换
$codex-auto-model-router 这个任务使用 GPT-5.6 Terra high
$codex-auto-model-router 查询实际模型与推理强度使用比例
$codex-auto-model-router 记录：Terra low 完成 UI 调整，耗时 90 秒
$codex-auto-model-router 根据历史结果微调分配
```

每个 Segment 开始前，Codex 会显示一次：

```text
Codex 自动路由｜Segment 1/3：分析改动｜模型：GPT-5.6 Sol｜推理：high｜根据任务歧义自动选择
```

下一段可以切换到 Terra 实现，再用 Luna 做确定性检查，全程不会创建新的顶层 Codex 任务。任一段失败会停止链路，最后只恢复一次原路由。如果当前界面不支持带模型参数的同任务续接，会优先使用能够明确选择模型的自定义 Agent；仍不可用时回退到当前模型。

## 报告、记录与隐私

- 完整报告：`docs/codex-model-routing-report.md`
- 本地使用账本：`.codex/model-routing-history.jsonl`

实际 Segment 执行、路由分析和建议分配会分开统计，建议不会被算成真实使用。账本只保存路由元数据和结果，不保存提示词、源码、密钥或对话正文。

自动微调保持保守：同类任务至少 5 次且压力事件达到 40% 才升档；至少 10 次、完成率达到 90%、没有压力事件且可以确定性验证，才会降档。

## 关于这个项目

这是我的第一个开源项目。它来自一个很实际的困扰：我在不同 Codex 项目里一遍遍做相同的模型选择。这个工具还在持续改进，我也在学习怎样把流程做得更清楚、更可靠。欢迎提交真实使用反馈、问题报告，或一个小小的改进。

## 兼容性

本项目面向支持个人 Skill 的 Codex。原生同任务模型覆盖和具名自定义 Agent 是否可用，取决于当前 Codex 界面提供的能力。如果目标 GPT-5.6 路由不可用，流程会使用可用模型继续，并记录回退，不会声称发生了无法验证的切换。

## 开发与贡献

```bash
python3 -m unittest discover -s tests -v
python3 tests/validate_distribution.py
```

欢迎通过 [CONTRIBUTING.md](CONTRIBUTING.md) 参与改进；安全问题请参阅 [SECURITY.md](SECURITY.md)。

## 许可证

MIT。详见 [LICENSE](LICENSE)。

这是独立社区项目，与 OpenAI 无隶属关系，也未获得 OpenAI 官方背书。
