# Subagent Runtime Implementation Plan

## Goal

Implement a production-usable subagent runtime in XuanWu based on the approved
design, while preserving existing tool names:

- `sessions_spawn`
- `subagents`

## Architecture Approach

- Add a dedicated backend runtime manager for subagent lifecycle/state/persistence.
- Keep `sessions_spawn` non-blocking and make it schedule real background execution.
- Implement `subagents list/kill/steer` against the same registry.
- Inject runtime/executor dependencies through `SkillDeps.extra` in API and channel flows.

## Phase Progress

| Phase | Status | Notes |
|---|---|---|
| Phase 1 - Runtime Foundation | Done | Runtime manager, models, persistence, restore-orphan, sweeper implemented |
| Phase 2 - Tool Integration | Done | `sessions_spawn` and `subagents` runtime-backed |
| Phase 3 - Runtime Wiring | Done | API/channel/main lifecycle wiring completed |
| Phase 4 - Verification | Done (current scope) | Runtime tests + targeted regression + full backend tests passed |

Follow-up items tracked in status doc and known gaps are outside this phase baseline.

## Implementation Phases

### Phase 1 - Runtime Foundation

1. Add `app/xuanwu/subagents/` runtime package:
   - run status model
   - run record model
   - spawn/kill/steer/list service
   - persistence under:
     - `workspace/users/<user_id>/sessions/subagent_runs.json`
     - `workspace/users/<user_id>/sessions/subagent_runs.log.jsonl`
2. Implement startup restoration:
   - load persisted records
   - reconcile non-terminal runs as `orphaned`
3. Implement sweeper:
   - periodic cleanup of terminal records after retention window

### Phase 2 - Tool Integration

1. Replace `tools/sessions/spawn_tool.py` stub with runtime-backed spawn.
2. Replace `tools/sessions/subagents_tool.py` stub with:
   - `list`
   - `kill` (single + all + cascade)
   - `steer` (restart-based)
3. Keep backward-safe behavior if runtime dependencies are absent.

### Phase 3 - Runtime Wiring

1. Extend API runtime context (`APIContext`) with subagent runtime handle.
2. Create executable subagent callback wiring:
   - child run uses `AgentRunner.run(...)`
   - isolated child `session_key`
   - bounded inherited context packing metadata
3. Wire into:
   - API request path (`build_scoped_deps`)
   - channel message path (`ChannelManager`)
4. Initialize runtime in app lifespan startup and stop on shutdown.

### Phase 4 - Verification

1. Add unit tests for runtime manager:
   - spawn + completion
   - kill transitions
   - steer restart linkage
   - persistence restore + orphan mark
2. Add tool integration tests:
   - `sessions_spawn` returns accepted + run ids and reaches terminal status
   - `subagents list/kill/steer` semantics
3. Run targeted and full test suites.

## Verification Commands

- `pytest tests/xuanwu/test_subagent_runtime.py -q`
- `pytest tests/xuanwu/test_workflow.py -q`
- `pytest tests/xuanwu/session/test_concurrent_scenarios.py -q`
- `pytest tests/xuanwu -q`

## Notes

- This task intentionally focuses on backend runtime/control-plane and does not
  add frontend UI changes.
- If implementation constraints require any semantic deviation from the design,
  update both `design.md` and `status.md` in the same change.
