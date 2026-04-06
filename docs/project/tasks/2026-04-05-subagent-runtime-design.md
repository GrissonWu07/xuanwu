# Subagent Runtime Design

## Goal

Design a truly executable subagent runtime for XuanWu that keeps the existing
`sessions_spawn` and `subagents` tool interfaces, while adding production-grade:

- isolated child execution contexts
- non-blocking spawn + lifecycle tracking
- concurrent execution limits
- `list / kill / steer` control-plane semantics
- restart recovery and stale-run cleanup

This document is design-only and does not include implementation.

## Scope

In scope:

- Runtime design for subagent execution and lifecycle management
- Runtime state model and persistence strategy
- Control API semantics for `subagents` actions
- Concurrency, timeout, and cleanup policies
- Comparison-based design decisions from OpenClaw and deer-flow

Out of scope:

- Frontend UI updates
- Channel-specific delivery behavior changes
- Full implementation and migration scripts

## Current XuanWu Baseline

Current repository state:

- `workflow/orchestrator.py` already defines orchestration abstractions
  (`sequential`, `parallel`, `delegate`, `hierarchical`).
- Tool registration already exposes `sessions_spawn` and `subagents`.
- `tools/sessions/spawn_tool.py` returns accepted-like payloads but does not run
  real child runtime.
- `tools/sessions/subagents_tool.py` is still a stub for `list`, `kill`, and
  `steer`.

Conclusion: XuanWu has the surface contract but not a complete executable
subagent runtime.

## External Reference Comparison

### OpenClaw (control-plane strong)

Reference files:

- `openclaw-ref/src/agents/subagent-registry.ts`
- `openclaw-ref/src/agents/subagent-control.ts`
- `openclaw-ref/src/agents/subagent-orphan-recovery.ts`
- `openclaw-ref/src/agents/tools/sessions-spawn-tool.ts`
- `openclaw-ref/src/agents/tools/subagents-tool.ts`

Useful patterns:

- Run registry as a first-class subsystem (run ids, child session mapping,
  ownership, status, cleanup policy).
- Non-blocking `sessions_spawn` returning accepted response immediately.
- Full control plane (`list`, `kill`, `steer`) with ownership and scope checks.
- Cascade stop for descendants.
- Restart orphan recovery and reconciliation.
- Timed sweeper for archival/cleanup.

### deer-flow (execution-plane strong)

Reference files:

- `deer-flow/subagents/executor.py`
- `deer-flow/tools/builtins/task_tool.py`
- `deer-flow/agents/middlewares/subagent_limit_middleware.py`

Useful patterns:

- Thread-pool-backed async background execution.
- Explicit execution status model and timeout handling.
- Streamable task lifecycle events (`task_started`, `task_running`,
  `task_completed`, `task_failed`, `task_timed_out`).
- Concurrency limiting middleware near tool call generation.
- Cleanup of terminal background tasks to prevent memory leak.

### Design decision

Adopt a hybrid:

- OpenClaw-style registry + recovery + control semantics
- deer-flow-style execution manager + event stream + concurrency guarding

## Proposed Architecture

### Components

1. `SubagentRunRegistry`
- Single source of truth for subagent run records.
- Stores run metadata, status, timestamps, ownership, and cleanup policy.
- Provides query indices for requester/controller/child-session lookups.

2. `SubagentRuntimeManager`
- Accepts spawn requests and schedules execution asynchronously.
- Applies timeout and cancellation.
- Emits lifecycle events and updates registry transitions.

3. `SubagentControlService`
- Implements `subagents` actions:
  - `list`
  - `kill`
  - `steer`
- Enforces ownership, control scope, and rate limiting.

4. `SubagentLifecycleReconciler`
- Restores in-flight records on startup.
- Detects orphaned runs and tries resume/finalize flow.
- Sweeps terminal records by retention policy.

5. `SubagentPolicyGuard`
- Enforces:
  - max spawn depth
  - max children per parent session
  - global max concurrent subagents
  - sandbox inheritance policy

## Runtime Wiring Contract

To avoid dual execution paths, subagent execution must have one canonical
runtime entry:

- Canonical entry: `SubagentRuntimeManager.spawn(...)`
- `sessions_spawn` tool is the primary user-facing trigger and must call the
  canonical entry directly.
- `workflow/orchestrator.py` `delegate` and `hierarchical` modes must route
  child-agent execution through the same canonical entry when they require
  detached/isolated subagent runs.
- Simple in-process mock execution in orchestrator remains valid only for
  non-detached local planning/testing paths and must not create persisted
  subagent run records.

Ownership and identifiers:

- Parent run id and parent session key are always attached to child run record.
- Child run record becomes the source of truth for `subagents list/kill/steer`.
- No component other than `SubagentRuntimeManager` may mutate lifecycle status.

## Runtime Data Model

`SubagentRunRecord` (proposed fields):

- `run_id`
- `subagent_id`
- `child_session_key`
- `requester_session_key`
- `controller_session_key` (optional)
- `task`
- `label` (optional)
- `status` (`pending|running|completed|failed|timed_out|killed|orphaned`)
- `created_at`, `started_at`, `ended_at`
- `timeout_seconds`
- `cleanup_policy` (`keep|delete`)
- `depth`
- `model` (optional)
- `error` (optional)
- `metadata` (optional dict)

Storage location:

- Persist under user workspace conventions:
  - `workspace/users/<user_id>/sessions/subagent_runs.json`
  - optional append-only ledger:
    `workspace/users/<user_id>/sessions/subagent_runs.log.jsonl`

Persistence consistency contract:

- Single-writer discipline per user workspace via async lock keyed by `user_id`.
- Snapshot writes use atomic temp-file + replace semantics.
- Ledger writes are append-only; on malformed trailing line, startup recovery
  truncates to last valid record.
- Registry mutation is memory-first then persisted; if persist fails, mutation
  is retried with backoff and run is flagged `persistence_degraded` in metadata.
- Startup reconciliation must tolerate partial snapshot/ledger mismatch by
  rebuilding runtime view from the newest valid data.

## State Machine

- `pending -> running`
- `running -> completed | failed | timed_out | killed`
- `running -> orphaned` (process restart / lost executor)
- `orphaned -> running` (resume success)
- `orphaned -> failed` (resume failed)
- terminal states enter retention and sweeper cleanup pipeline

## Tool Contract Design

### `sessions_spawn`

Keep current tool name and semantics, but make it truly executable:

- always non-blocking
- returns immediately:
  - `status = accepted`
  - `run_id`
  - `subagent_id`
  - `child_session_key`
  - selected runtime settings (timeout/model/depth)

Validation:

- deny if depth/concurrency policy violated
- deny when requester requires sandbox but child runtime cannot satisfy

### `subagents`

#### `action=list`

- list active + recent runs visible to requester/controller
- include compact status, runtime duration, and target identifiers

#### `action=kill`

- support target by run id / subagent id
- support `all`
- cascade descendants
- idempotent behavior for already-terminal runs

#### `action=steer`

- only for active run
- ownership required
- enforce steer message length and rate limit
- default behavior: restart-based steer (OpenClaw-compatible control model)
- optional future mode: in-run message injection (`steer_mode=inplace`) is
  explicitly out of current implementation scope
- when restart steer is accepted:
  - old run transitions to `killed` with reason `steer_restart`
  - new run id is created and linked through `metadata.replaces_run_id`
  - `subagents list` shows newest run as active target for subsequent control

## Concurrency and Isolation Policies

Recommended defaults:

- `max_spawn_depth = 1`
- `max_children_per_session = 2`
- `max_concurrent_subagents = 8`
- `subagent_default_timeout_seconds = 900`
- `steer_rate_limit_ms = 2000`

Isolation:

- child subagent uses dedicated child session key
- inherited context must be bounded (summary + selected transcript tail)
- session-management tools denied for leaf subagents by default
- only orchestrator-role subagents may gain controlled session tool subset

Context injection rule table:

- Inputs:
  - parent run summary
  - parent transcript tail
  - explicitly passed task payload
  - selected attachment/file references
- Hard limits (defaults):
  - summary budget: 2,000 chars
  - transcript tail: last 20 messages and max 12,000 chars
  - combined inherited context cap: 16,000 chars
- Truncation order:
  1. keep explicit task payload in full when possible
  2. keep structured summary
  3. trim transcript tail oldest-first
  4. drop non-essential metadata blocks
- Sensitive-field policy:
  - redact configured secrets/tokens from inherited context
  - pass file paths as references, not raw file content, unless tool explicitly
    requests content materialization
- Determinism:
  - runtime stores context packing stats in run metadata:
    `summary_chars`, `tail_messages`, `tail_chars`, `truncated=true|false`

## Recovery and Cleanup

Startup recovery:

1. load persisted run registry
2. identify non-terminal records
3. reconcile with live runtime handles
4. mark orphaned where no live handle exists
5. attempt resume/finalize strategy

Sweeper:

- periodic cleanup of terminal runs after retention window
- optional session/transcript cleanup when `cleanup_policy=delete`
- best-effort artifact/attachment cleanup if owned by child run

## Error Handling Design

Expected failures should map to explicit result states:

- policy denial -> tool error (`forbidden`/`limit_exceeded`)
- execution crash -> `failed`
- timeout -> `timed_out`
- kill request -> `killed`
- restart loss -> `orphaned` then reconciled

All transitions must be monotonic and idempotent.

## Verification Strategy (for implementation phase)

Unit:

- state transition correctness and idempotency
- policy guard boundaries (depth/children/concurrency)
- ownership and target resolution for `kill`/`steer`

Integration:

- non-blocking spawn with real completion updates
- timeout and kill flows
- steer restart flow
- orchestrator delegate/hierarchical path uses canonical spawn runtime

Recovery:

- restart with in-flight runs -> orphan detection and reconcile
- sweeper cleanup of terminal records
- snapshot/ledger mismatch recovery and last-valid-line replay

## Rollout Plan (high level)

Phase 1:

- implement registry + persistent storage
- wire `sessions_spawn` to real async runtime manager

Phase 2:

- implement `subagents list/kill/steer` control service
- add policy guard and runtime limits

Phase 3:

- add restart reconciler + sweeper
- add observability metrics/events and E2E tests

## Risks and Mitigations

- Risk: concurrency storms from nested delegation
  - Mitigation: strict depth/children/global caps and early policy rejection
- Risk: stale records after crash
  - Mitigation: startup reconciliation and orphan lifecycle
- Risk: unauthorized control of sibling runs
  - Mitigation: explicit requester/controller ownership checks
- Risk: memory growth in background manager
  - Mitigation: terminal cleanup and bounded in-memory caches

## Open Questions

- Should subagent output be auto-announced to parent session in all channels, or
  be configurable per agent/channel?
- Should depth-1 orchestrator role be explicit config, or inferred from
  `max_spawn_depth` and profile?
