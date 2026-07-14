# Codex Model Router

一个面向 OpenAI Codex 的任务级模型路由 Skill：根据项目和任务难度，在 GPT-5.6 Sol、Terra、Luna 之间分配工作，自动选择 `low`、`medium`、`high` 或 `xhigh` 推理强度，并通过真实使用记录持续微调。

[English README](README.md)

## 主要能力

- 分析项目结构，为不同任务推荐最小够用的模型和推理强度。
- Apply 模式会把同一次调用中请求的实际工作拆成任务段，通过 Codex 原生的同任务 `model` 与 `thinking` 覆盖交给匹配模型执行，而不只是生成规划文档。
- 默认使用 Sol / medium 完成首次分析，也允许用户指定任意 Sol、Terra、Luna 和推理强度组合。
- 每个明显不同的任务段开始前，在 Codex 对话框显示模型、推理强度、任务目的和回退状态。
- Query 和 Record 使用本地脚本快速完成，不启动分析 Agent。
- 分开统计实际执行比例、分析调用比例和最新建议比例。
- 根据成功、失败、升级、返工和耗时证据微调任务分配。
- GPT-5.6 不可用时回退到当前可用 Codex 模型，并如实记录。
- 完整报告写入 Markdown，对话框只显示简短结论和预计增效。
- 不需要 API Key，也不接入外部模型 API。

## 安装

```bash
git clone https://github.com/<你的-GitHub-用户名>/codex-model-router.git
cd codex-model-router
./install.sh
```

安装后重新启动 Codex，使 Skill 和自定义 Agent 生效。

## 使用示例

```text
$codex-model-router 分析当前项目并优化模型分配
$codex-model-router 查询各模型实际使用比例
$codex-model-router 记录：Terra low 完成 UI 调整，耗时 90 秒
$codex-model-router 根据历史成功率、返工和耗时微调任务分配
$codex-model-router 用 Terra high 分析当前项目
$codex-model-router 按照已保存的路由规划实现这个功能
```

任务段开始前会显示一条简洁提示；只有模型、推理强度或职责明显变化时才再次显示：

```text
Codex 自动路由｜任务段：项目分析｜模型：GPT-5.6 Sol｜推理：medium｜Codex 根据项目范围自动选择
```

在 Codex Desktop 中，任务段通过带有明确模型和推理字段的续接消息回到当前任务，不会新开任务。不能把普通子任务名称当成模型已经切换的证据。这项约束覆盖该次 Skill 调用所协调的工作；以后另开的独立任务需要再次调用 Skill，或明确要求沿用已保存的路由报告。

## 输出文件

- 完整报告：`docs/codex-model-routing-report.md`
- 使用账本：`.codex/model-routing-history.jsonl`

实际执行、Skill 分析调用和建议分配会分开统计。建议不会被伪装成真实使用记录，账本也不会保存提示词、源码、密钥或对话内容。

## 调整阈值

- 同类任务至少 5 次，失败、升级或返工压力达到 40%，才建议升档。
- 同类任务至少 10 次、成功率达到 90%、没有压力事件且可确定性验证，才建议降档。
- 样本不足时保持原分配。

## 许可证

MIT。详见 [LICENSE](LICENSE)。

这是独立社区项目，与 OpenAI 无隶属或官方背书关系。
