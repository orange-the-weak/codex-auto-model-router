# Codex Auto Model Router

[![Validate](https://github.com/orange-the-weak/codex-auto-model-router/actions/workflows/validate.yml/badge.svg)](https://github.com/orange-the-weak/codex-auto-model-router/actions/workflows/validate.yml)

**面向 OpenAI Codex 的轻量 GPT-5.6 模型与推理强度路由器。** 推荐 Sol、Terra 或 Luna，以及 low 到 max 推理；优先通过直接工具并发降低开销，并在模型切换收益明确高于协调成本时自动使用对应模型的叶子智能体。

[English](README.md) · [路由反馈](https://github.com/orange-the-weak/codex-auto-model-router/issues/new?template=routing-feedback.yml) · [问题反馈](https://github.com/orange-the-weak/codex-auto-model-router/issues/new?template=bug-report.yml)

GPT-5.6 给 Codex 带来了很多有用的模型和推理组合，但每次都判断一遍，很快也成了一件麻烦事。我最初只是想让选择自动化，后来又发现：如果 Router 自己挡住了真正的工作，那还不如不用。

所以 v2 默认采用 fail-open 收益门槛路径：快速给出建议，台账不进入关键路径，并在模型切换收益超过启动与汇总成本时自动创建有界子智能体。这也是我的第一个开源项目，欢迎把真实使用中的好坏都告诉我。

**自动选择模型**

```text
当前请求
└─ 只根据这次任务重新评估
   ├─ 机械、普通、扫描或确定性深度任务 → Luna
   ├─ 明确追求低延迟 → Terra
   └─ 复杂、高耦合、高歧义或高后果 → Sol
      ↓
   建议一致或切换不划算 → 主线程直接完成
   建议不同且路由收益超过开销 → 使用对应模型的叶子智能体
```

**低开销并发**

```text
任务
├─ 独立、安全的工具或进程调用 → 在主线程中并发
├─ 依赖推理或存在资源冲突 → 串行执行
└─ 独立推理且路由净收益明确 → 自动进入代理模式
```

## 快速安装

直接告诉 Codex：

> 从 `https://github.com/orange-the-weak/codex-auto-model-router` 安装 `codex-auto-model-router` Skill。

或手动安装：

```bash
git clone https://github.com/orange-the-weak/codex-auto-model-router.git
cd codex-auto-model-router
./install.sh
```

安装后重启 Codex。

## 工作方式

每个适用请求只走三条路径之一：

| 路径 | 行为 |
|---|---|
| Local | 推荐路由，然后由当前主智能体完成工作。 |
| Tool concurrency | 不创建子智能体，并发运行独立安全的工具或进程调用。 |
| Benefit-gated subagents | 路由收益明确超过有界开销时，自动委派、复用或进行多模型推理。 |

默认路径不使用 Restore、计划哈希、游标、环境变量门禁或阻塞式台账。路由或执行器启动失败不会阻塞普通工作。旧的严格状态机只在用户明确要求严格审计或防重放时启用。

所有可见路由提示都会跟随当前请求的语言：英文请求使用英文标签，中文请求使用中文标签；模型、推理强度和原因值保持不变。

Skill 加载时，本轮主对话的模型和推理强度已经确定，因此 Router 不能主动切换它们。`recommended_route` 在实际委派前只是建议；委派后由独立叶子任务运行建议模型，并不改变已经开始的主对话。用户在 UI 选模或修改配置通常只影响后续任务或请求。直接工具并发仍共享当前主模型和推理强度，不会产生独立推理流或子智能体卡片。

适合直接并发的工作包括独立文件读取、搜索、元数据查询，以及不共享构建状态的测试。依赖前一步语义判断、重叠写入、Git 修改、部署、审批，以及共享模拟器、设备或构建资源的动作必须串行。

当路由适配、质量、延迟或资源收益明确超过有界启动与汇总开销时，子智能体模式会自动启用，不需要额外询问用户许可；用户可用 `--no-subagents` 明确禁用。委派仍保留有界生命周期规则：`completed` 是正常终态，子任务 `task_complete` 覆盖父侧陈旧的 `running`，单次等待超时本身不等于停滞，复用也不会跨用户请求。

主线程发送最终回复前，只要本轮使用过子智能体，就会停止新调度、禁用复用、清空当前请求的复用登记、刷新当前任务树、中断所有仍真实 `running` 但已非必需的子智能体，并再次刷新。只有当前请求拥有的全部子智能体都进入终态后才结束。这个流程能结束当前任务的子智能体，但 Codex 协作接口没有删除已完成子智能体 UI 历史的操作；历史卡片可能继续显示，Skill 不会声称已经清除。

CLI 默认启用收益门槛委派；`--no-subagents` 是明确退出开关。旧的 `--allow-subagents` 仍为调用方兼容而接受，但不再代表授权，也不是必需参数。执行器预设只在收益门槛通过后自动选择，绝不预热或预建等待队列。

## v0.2 更新重点

- 默认路径会在模型切换收益明确超过有界开销时自动使用对应模型的叶子智能体。
- 独立安全的工具和进程可以并发执行，不复制模型上下文，也不新增子智能体 UI 条目。
- `--no-subagents` 可明确禁用委派、复用和代理并发；其他情况下无需额外询问许可。
- 推荐路由与本轮实际使用的模型被明确分开，不再声称 Skill 已切换主对话模型。
- Ultra 仍需用户显式开启；只要 Sol、Terra 或 Luna 任一可用，就不回退 GPT-5.5。

## 模型梯度

| 任务 | 默认路由 |
|---|---|
| 确定性机械任务 | Luna / medium |
| 普通有界任务 | Luna / high |
| 大型有界扫描或审查 | Luna / xhigh |
| 大型确定性深度任务 | Luna / max |
| 明确追求低延迟 | Terra / high |
| 有界复杂任务 | Sol / medium |
| 高歧义、高耦合或高后果 | Sol / high |
| 复杂推理或验证已有失败 | Sol / xhigh |

Ultra 永不自动启用。用户显式使用 Ultra 时，由其原生编排接管，并关闭 Router 并发。只有整个 GPT-5.6 家族都确认不可用时才回退 GPT-5.5。

## 测评与台账

路由策略离线参考 OpenAI、Artificial Analysis、CursorBench、ChatBench、DeepSWE、SWE-Bench Pro 与 Terminal-Bench 的公开编码测评。任务本身的证据和用户指定始终优先；API effort 数据只作为相对能力、延迟和输出量先验，不代表 Codex 订阅成本或真实耗时。

完整数据见[测评证据](references/benchmark-evidence.md)和[机器可读快照](references/benchmark-evidence.json)。快照缺失、损坏或过期时，Router 直接使用确定性规则，不阻塞任务。

只有观察到的真实执行才会写入台账，推荐路由绝不记作实际模型使用。收益门槛子智能体模式会返回机器可读的启动契约：执行器类型必须搭配 `fork_turns="none"`；契约不匹配时不重试，直接由主任务接管。台账失败不会影响项目交付。

## 开发

```bash
python3 -m unittest discover -s tests
python3 tests/validate_distribution.py
```

隐私安全的反馈与贡献方式见 [CONTRIBUTING.md](CONTRIBUTING.md)。
