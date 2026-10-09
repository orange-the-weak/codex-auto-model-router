# Codex Auto Model Router

[![Validate](https://github.com/orange-the-weak/codex-auto-model-router/actions/workflows/validate.yml/badge.svg)](https://github.com/orange-the-weak/codex-auto-model-router/actions/workflows/validate.yml)

**面向 OpenAI Codex 的轻量 Astra/Sol/Luna 模型与推理强度路由器。** 推荐 Astra、Sol 或 Luna（保留 GPT-5.6 兼容），以及 low 到 max 推理；优先通过直接工具并发降低开销，并在模型切换收益明确高于协调成本时自动使用对应模型的叶子智能体。

[English](README.md) · [路由反馈](https://github.com/orange-the-weak/codex-auto-model-router/issues/new?template=routing-feedback.yml) · [问题反馈](https://github.com/orange-the-weak/codex-auto-model-router/issues/new?template=bug-report.yml)

GPT-5.6 给 Codex 带来了很多有用的模型和推理组合，但每次都判断一遍，很快也成了一件麻烦事。我最初只是想让选择自动化，后来又发现：如果 Router 自己挡住了真正的工作，那还不如不用。

所以 v2 默认采用 fail-open 收益门槛路径：快速给出建议，台账不进入关键路径，并在模型切换收益超过启动与汇总成本时自动创建有界子智能体。这也是我的第一个开源项目，欢迎把真实使用中的好坏都告诉我。

**自动选择模型**

```text
当前请求
└─ 只根据这次任务重新评估
   ├─ 机械、普通、扫描或确定性深度任务 → Luna
   ├─ 明确追求低延迟 → Terra
   └─ 有界复杂任务 → Sol；高歧义、高后果任务 → Astra
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

安装后重启 Codex。若还要安装全局提示钩子，请使用 `./install.sh --install-hook`（PowerShell：`./install.ps1 -InstallHook`）。该钩子会提示 Codex 在适用时使用此 Skill，但不会更改当前对话的模型。使用 `/hooks` 审核、信任或停用钩子，然后重启 Codex。

## 路由配置档

`balanced` 保留默认路由；`economy` 让更多有界任务使用 Luna；`quality` 让普通任务和扫描优先使用 Sol。这三个现有配置中，Astra 默认 low，推理或验证失败后可升至 medium；更高强度必须显式指定，包括用户配置的任务档位覆盖。

可选的 `plus` 和 `pro` 必须由用户显式选择。它们是路由偏好，不检测订阅，也不强制设置服务层级。安装保留已有选择和默认行为。保存的选择持续有效，直到用户明确切换；`--profile` 只覆盖本次调用。账号信息、订阅权益和可用模型都不会自动选择配置。

- Plus：轻量机械任务用 GPT-6 Luna/high，默认 Luna/xhigh，有界复杂任务用 GPT-6.1 Sol/high，更深任务用 Sol/xhigh。不会自动选择或回退到 Astra，但保留显式覆盖。
- Pro：沿用两个 Luna 档；复杂的严格限定实现、既有项目迭代、UI 或谨慎维护用 GPT-5.6 Sol/xhigh；大型仓库、自主调查、复杂规划或深入跨模块任务用 GPT-6.1 Sol/xhigh。只有对应 Sol/xhigh 分支发生实质性失败，或任务确属极难／高后果，才允许 GPT-6 Astra/xhigh。不会经过 Astra medium/high 中间档。选择 Pro 意味着明确允许最高档可能显著增加预算消耗。

```bash
python3 scripts/router_lite.py profile-show --repository .
python3 scripts/router_lite.py profile-set quality --scope project --repository .
python3 scripts/router_lite.py decide --profile economy --repository .
python3 scripts/router_lite.py profile-set plus --scope project --repository .
python3 scripts/router_lite.py decide --profile pro --task-kind complex --task-subtype ui --repository .
```

Pro 按失败升级时，需使用 `--prior-failure --prior-failure-kind reasoning`（或 `verification`），并提供实际观测到的 `--prior-failure-model` 和 `--prior-failure-effort xhigh`。模型或强度证据缺失、不匹配，Luna 失败以及基础设施失败，都不能触发 Astra。普通的有界实现仍从 Luna 开始；一般复杂度或歧义也必须先走 Sol。自动生成或缓存报告中的建议会按所选配置重新分类；用户明确指定的模型和强度仍优先。任务子类型、全局设置、TOML 档位覆盖和优先级见[路由配置说明](references/routing-profiles.md)。配置档和可选提示钩子改编自 [David Soff](https://github.com/Davidsoff) 的 PR #4 与 #6。

## 退出当前项目

直接告诉 Codex“当前项目不再使用这个 Skill”，或运行：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/codex-auto-model-router/scripts/router_lite.py" project-disable --repository .
```

该命令会保留其他设置，只在当前项目的 `.codex/config.toml` 中加入一条受管理的 `[[skills.config]]` 禁用项。Router 命令会立即停止；随后重启 Codex，可信项目就能在后续任务中阻止该 Skill 正常加载。它只影响当前项目，不修改全局 `~/.codex/config.toml`。

恢复或查看状态：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/codex-auto-model-router/scripts/router_lite.py" project-enable --repository .
python3 "${CODEX_HOME:-$HOME/.codex}/skills/codex-auto-model-router/scripts/router_lite.py" project-status --repository .
```

`--no-subagents` 含义不同：它只针对一次 Router 命令禁用子智能体，不会退出整个 Skill。项目配置遵循 Codex 官方的 [`config.toml` 机制](https://developers.openai.com/codex/config-reference/)。

## 工作方式

每个适用请求只走三条路径之一：

| 路径 | 行为 |
|---|---|
| Local | 推荐路由，然后由当前主智能体完成工作。 |
| Tool concurrency | 不创建子智能体，并发运行独立安全的工具或进程调用。 |
| Benefit-gated subagents | 路由收益明确超过有界开销时，自动委派、复用或进行多模型推理。 |

默认路径不使用 Restore、计划哈希、游标、环境变量门禁或阻塞式台账。路由或执行器启动失败不会阻塞普通工作。旧的严格状态机只在用户明确要求严格审计或防重放时启用。

所有可见路由提示都会跟随当前请求的语言：英文请求使用英文标签，中文请求使用中文标签；模型、推理强度和原因值保持不变。

当建议路由不同但仍由主线程执行时，提示会简洁说明主对话模型已固定、子智能体启动成本高于预期收益。实际委派时则写出切换原因，避免把推荐模型误认为已经执行的模型。Skill 内只保存英文规范模板，运行时再按用户当前语言自然翻译。

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
- 显式指定的模型不会静默替换；自动 Astra 降级必须说明。旧严格模式保留 GPT-5.6 家族回退限制。

## 模型梯度

| 任务 | 默认路由 |
|---|---|
| 确定性机械任务 | Luna / medium |
| 普通有界任务 | Luna / high |
| 大型有界扫描或审查 | Luna / xhigh |
| 大型确定性深度任务 | Luna / max |
| 明确追求低延迟 | Terra / high |
| 有界复杂任务 | Sol / medium |
| 高歧义、高耦合或高后果 | Astra / low |
| 复杂推理或验证已有失败 | Astra / medium |

现有默认配置中，Astra 默认 low，自动升级最多 medium；high、xhigh、max 仅在用户显式指定强度或配置档位覆盖时使用。上文明确选择 Pro 后的最高档是唯一内置例外。只指定 Astra 不代表允许更高强度。Plus/Pro 的可用性回退不会把非 Astra 建议提升为 Astra。

当前默认使用 GPT-6 Luna、GPT-6.1 Sol 与 GPT-6 Astra，兼容 GPT-6 Sol 和显式 GPT-5.6 路由；Terra/high 保留为旧版低延迟路线。Ultra 与 GPT-5.5 回退仅属于旧兼容模式。可显式请求“更新模型目录”；只读检查发现新模型时提示审核，不自动改路由、不创建后台定时任务。详见[模型更新说明](references/model-updates.md)。

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
