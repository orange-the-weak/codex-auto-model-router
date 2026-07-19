# Codex Auto Model Router：动态分段路由

**为 OpenAI Codex 自动执行动态分段的 GPT-5.6 模型、推理强度与并发路由。** 策略经公开测评校准，为每个有界任务选择刚好够用的 Sol、Terra 或 Luna；不需要外部 API 或 API Key。

[English README](README.md)

## 为什么做这个工具？

GPT-5.6 在 Codex 中提供三种模型和多档推理强度。这个 Skill 自动重新评估每个有价值的 Segment，只在任务受益时动态切换，完成后恢复可验证的原 GPT-5.6 路由。

## 快速安装

在 Codex 中发送：

```text
$skill-installer 从 GitHub 安装 https://github.com/orange-the-weak/codex-auto-model-router
```

安装后重启 Codex。如需全部 24 个可选自定义 Agent 预设，或从旧名称迁移，可克隆后运行对应系统的安装脚本：

```bash
git clone https://github.com/orange-the-weak/codex-auto-model-router.git
cd codex-auto-model-router
./install.sh
```

Windows PowerShell：

```powershell
.\install.ps1
```

## 基于公开测评的路由

当前策略参考 OpenAI coding 结果、Artificial Analysis Coding Agent Index，以及 DeepSWE、Terminal-Bench、SWE-Bench Pro 的原始方法。API 分档数据只用于判断相对能力、延迟和输出量，不代表 Codex 实际耗时或订阅成本。

| 路由 | 默认用途 |
|---|---|
| **Luna low** | 明确的机械修改和确定性检查 |
| **Luna medium** | 大型重复批次 |
| **Terra low** | 边界清晰、可确定验证的普通任务 |
| **Terra medium** | 多文件或多约束的普通任务 |
| **Sol medium** | 有界复杂任务 |
| **Sol high** | 高歧义、高耦合、判断型验证或高后果任务 |
| **Sol xhigh** | 复杂任务已有失败，或用户明确指定 |

任务证据和用户指定始终优先。测评快照带版本、离线运行、有效期 90 天；缺失、损坏或过期时自动回退确定性规则，不阻塞任务。详见[完整测评报告](references/benchmark-evidence.md)和[机器可读快照](references/benchmark-evidence.json)。

按示例混合任务估算，相比所有任务固定使用 Sol/medium，当前策略预计可让 **AI 工作周转增效约 15–30%**。这是保守假设，不是通用 Codex 实测；后续应由本地使用记录继续校准。

## 工作方式

- 每次适用请求都重新评估，不继承上一轮的强弱档位。
- 单 Segment 使用快速路径：当前路由已匹配时跳过完整 DAG、cursor、claim 和 Restore 链；多段状态检查合并为一次 `begin` 与一次 `finish`。
- 只有分析、实现、验证或审查确实需要不同能力时才拆分。
- 自动并行任务上限为 4，再按独立宽度和已观测空闲槽位减少。主线程需占 1 个槽位负责调度与汇总；因此总槽位为 4 时，并行任务峰值通常是 3。
- 对话框将主任务算入并发计划，简化显示为 `并发计划：4 个任务（含主任务）`；内部仍按 1 个主任务 + 3 个子任务校验容量。
- 容量未验证时先派发一个任务，确认空闲后再补位；超过 4 必须证明有足够空闲容量，不预建等待队列。
- 采用关键路径优先的 wait-any 调度降低尾延迟；兼容的短兄弟任务可合并，长任务只在真实独立边界拆分。
- 完整对话留在主线程；并行任务只接收目标、必要决策、范围、验收和不可变 ID 组成的上下文胶囊。
- 子智能体任务名由内容生成，例如 `runtime_ledger_audit`，不使用随机名或 `worker_1`；Codex 客户端额外显示的系统昵称不受 Skill 控制。
- 并行写入必须拥有不相交的路径；Git index、lockfile、工程文件、migration、部署目标和共享模拟器等资源通过冲突键串行化。
- 默认预算 4 个 Segment/4 次切换；复杂或大型计划可自动扩到 6/6；用户可显式设置，但 8/8 是硬上限。最终恢复计入切换次数。
- 回退保持在 GPT-5.6 家族内：Sol 依次尝试 Terra、Luna；Terra 依次尝试 Sol、Luna；Luna 依次尝试 Terra、Sol。只有整个 5.6 家族不可用时才允许 GPT-5.5。
- 每段只显示一次模型和推理强度；失败立即停止；最后只恢复一次可验证的原路由。
- 本地 JSONL 账本只记录可验证执行，推荐路由不会被算成真实使用。
- 每个并行任务派发确认和结果收到时，都由协调线程用同一 monotonic clock 自动打点；实际用时、并行任务累计用时、峰值并发和槽位利用都由区间推导，模型不能填写时间数字。
- 旧的聚合计时记录继续可读，但退出 verified 历史，不再影响并发统计。
- 仅用任务元数据或用户确认统计路由、排队、启动、切换/恢复、有效执行、往返次数和状态门阻塞；缺失值不猜。
- Apply 简报只覆盖当前运行并原样使用运行时生成的并发行；Query/历史明确标注为历史聚合。只有完整的 schema-v2 逐任务区间才显示实测指标，否则显示 `测量：待记录`。`并行省时估算` 是相对于同批任务串联相加的对照，不是受控 A/B 实测。

## 使用

```text
$codex-auto-model-router 分析当前仓库并推荐路由
$codex-auto-model-router 动态分段实现这个功能
$codex-auto-model-router 这个任务使用 GPT-5.6 Terra high
$codex-auto-model-router 查询使用比例并根据真实结果微调
```

对话框提示示例：

```text
Codex 自动路由｜Segment 1/3：分析改动｜模型：GPT-5.6 Sol｜推理：high｜任务歧义较高
Codex 自动路由｜并发计划：4 个任务（含主任务）｜来源：smart-reduced｜调度：关键路径优先
并发：峰值 4（含主任务）｜实际用时：2分0秒｜并行任务累计用时：4分48秒｜并行省时估算：58%｜槽位利用：85%
```

完整报告写入 `docs/codex-model-routing-report.md`，可验证使用记录保存在 `.codex/model-routing-history.jsonl`。账本只保存路由元数据和结果，不保存提示词、源码、密钥或对话正文。

## 关于这个项目

这是我的第一个开源项目。它来自一个很实际的困扰：我在不同 Codex 项目里反复做同样的模型选择。欢迎真实使用反馈、问题报告和小改进。

## 兼容性与开发

本项目需要支持个人 Skill 的 Codex。原生同任务覆盖和自定义 Agent 取决于当前界面。只要任一 GPT-5.6 路由可选，就不会回退或恢复到 GPT-5.5，也不会使用含糊的 `available-default`。如果任务从 5.5 开始并成功进入 5.6，结束后会留在已验证的 5.6 路由。只有 Sol、Terra、Luna 全部不可用时才允许 5.5，并明确记录和提示。

```bash
python3 -m unittest discover -s tests -v
python3 tests/validate_distribution.py
```

参与改进请查看 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题见 [SECURITY.md](SECURITY.md)，许可证见 [LICENSE](LICENSE)。这是独立社区项目，与 OpenAI 无隶属关系，也未获得官方背书。
