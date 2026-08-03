# Project Agent Rules

## Model routing

- 所有代码修改、测试、代码审查、重构、调试和验证任务，自动调用 `$codex-auto-model-router` 的 Apply 路径。
- Apply 默认使用 `apply-fast-v1` 单段快速路径；只有真实顺序边界才使用 `segmented-v1`，存在两个以上独立且值得并行的边界时才使用 `dependency-parallel-v1`。不得为了凑并发机械拆分，也不先插入独立 Assess 回合。
- 并行计划自动上限为 4 个并行任务；实际数量按独立宽度和已观测空闲槽位减少。总槽位必须扣除主协调线程和已运行的执行任务；因此总槽位为 4 时，通常表现为主线程 1 + 并行任务峰值 3。文档默认 `max_threads` 不是实时容量。容量未知时先派发一个、确认空闲后再补位；用户请求超过 4 必须有足够的已观测空闲槽位和独立 ready 任务。
- 并行调度由主线程独占 frontier。完整计划只交给 `router_runtime.py prepare-dispatch` 一次；它按关键路径和实时容量签发有界 `dispatch-ticket-v1` 批次。worker 只凭 ID/hash `attach`，不重建计划或手写并发 envelope。仅创建当前票据覆盖的任务，结果返回后 wait-any 补位；worker 不得继续委派。
- 完整对话和未来计划只保留在主线程；worker 只接收当前目标、必要决策、范围/冲突键、验收、验证预算、禁止事项和不可变 ID/hash，不复制完整历史。
- 写任务必须声明不相交的 `write_scopes`；Git index、lockfile、工程文件、migration、部署目标、共享模拟器等共享可变资源必须声明 `conflict_keys`。冲突任务自动加依赖退化串行；无法证明隔离时改为只读或串行。
- 并行失败采用 `stop-dispatch-drain-running`：首次失败后停止分发新任务，等待已运行 worker 返回，保留可验证结果，跳过未开始和依赖失败的任务，再按计划顺序汇总。
- 报告覆盖当前请求时，将匹配路由作为对应 Segment 的输入；多 Segment 不得把一条全局报告路由套用到所有阶段。报告缺失、过期或未覆盖时，使用确定性默认路由，不阻塞实际工作。
- 每次适用的 Apply 请求都根据当前任务重新选择路由，不得继承上一请求的强弱档位。当前模型只用于选择后的 `local` 或切换。同路由不再自动吞并任务边界；只有显式同一 `merge_group`、路由来源和完整任务证据都一致时才合并。
- 路由必须优先使用当前任务的歧义、耦合、验证方式、后果、延迟优先级和既往失败证据；`references/benchmark-evidence.json` 只是带版本和有效期的离线先验。缺失、损坏或过期时回退确定性规则，Apply 运行时不得联网刷新。
- 自动路由固定为 8 档：Luna/medium 处理机械任务；Luna/high 处理普通有界任务和常规扫描；大型有界扫描/审查用 Luna/xhigh；只有大型、低后果、确定性深度任务才用 Luna/max；Terra/high 仅作显式低延迟专家；有界复杂任务 Sol/medium；高歧义、高耦合或高后果才用 Sol/high，`judgment` 单信号不升档；Sol/xhigh 仅用于已归类的复杂推理/验证失败或用户明确指定。环境/未知失败不得升级。默认禁止 Ultra。
- 默认预算为 4 个 Segment、4 次模型切换（包含最终恢复）；只有计划确实超过 4/4 且存在 `complex` 或 `large` 依据时自动扩到 6/6。用户可显式指定 1–8；8/8 是不可突破的硬上限。预算写入不可变计划，Segment 失败立即停止，不得循环换模型或执行中扩容。
- 仅使用 `CODEX_THREAD_ID` 和对应 session 元数据识别当前任务及原模型；原模型或推理强度不可验证时，不执行会污染后续回合的同任务持久切换。
- 每个 Segment 开始前在当前 Codex 对话框显示一次由 Codex 自动选择的模型、推理强度和原因；可见格式使用 `任务段：<名称>`，不显示 `x/y`，索引和总数只保留在内部计划与账本。段内命令与文件操作不重复提示。优先使用 Codex 原生同任务模型覆盖，按段顺序续接，不创建新的顶层任务。
- 所有同任务模型切换、下一 Segment 和 Restore 续接消息都视为用户可见：必须先写“继续当前任务”或“任务已完成，正在恢复原模型”的可读说明，再把 `ROUTE_PROJECT_MODELS_*`、ID、hash、路径和 envelope 放入末尾的 `CODEX_ROUTER_INTERNAL` Markdown 注释。禁止让机器字段出现在消息首屏；若当前界面会在模型输入前移除注释，则改用末尾的“内部路由上下文”代码块。
- 每次选择并行度时额外显示一条简短提示：`并发计划：N 个任务（含主任务）`，并附 `parallelism_source` 和调度方式；不在对话框展开总槽位/子任务分式。并行任务仍逐段显示各自模型与推理强度。
- 并行 Segment 必须使用基于任务内容的稳定 `segment_id`；创建子智能体时，将其规范化为符合 Codex `[a-z0-9_]+` 规则的 `agent_task_name`。禁止 Router 生成随机名、`worker_1` 或纯序号名；客户端附加的系统昵称不视为任务名。
- 如果所选 GPT-5.6 模型不可用，必须先按确定性顺序尝试其他 5.6 模型和显式 5.6 Agent；只要 Sol、Terra、Luna 任一可用，就禁止回退 GPT-5.5、`available-default` 或当前的非 5.6 模型。只有能力界面明确不提供任何 5.6，或三种 5.6 均在执行前被拒绝为不可用时，才允许 GPT-5.5，并记录与提示 `gpt56-family-unavailable`。
- 如果调用 Skill 前的原模型是 GPT-5.5 或其他非 5.6 模型，而本次 Segment 已验证运行在 GPT-5.6，结束时不得恢复非 5.6 原模型；保持当前 5.6 路由返回，避免完成后自动切回 5.5。
- 所有 Segment 共用一个不可变 `route_id` 和 `plan_hash`，每段使用唯一 `segment_id` 与确定性 `attempt_id`；执行开始后不得递归规划、改变顺序或重复推进零基游标。最后一段完成或任一段失败后，若尚未回到调用前路由，只恢复一次原模型与推理强度。
- 简单问答、文案确认、解释说明和只读查询不走 Apply 路径，也不启动模型路由，以避免额外延迟。
- 只读查询模型使用比例或记录已完成任务时，使用 `codex-auto-model-router` 的 Query/Record 快速路径。
- 串行使用 `router_runtime.py begin/finish/restore`。并行使用 `prepare-dispatch → spawn → worker-start`，worker 先 `attach` 再执行；ambient `ROUTE_PROJECT_MODELS_EXECUTOR` 只兼容旧提示，不得当作 shell 授权条件。`finish` 与 `restore` 只凭 ID 读取状态，不重建 plan/hash。首次失败后，仅已记录 `worker-start` 的任务可排空，只有 reservation 的票据不得再启动。
- `begin` 必须在任何项目工具或编辑前验证实际模型/推理强度与目标或已验证 fallback 一致；未知或不一致时停止并转显式选模执行器/切换。GPT-5.5 必须提供与 route/plan/segment/attempt 绑定的结构化能力决策，仅写回退原因不足以放行。
- 默认只在本地修改和验证，不自动执行 `git commit` 或 `git push`；只有用户明确要求提交、推送或发布到 GitHub 时才执行。

## Verification

- 遵守本仓库已有的验证说明；验证范围与任务风险相称。
- 每个 Apply 任务完成后，报告修改文件、执行的检查和剩余风险；项目本地路由账本不可写时不阻塞主任务。
- `finish` 与 `restore` 必须幂等；项目账本或运行时状态在项目工作完成后不可写时，转隔离临时状态或输出一次非阻塞警告。身份不匹配仍明确拒绝，不得用重建整份 plan 代替身份校验。
- 并行实际用时、子任务累计、任务重叠、编排空档、峰值并发和模型×并发比例只记录任务元数据或用户确认的真实值；事件写入时间不能冒充并行任务开始时间。
- 每个并行任务派发确认后立即调用 `router_runtime.py worker-start`，结果收到后立即调用 `worker-finish`；两者必须携带同一 `route_id + plan_hash + segment_id + attempt_id`，由协调线程自动读取 monotonic clock，不接受模型提供时间。未派发的 prepared claim 可受控恢复；dispatch-confirmed 后禁止重放。
- 每个并行结果都立即调用 `router_runtime.py finish`，将有界 `handoff` 原子写入路由结果收件箱；最后一个依赖完成时优先直接派发返回的 continuation ticket。终态从逐任务区间自动计算实际用时、子任务累计、任务重叠、编排空档与峰值并发并幂等落账；缺少或无效区间时保持 `pending`，不得手工补算。
- Apply 简报必须原样使用运行时返回的 `parallel_execution_brief`，不得再次计算、四舍五入或改写格式。
- 路由、排队、executor 启动、模型切换、Restore、有效执行、模型/工具往返和状态门停止只接受任务元数据或用户确认；缺失数据不得估算补齐。
- 每次 Apply 简报用一行说明并发效果：串行说明未启用原因；未计时说明待记录；有可靠数据时报告峰值、实际用时、子任务累计、任务重叠和编排空档。时长取整到秒；没有受控串行 A/B 时不得声称实际提速。
- 项目账本必须通过最近 Git 根目录解析；Apply 只显示当前 `route_id`，Query 才显示明确标注的历史聚合。
