# Subagent Runtime Status

## Goal

Implement a production-usable, executable subagent runtime for XuanWu that keeps
existing tool contracts (`sessions_spawn`, `subagents`) and aligns with:

- `docs/project/tasks/2026-04-05-subagent-runtime-design.md`
- `docs/project/tasks/2026-04-05-subagent-runtime-plan.md`

## Spec and Plan Alignment

| Requirement | Source | Status | Evidence |
|---|---|---|---|
| Runtime package with lifecycle models and manager | Plan Phase 1 | Done | `app/xuanwu/subagents/models.py`, `app/xuanwu/subagents/runtime.py`, `app/xuanwu/subagents/executor.py` |
| `sessions_spawn` non-blocking accepted flow | Design + Plan Phase 2 | Done | `app/xuanwu/tools/sessions/spawn_tool.py` |
| `subagents list/kill/steer` real control path | Design + Plan Phase 2 | Done | `app/xuanwu/tools/sessions/subagents_tool.py` |
| Per-user run persistence under workspace path | Design + Plan Phase 1 | Done | `workspace/users/<user_id>/sessions/subagent_runs.json`, `subagent_runs.log.jsonl` in runtime manager |
| Startup restore and in-flight orphan marking | Design + Plan Phase 1 | Done | `_restore_user()` in `app/xuanwu/subagents/runtime.py` |
| Terminal run retention sweeper | Design + Plan Phase 1 | Done | `_sweeper_loop()` and `_sweep_once()` in `app/xuanwu/subagents/runtime.py` |
| API/channel dependency wiring for runtime and executor | Plan Phase 3 | Done | `app/xuanwu/api/deps_context.py`, `app/xuanwu/channels/manager.py`, `app/xuanwu/main.py` |
| Runtime tests and tool integration tests | Plan Phase 4 | Done | `tests/xuanwu/test_subagent_runtime.py` |
| Orchestrator detached path uses canonical runtime entry | Design runtime wiring contract | Not done | `app/xuanwu/workflow/orchestrator.py` still local executor path |
| Persistence degraded-mode retries and ledger tail repair strategy | Design persistence consistency contract | Not done | Not implemented in runtime manager |
| Runtime knobs promoted into formal config schema | Status follow-up + Known gaps | Not done | Defaults remain constructor params in runtime manager |

## Completed

- Added executable subagent runtime foundation with:
  - spawn/list/kill/steer lifecycle control
  - per-user ownership-scoped run registry
  - startup orphan reconciliation
  - periodic retention sweep
- Replaced sessions tool stubs with runtime-backed implementation.
- Wired runtime into API and channel-scoped dependencies.
- Added dedicated runtime tests and verified broader regression suites.
- Added companion implementation documentation:
  - `docs/SUBAGENT-RUNTIME-IMPLEMENTATION.md`

## Not Completed

- Orchestrator detached execution path is not yet routed through
  `SubagentRuntimeManager.spawn(...)`.
- Persistence hardening from design contract is partial:
  - no malformed-ledger truncation recovery
  - no persist retry/backoff with degraded flag
- Runtime policy defaults are not yet configurable through
  `core/config_schema.py`.

## Verification

- `pytest tests/xuanwu/test_subagent_runtime.py -q` -> `4 passed`
- `pytest tests/xuanwu/test_workflow.py -q` -> `19 passed`
- `pytest tests/xuanwu/session/test_concurrent_scenarios.py -q` -> `11 passed`
- `pytest tests/xuanwu -q` -> `999 passed, 8 skipped, 1 xfailed`

## Notes

- Pytest on Windows still emits a known `PermissionError` during temporary
  directory cleanup (`pytest-current`) after successful completion.
- Current task status is: **core implementation complete, follow-up hardening
  pending**.

## Next Step

Follow-up execution moved into closure task set:

1. `docs/project/tasks/2026-04-06-subagent-ux-closure-design.md`
2. `docs/project/tasks/2026-04-06-subagent-ux-closure-plan.md`
3. `docs/project/tasks/2026-04-06-subagent-ux-closure-status.md`
