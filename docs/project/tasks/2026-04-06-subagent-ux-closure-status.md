# Subagent UX Closure Status

## Goal

Close the end-to-end user interaction loop for subagent runtime and finish all
previously unresolved runtime foundation items in one complete delivery.

## Current Status

- Phase: `Implementation In Progress`
- Completion policy: `All plan items required`
- Partial delivery: `Not allowed`

## Scope Checklist

| Area | Item | Status |
|---|---|---|
| UX loop | realtime subagent status visibility | Done (`subagent_status` SSE + cursor resume) |
| UX loop | automatic terminal message write-back | Done (run + batch terminal receipts auto-appended) |
| UX loop | dual-surface artifact links | Pending |
| UX loop | stream tail flush (no dropped late events) | Pending |
| UX loop | SA 触发透明度 + 一键单 Agent 回退 | Pending |
| UX loop | 活跃 batch 冲突语义（继续/排队/拒绝） | In Progress (后端裁决 + tool status) |
| UX loop | SA 运行中多轮输入默认主 Agent 路由 | Pending |
| UX loop | batch 结束统一回执（统计/产物/建议） | Done (batch transcript now includes artifact links + next-step) |
| UX loop | 失败重试（同上下文/可编辑重试） | Done (frontend now supports `Retry` + `Retry + Edit`) |
| UX loop | 进度节流去重（防刷屏） | Pending |
| UX loop | 断线恢复（快照 + 游标增量） | Pending |
| Runtime backlog | thread 单活跃 SA batch 原子锁 | Done |
| Runtime backlog | 幂等键防重复 spawn | Done |
| Runtime backlog | steer/kill/retry 权限边界 | Pending |
| Runtime backlog | stalled 检测与超时部分总结 | In Progress (stalled 判定 + partial 标记) |
| Runtime backlog | orchestrator detached path canonical runtime routing | Pending |
| Runtime backlog | persistence hardening (ledger tail + retry/backoff/degraded) | Pending |
| Runtime backlog | config schema promotion for runtime knobs | Done |
| Validation | unit/integration/E2E verification | In Progress |
| Documentation | state/task/workflow closure write-back | In Progress |

## Design and Plan References

- `docs/project/tasks/2026-04-06-subagent-ux-closure-design.md`
- `docs/project/tasks/2026-04-06-subagent-ux-closure-plan.md`
- `docs/images/mockups/2026-04-06-subagent-ux-closure.svg`

## Documentation Updates Done In This Step

- Added visual mockup for frontend closure design.
- Added new design/plan/status task set for closure delivery.
- Added process-level no-half-delivery rules to workflow and template docs.
- Added runtime implementation doc note for interaction closure gaps.

## Verification Evidence (This Iteration)

- Backend targeted:
  - `pytest tests/xuanwu/test_subagent_runtime.py -q` -> `8 passed`
  - `pytest tests/xuanwu/test_session_api_routes.py -q` -> `21 passed`
  - `pytest tests/xuanwu/session/test_concurrent_scenarios.py::TestSubAgentResourceCleanup::test_subagent_session_creation -q` -> `1 passed`
- Backend full:
  - `pytest tests/xuanwu -q` -> `1006 passed, 8 skipped, 1 xfailed`
- Frontend targeted:
  - `npm test -- tests/frontend/api-client.test.js tests/frontend/chat-page.test.js` -> `24 passed`
- Frontend full:
  - `npm test` currently fails in pre-existing suites (`auth.test.js`, `session-manager.test.js`) with legacy-storage expectations unrelated to subagent closure slice.

## Remaining

- Execute remaining plan items in workstreams 1-5 and keep updating this file with evidence.

## Next Step

Start implementation from Workstream 1 (backend event + write-back closure),
then proceed in plan order until all items are done.
