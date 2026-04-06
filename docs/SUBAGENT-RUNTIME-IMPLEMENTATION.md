# Subagent Runtime Implementation (XuanWu)

## 1. 目的与范围

本文档记录 XuanWu 子代理运行时（Subagent Runtime）当前已落地实现，覆盖：

- `sessions_spawn` 非阻塞可执行化
- `subagents` 控制面（`list / kill / steer`）
- 子代理生命周期与状态持久化
- API/Channel 请求链路注入与启动期装配
- 当前验证结果与未完成项

本实现目标是提供可运行、可追踪、可恢复的后端基础能力，不包含前端 UI 改造。

## 2. 代码落点

- Runtime 模块
  - `app/xuanwu/subagents/models.py`
  - `app/xuanwu/subagents/runtime.py`
  - `app/xuanwu/subagents/executor.py`
- Tool 接入
  - `app/xuanwu/tools/sessions/spawn_tool.py`
  - `app/xuanwu/tools/sessions/subagents_tool.py`
- 依赖注入与生命周期装配
  - `app/xuanwu/api/deps_context.py`
  - `app/xuanwu/channels/manager.py`
  - `app/xuanwu/main.py`
- 测试
  - `tests/xuanwu/test_subagent_runtime.py`

## 3. 运行时核心设计（已实现）

### 3.1 生命周期状态

`SubagentRunStatus`：

- `pending`
- `running`
- `completed`
- `failed`
- `timed_out`
- `killed`
- `orphaned`

终态由 `is_terminal` 统一判定。

### 3.2 关键数据结构

- `SpawnSubagentRequest`
  - 调度输入（`user_id/session/task/depth/timeout/...`）
- `SubagentExecutionRequest`
  - 运行器实际执行输入
- `SubagentExecutionResult`
  - 执行结果（状态、输出、错误、metadata）
- `SubagentRunRecord`
  - 持久化记录（run id、subagent id、状态、时间戳、上下文统计等）
- `SubagentContextPack`
  - 从父会话注入到子代理的有界上下文

### 3.3 Runtime Manager 能力

`SubagentRuntimeManager` 提供：

- `start/stop`
- `spawn`
- `list_runs_view`（活跃 + 最近）
- `resolve_controlled_target`（`run_id/subagent_id/prefix`）
- `kill_run` / `kill_all_for_controller`（含级联）
- `steer_run`（重启式 steer）

默认策略（构造参数）：

- `max_spawn_depth=1`
- `max_children_per_session=2`
- `max_concurrent_subagents=8`
- `default_timeout_seconds=900`
- `steer_rate_limit_ms=2000`
- `retention_seconds=3600`

## 4. 执行链路

### 4.1 `sessions_spawn` 调用路径

1. `sessions_spawn_tool()` 读取 `deps.extra` 中 runtime/executor。
2. 构建 `SubagentContextPack`（摘要 + transcript tail，带预算上限）。
3. 调用 `runtime.spawn(...)`，立即返回 accepted 响应：
   - `run_id`
   - `subagent_id`
   - `child_session_key`
4. 背景任务异步执行子代理，不阻塞当前对话。

### 4.2 子代理执行回调

`create_subagent_executor(...)` 将子任务桥接到 `AgentRunner.run(...)`：

- 为子代理构建独立 `SkillDeps`（独立 `session_key`）
- 注入父上下文摘要与尾部 transcript
- 聚合 assistant 输出为 `SubagentExecutionResult`
- 失败路径返回 `FAILED` 状态

### 4.3 `subagents` 控制面

- `action=list`
  - 返回 active/recent 列表和计数
- `action=kill`
  - 支持 `all` 或单目标（含 target 解析与级联）
- `action=steer`
  - 对活动 run 做“重启式 steer”
  - 老 run 标记 `killed`（`steer_restart`）
  - 新 run 写入 `replaces_run_id`

## 5. 持久化与恢复

每用户存储路径：

- `workspace/users/<user_id>/sessions/subagent_runs.json`
- `workspace/users/<user_id>/sessions/subagent_runs.log.jsonl`

已实现行为：

- 每次状态变化写 snapshot + 追加 ledger
- 启动恢复时：
  - 读取 snapshot
  - 将 `pending/running` 记录标记为 `orphaned`
- 定时 sweeper 清理超过保留窗口的终态记录

## 6. API/Channel 装配

- `APIContext` 新增 `subagent_runtime` 持有
- `build_scoped_deps()` 注入：
  - `subagent_runtime`
  - `subagent_executor`
  - `subagent_depth`
- `ChannelManager` 新增 `set_subagent_runtime(...)`，在消息流中同样注入上述依赖
- `main.py` 生命周期：
  - 启动时创建并 `start()` runtime
  - 注入 APIContext 与 ChannelManager
  - 关闭时 `stop()` runtime

## 7. 测试与验证

已新增并通过：

- `tests/xuanwu/test_subagent_runtime.py`
  - spawn 完成流
  - kill 状态流
  - steer 重启流
  - tool 与 runtime 集成流

回归验证（本地执行）：

- `pytest tests/xuanwu/test_subagent_runtime.py -q` -> `4 passed`
- `pytest tests/xuanwu/test_workflow.py -q` -> `19 passed`
- `pytest tests/xuanwu/session/test_concurrent_scenarios.py -q` -> `11 passed`
- `pytest tests/xuanwu -q` -> `999 passed, 8 skipped, 1 xfailed`

## 8. 与 design/plan 的对齐结论

当前结论：**核心实现已完成，非阻塞 spawn + 控制面 + 持久化基础已落地**。

未完成项（按 design contract 与后续任务）：

- `workflow/orchestrator.py` 的 detached 路径尚未接入 canonical runtime entry
- persistence hardening（ledger 损坏修复、重试回退与降级标记）尚未补齐
- runtime 策略项尚未全部进入正式 config schema

对应追踪请看：

- `docs/project/tasks/2026-04-05-subagent-runtime-status.md`
- `docs/project/state/KNOWN_GAPS.md`

## 9. 交互闭环缺口（后续任务）

当前 runtime 基础能力已完成，但用户交互闭环仍需补齐：

1. 子代理终态自动回推到当前聊天线程（无需手动 `subagents list`）。
2. 前端实时子代理状态条（accepted/running/completed/failed）。
3. SSE 事件尾包保护，避免 `lifecycle=end` 过早关闭导致遗漏晚到事件。
4. `sessions_spawn` runtime 不可用时用户语义从 placeholder accepted 改为显式错误。
5. 统一消息卡片与附件条双入口一致展示。

该闭环工作在以下任务中跟踪并要求整单闭环交付：

- `docs/project/tasks/2026-04-06-subagent-ux-closure-design.md`
- `docs/project/tasks/2026-04-06-subagent-ux-closure-plan.md`
- `docs/project/tasks/2026-04-06-subagent-ux-closure-status.md`
