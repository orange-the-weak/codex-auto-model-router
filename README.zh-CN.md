# Codex Auto Model Router：动态分段路由

**为 OpenAI Codex 自动执行动态分段的 GPT-5.6 模型、推理强度与并发路由。** 策略经公开测评校准，为每个有界任务选择最匹配的 Sol、Terra 或 Luna 模型及推理强度；不需要外部 API 或 API Key。

[English README](README.md)

**自动选择模型**

```text
任务
└─ 评估范围、歧义、风险和时延
   ├─ 重复、普通或确定性任务 → Luna ─┐
   ├─ 时延敏感任务 → Terra ──────────┼─→ 执行 → 验证
   └─ 复杂、高歧义或高风险任务 → Sol ─┘
```

**依赖感知并发**

```text
任务依赖图
├─ 独立任务 A ─┐
├─ 独立任务 B ─┼─→ 验证并汇总
└─ A 完成后执行 C ─┘

共享文件或资源 → 串行执行
```

## 快速安装

在 Codex 中发送：

```text
$skill-installer 从 GitHub 安装 https://github.com/orange-the-weak/codex-auto-model-router
```

安装后重启 Codex。如需全部 30 个可选自定义 Agent 预设，或从旧名称迁移，可克隆后运行对应系统的安装脚本：

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

当前策略参考 OpenAI coding 结果与 Codex credit rate、CursorBench 3.2、Artificial Analysis，以及 DeepSWE、Terminal-Bench、SWE-Bench Pro 的原始方法。ChatBench 的分类分数主要是第三方 API 指标的加权代理，因此只作为弱速度/成本先验，不当作独立 Coding Agent 实测。

| 路由 | 默认用途 |
|---|---|
| **Luna medium** | 所有机械与重复任务；自动路由不再低于此档 |
| **Luna high** | 有界普通任务与常规规模信息扫描的默认档 |
| **Luna xhigh** | 大型有界扫描/审查；无需承担 max 的启动与 token 膨胀 |
| **Luna max** | 确实大型、确定性且需要深度推演的任务 |
| **Terra high** | 显式强调低延迟，且更看重较短推理链而非 Luna/high 质量时 |
| **Sol medium** | 有界复杂任务 |
| **Sol high** | 高歧义、高耦合或高后果；仅“需要判断”不够 |
| **Sol xhigh** | 复杂任务已有可归类的推理/验证失败，或用户明确指定 |

Luna 当前每类 Codex token 的 credit 仅为 Sol 的 4%。CursorBench 中 Luna/medium 比 low 高 10.1 分；为了节省已经很低的 credit 而承受明显质量损失，意义不大。Terra/high 的分数高于 Sol/low，ChatBench 响应代理又明显更短，因此只保留为低延迟专家，而不再承担默认中间档。任务证据和用户指定始终优先，完整模型与推理组合仍可显式选择；快照离线运行、有效期 90 天，失效时自动回退。详见[完整测评报告](references/benchmark-evidence.md)和[机器可读快照](references/benchmark-evidence.json)。

原生 Ultra 默认关闭。Router 已自带依赖感知并发，因此不会自动选择 Ultra。只有用户显式开启时，才会将其用于一个有界的 Sol 或 Terra 任务段，并停用 Router 并发，避免两套调度叠加。

按示例混合任务估算，8 档策略相比所有任务固定 Sol/medium，预计可让 **AI 工作周转增效约 10–20%**，Cursor 成本代理约下降 62%。Luna 更高的输出量不算作速度收益，API 成本也不等于 Codex 订阅成本；这些仍需本地账本继续校准。

## 工作方式

- 每次适用请求都重新评估，不继承上一轮的强弱档位。
- 单 Segment 使用快速路径。`begin` 持久化 canonical plan 和身份；此后 `finish`、`restore` 只凭三个 ID 读取状态，不再在上下文压缩后重建计划。
- 并行任务由 `prepare-dispatch` 只持久化一次完整计划，并签发有界票据；执行器只做 ID 级 `attach`，不再重复读取计划、手写并发 envelope 或依赖 shell 标记。
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
- 模型切换消息先显示任务、模型和下一步；内部 ID 与状态只放在续接消息末尾，不再占据首屏。
- 本地 JSONL 账本只记录可验证执行，推荐路由不会被算成真实使用。
- 每个子任务的有界结果都会原子写入同一路由收件箱；最后一个采集任务完成时可直接返回综合阶段 ticket，后续任务只读取自己声明依赖的结果。
- 每个并行任务派发确认和结果收到时，都由协调线程用同一 monotonic clock 自动打点；实际用时、子任务累计、任务重叠、编排空档和峰值并发都由区间推导，模型不能填写时间数字。
- 旧的聚合计时记录继续可读，但退出 verified 历史，不再影响并发统计。
- 仅用任务元数据或用户确认统计路由、排队、启动、切换/恢复、有效执行、往返次数和状态门阻塞；缺失值不猜。
- Apply 简报只覆盖当前运行并原样使用运行时生成的并发行；Query/历史明确标注为历史聚合。只有完整的 schema-v2 逐任务区间才拆分“任务重叠”和“编排空档”；没有受控串行 A/B 时不声称实际提速。

## 使用

```text
$codex-auto-model-router 分析当前仓库并推荐路由
$codex-auto-model-router 动态分段实现这个功能
$codex-auto-model-router 这个任务使用 GPT-5.6 Terra high
$codex-auto-model-router 这个有界实现使用 GPT-5.6 Luna high
$codex-auto-model-router 这个有界重构使用 GPT-5.6 Luna max
$codex-auto-model-router 这个单段任务显式开启 Sol ultra
$codex-auto-model-router 查询使用比例并根据真实结果微调
```

对话框提示示例：

```text
Codex 自动路由｜任务段：分析改动｜模型：GPT-5.6 Sol｜推理：high｜任务歧义较高
Codex 自动路由｜并发计划：4 个任务（含主任务）｜来源：smart-reduced｜调度：关键路径优先
并发：峰值 4（含主任务）｜实际用时：2分0秒｜子任务累计：4分48秒｜任务重叠：2分58秒｜编排空档：10秒
```

完整报告写入 `docs/codex-model-routing-report.md`，可验证使用记录保存在 `.codex/model-routing-history.jsonl`。账本只保存路由元数据和结果，不保存提示词、源码、密钥或对话正文。

## 关于这个项目

这是我的第一个开源项目。它来自一个很实际的困扰：我总在 Sol、Terra、Luna 之间来回切，琢磨一个任务到底要不要上更重的档位。

后来我干脆把这套反复做的判断写成了 Skill。欢迎真实反馈，尤其是选强了、选弱了或拆得不顺的案例；比起一个 Star，这些对我更有帮助。

## 反馈

如果路由过强、过弱、过度拆分或不必要地阻塞，请在不包含私人提示词和源码的前提下[提交一次路由结果](https://github.com/orange-the-weak/codex-auto-model-router/issues/new?template=routing-feedback.yml)。其他问题和建议请使用 [GitHub Issues](https://github.com/orange-the-weak/codex-auto-model-router/issues)。

## 兼容性与开发

本项目需要支持个人 Skill 的 Codex。原生同任务覆盖和自定义 Agent 取决于当前界面。只要任一 GPT-5.6 路由可选，就不会回退或恢复到 GPT-5.5，也不会使用含糊的 `available-default`。如果任务从 5.5 开始并成功进入 5.6，结束后会留在已验证的 5.6 路由。只有 Sol、Terra、Luna 全部不可用时才允许 5.5，并明确记录和提示。

```bash
python3 -m unittest discover -s tests -v
python3 tests/validate_distribution.py
```

参与改进请查看 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题见 [SECURITY.md](SECURITY.md)，许可证见 [LICENSE](LICENSE)。这是独立社区项目，与 OpenAI 无隶属关系，也未获得官方背书。
