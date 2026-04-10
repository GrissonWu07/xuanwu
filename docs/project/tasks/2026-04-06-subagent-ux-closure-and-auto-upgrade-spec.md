# XuanWu Subagent 闭环与自动升级 Spec

## 1. 背景与目标

本 spec 汇总本轮会话中从“实现审查”到“自动升级策略”达成的一致结论，目标是：

1. 保持 XuanWu 的 Chat-first 产品形态，不转向 deep research 工作台。
2. 补齐 Subagent 端到端用户交互闭环，避免“已受理但不可见/不可追溯”。
3. 完成此前已确认的 3 个未完成基础项。
4. 设计默认单 Agent、按需自动升级 Subagent 的机制，并明确 LLM 与平台职责边界。
5. 形成“任务必须闭环完成，不得半成品交付”的执行标准。

## 2. 本轮审查结论（问题清单）

### 2.1 已实现但不完整的部分

- `sessions_spawn` 已支持非阻塞 accepted。
- `subagents list/kill/steer` 已可运行。
- 子任务状态有持久化与恢复基础。

### 2.2 用户交互闭环缺口（需补齐）

1. 子任务终态未自动回推到当前聊天线程（用户需手动查）。
2. 前端没有独立实时 Subagent 状态区。
3. 流尾事件保护不足，生命周期结束附近可能漏掉晚到事件。
4. `runtime unavailable` 场景使用 placeholder accepted 语义，不应对用户显示为“成功”。
5. 结果展示缺少稳定“双入口一致性”（消息卡片 + 附件条同时可访问）。

### 2.3 之前确认未完成的 3 个基础项

1. Orchestrator detached 路径尚未统一走 canonical runtime。
2. Persistence hardening 未完成（ledger 尾损坏修复、重试回退、降级标记）。
3. Runtime 策略项尚未全部进入正式 config schema。

## 3. 产品方向共识

1. Subagent 不是 deep research 专属能力，而是“后台可控执行能力”。
2. 默认仍是单 Agent。
3. 只有在任务满足特征时才升级为 Subagent。
4. 用户必须能看到升级发生、执行进展、终态结果和产物链接。

## 4. 交互设计需求（给设计与前端实现）

## 4.1 页面结构（保持 chat-first）

- 主体仍是聊天时间线。
- 输入框下固定两条“克制”区域：
  1. 附件条（Attachments / Outputs）
  2. Subagents 条（活跃与最近子任务）

## 4.2 结果展示双入口

子任务产物必须同时存在于：

1. 消息时间线中的完成卡片（可点击链接）。
2. 底部附件条 Outputs（可再次访问）。

## 4.3 Subagents 条最小功能

- 展示：`subagent_id`、状态、耗时、更新时间。
- 操作：`Steer`、`Kill`、`Open Result`。
- 支持并发多个子任务显示。

## 4.4 终态自动回推

子任务到达终态（completed/failed/killed/timed_out）时，系统自动写回一条会话消息，包含：

- 子任务标识
- 终态
- 摘要或错误
- 产物链接（若有）

## 4.5 Chat-first 单活跃批次约束（新增）

同一 thread 在任一时刻只允许 1 个活跃 SA batch（含 queued/running）。

1. 若当前 batch 未结束，新一轮请求默认不创建新 SA。
2. 后端必须做原子锁裁决（不能只靠前端禁用）。
3. 冲突时必须返回明确语义：
   - `continue_current_batch`
   - `queued_next_request`
   - `rejected_queue_full`

## 4.6 触发透明度与一键回退（新增）

当系统判定进入 SA 模式时，必须在聊天流出现透明说明：

1. 本轮进入 SA 的原因（例如并行性/长耗时/产物要求）。
2. 当前计划的 SA 数量与分工摘要。
3. 一键改为单 Agent 执行（本轮 override）。

## 4.7 排队策略（新增）

默认策略：

1. 每个 thread 最多允许 1 条待执行 SA 请求（可配置）。
2. 超限返回 `rejected_queue_full`，并提示用户：
   - 继续等待当前 batch
   - 取消当前 batch 并替换
   - 保持单 Agent 执行

## 4.8 中断语义（新增）

区分两类中断：

1. `kill_run(run_id)`：仅停止指定 run。
2. `kill_batch(batch_id)`：停止该 batch 全部活跃 run。

中断后已产出 artifact 默认保留并可下载，状态标记为 `partial`。

## 4.9 多轮输入路由一致性（新增）

当存在活跃 SA batch 时：

1. 用户新消息默认由主 Agent 即时回复。
2. 不自动创建新 SA（除非用户显式替换当前 batch）。
3. 前端在消息上方显示当前 batch 进度摘要，避免用户误解“消息被吞”。

## 4.10 完成回执与失败恢复（新增）

batch 结束时系统必须自动发送统一回执消息，包含：

1. 完成数 / 失败数 / 取消数
2. 产物数量与链接
3. 下一步建议

失败 run 必须支持：

1. `retry_same_context`
2. `retry_with_edit`（允许编辑任务后重试）

## 4.11 流式噪音控制与断线恢复（新增）

1. 进度更新需节流与去重（建议 300-500ms 合并刷新）。
2. 同一 run 仅更新一条消息卡，不重复刷新多条。
3. 页面刷新/重连后，前端先拉取 batch 快照，再订阅增量事件。
4. 事件消费需 cursor 化，防止丢包与重复渲染。

## 4.12 并发与权限边界（新增）

1. 后端使用原子锁 + 幂等键防止双击/重连重复 spawn。
2. `steer/kill/retry` 权限按 thread owner/workspace role 判定。
3. 未授权操作返回明确权限错误，不可静默失败。

## 4.13 超时与卡住处理（新增）

1. 长时间无进度时标记 `stalled` 并提示“可能卡住”。
2. 提供两种用户动作：
   - 继续等待
   - 中断并总结已完成部分
3. 若触发超时，系统仍需产出部分结果回执与可用 artifact。

## 5. 自动升级机制（默认单 Agent）

## 5.1 总体策略

- 默认：单 Agent。
- 自动升级：由 LLM 进行任务形态判断 + 编排建议，平台 runtime 最终裁决。
- 不采用关键词硬编码判断。

## 5.2 LLM 判定器输入

- 当前用户请求
- 最近会话上下文
- 可用工具/能力清单
- 当前运行约束（并发上限、深度、策略）

## 5.3 LLM 判定器输出（必须结构化）

LLM 输出不止“是否升级”，还必须给“如何拆分执行”：

```json
{
  "should_upgrade": true,
  "confidence": 0.86,
  "execution_mode": "parallel",
  "branch_count": 3,
  "estimated_steps": 7,
  "estimated_seconds": 45,
  "subtasks": [
    {
      "id": "s1",
      "goal": "子任务目标",
      "deliverable": "产出说明",
      "required_tools": ["provider:xxx"],
      "timeout_seconds": 120
    }
  ],
  "merge_strategy": "s3_as_final",
  "reasons": ["parallelizable", "long_running", "artifact_expected"]
}
```

## 5.4 平台 runtime 最终裁决（非 LLM）

runtime 负责：

1. 准入控制（并发、深度、权限、安全策略）。
2. 计划合法性校验（工具可用、依赖闭环）。
3. 必要裁剪（branch 数、超时）。
4. 不合法计划回退单 Agent。
5. 记录执行图，支撑 kill/steer/retry。

结论：LLM 负责“建议与编排”，平台负责“是否执行与如何安全执行”。

## 5.5 判定模型来源

- 默认：使用当前 token pool 内模型（沿用现有 gate 机制）。
- 可选：配置独立 `subagent_classifier_model`。
- 未配置时回退到当前可用主模型/分类模型策略。

## 6. 技术改造范围

## 6.1 后端

1. 增加 Subagent 专用事件通道（如 `subagent_status`）并接入 SSE。
2. 终态写回消息到主会话 transcript。
3. 修正 runtime unavailable 的用户语义（显式错误）。
4. 完成 orchestrator detached 统一接入 canonical runtime。
5. 完成 persistence hardening。
6. 完成 runtime 策略 config schema 化。
7. 增加 thread 级 `active_sa_batch` 原子锁与排队控制。
8. 增加 SA batch 结束统一回执生成。
9. 增加 `retry_same_context` / `retry_with_edit` 接口。
10. 增加 `stalled` 检测与超时总结路径。
11. 增加 `steer/kill/retry` RBAC 校验。

## 6.2 前端

1. 新增固定 Subagents 条并订阅实时状态事件。
2. 渲染终态自动消息卡片。
3. 保证产物在消息与附件条双入口一致可访问。
4. 增加多任务并发态、失败态、重连态体验。
5. 增加“进入 SA 原因 + 一键单 Agent”透明提示。
6. 增加活跃 batch 存在时的冲突语义提示（继续/排队/拒绝）。
7. 增加 `stalled` 态提示与操作按钮（继续等待/中断总结）。

## 7. 任务闭环规则（强约束）

本任务执行采用强闭环标准：

1. 所有 in-scope 项全部完成后才可标记 Complete。
2. 不允许“先交核心、其余后续补”的半成品结束语义。
3. 若阻塞，必须标记 Blocked 并写明：
   - blocker 原因
   - owner
   - unblock 条件
   - 预计时间
4. 文档、测试、实现三者必须同步闭环。

## 8. 验收标准

## 8.1 用户体验验收

1. 发起 `sessions_spawn` 后立即可见 accepted 状态。
2. 运行中状态实时更新，无需手动 `subagents list`。
3. 子任务终态自动回推聊天消息。
4. 产物链接在消息与附件条均可点击。
5. 刷新后仍能在会话内追溯终态与产物。
6. 进入 SA 时用户可见触发原因，并可一键切回单 Agent。
7. 活跃 batch 存在时，新 SA 请求反馈语义明确（继续/排队/拒绝）。
8. SA 运行中发送新消息，主 Agent 仍可稳定响应且不自动再开 SA。
9. batch 结束后自动出现统一回执（统计 + 产物 + 下一步）。
10. run 失败后可直接重试（同上下文与可编辑重试）。
11. 卡住/超时时有明确提示与可执行动作。

## 8.2 技术验收

1. 3 个历史未完成项全部完成。
2. 自动升级策略可通过配置开关与阈值控制。
3. LLM 判定失败/低置信度时可安全回退单 Agent。
4. 无事件尾包丢失。
5. thread 级 SA 并发锁与排队策略生效。
6. spawn 幂等防重入生效（双击/重连无重复创建）。
7. 权限边界可验证（owner/协作者/只读角色）。

## 8.3 测试验收

至少覆盖：

1. Unit：判定器解析、runtime 裁决、持久化恢复。
2. Integration：accepted -> running -> terminal 全链路事件。
3. E2E：主会话自动收到子任务终态与产物链接。
4. 回归：`pytest tests/xuanwu -q` 与前端相关测试。
5. E2E：活跃 batch 时新 SA 请求的 continue/queue/reject 三分支。
6. E2E：SA 运行中主 Agent 多轮输入稳定响应。
7. E2E：失败重试、卡住提示、超时总结。
8. E2E：权限不足时 `steer/kill/retry` 被拒绝并前端提示。

## 9. 关联文档

- `docs/project/tasks/2026-04-05-subagent-runtime-status.md`
- `docs/project/tasks/2026-04-06-subagent-ux-closure-design.md`
- `docs/project/tasks/2026-04-06-subagent-ux-closure-plan.md`
- `docs/project/tasks/2026-04-06-subagent-ux-closure-status.md`
- `docs/SUBAGENT-RUNTIME-IMPLEMENTATION.md`
- `docs/project/WORKFLOW.md`
