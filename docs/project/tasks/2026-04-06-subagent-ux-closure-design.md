# Subagent UX Closure Design

## Goal

Complete the user-facing closure loop for subagent runtime so that users can:

- see subagent acceptance immediately
- see progress while task is running
- receive completion/failure automatically in current chat thread
- open artifacts via clickable links from both message and attachment strip

This design also folds in unfinished backend foundations and documents a strict
"no half-delivery" closure rule for this task.

## Visual Mockup

- Mockup file:
  - `docs/images/mockups/2026-04-06-subagent-ux-closure.svg`

Design highlights:

- keep chat as primary surface
- fixed one-line attachment strip below input
- fixed one-line subagent strip below attachment strip
- artifact links appear both in assistant message and attachment strip
- subagent actions (`Steer`, `Kill`, `Open Result`) available in strip
- no dedicated research page / no workspace pivot
- when active SA batch exists, chat remains usable and new SA creation is gated

## Scope

In scope:

- Frontend interaction closure for subagent runtime visibility
- Backend event delivery path needed by that UX
- Completion of previously unfinished 3 runtime items
- Documentation/process updates to enforce full task closure

Out of scope:

- unrelated chat redesign
- multi-page workbench/product pivot

## Closure Contract (Task-Level Hard Gate)

This task is considered complete only when all items in the plan are done.
No partial "core done, follow-up later" handoff is allowed for this task.

If any item cannot be completed, status must be `Blocked` with explicit reason,
owner, and unblock condition; otherwise no completion claim.

## Required Completion Set

### A. User Interaction Closure

1. Subagent lifecycle visibility in active chat run:
   - accepted/running/completed/failed/killed state updates visible in UI
2. Automatic completion callback into current conversation:
   - completion/failure summary message emitted without requiring manual polling
3. Artifact link dual-surface guarantee:
   - message card link
   - persistent attachment strip link
4. Stream tail safety:
   - prevent dropping late artifact/subagent terminal events

### B. Previous 3 Unfinished Runtime Points

1. Orchestrator detached/hierarchical path uses canonical subagent runtime entry
   (`SubagentRuntimeManager.spawn(...)`) when detached execution is requested.
2. Persistence hardening:
   - malformed ledger tail handling
   - persist retry/backoff and degraded marker
3. Runtime policy knobs promoted into formal config schema and load path.

### C. Validation and Documentation Closure

1. Unit/integration/E2E tests for full UX closure chain.
2. State docs and task status docs updated with evidence.
3. Workflow/task template updates to encode no-half-delivery standard.

## Design Decisions

### Event Contract

Introduce explicit subagent runtime SSE events for active run streams:

- `subagent_status`:
  - `queued|running|completed|failed|killed|timed_out`
  - includes `run_id`, `subagent_id`, `label`, `summary`, `error`, `artifact_refs`

### Message Write-Back Strategy

When a subagent reaches terminal status:

- append a system-style assistant message to current thread transcript with:
  - subagent identity
  - terminal status
  - short output/error summary
  - clickable artifact links if available

### Frontend Surface Strategy

- Keep the current chat page model.
- Add compact fixed "Subagents strip" under attachment strip.
- Strip shows active/recent child runs and supports action buttons.
- Message timeline gets one completion card per terminal subagent run.
- Add "SA mode transparency chip" in timeline:
  - why SA was chosen
  - planned branch count
  - one-click switch to single-agent for current round

### Active Batch Lock and Queue UX

- Thread-level single active SA batch.
- If user sends a request that would spawn new SA while one is active:
  - `continue_current_batch`: show inline info and keep progressing current batch
  - `queued_next_request`: show queued badge (max queue size configurable, default 1)
  - `rejected_queue_full`: explicit reject toast + inline action choices
- User can choose "replace current batch" to kill existing batch then start new one.

### Multi-turn UX While SA Is Running

- New user messages continue to receive main-agent replies.
- Default behavior: no additional SA spawn during active batch window.
- Top-of-input lightweight status line shows current batch progress summary.

### Kill / Retry Semantics

- `Kill Run`: terminate one run only.
- `Kill Batch`: terminate all active runs in current batch.
- Existing artifacts from terminated runs are retained and marked partial.
- Failed runs support:
  - `Retry with same context`
  - `Retry with edit` (user can modify task)

### Completion Receipt UX

On batch terminal, push one auto summary message containing:

- completed/failed/canceled counts
- artifact count and links
- suggested next action

### Noise Control and Reconnect Recovery

- Progress cards update in place (no repeated message spam).
- Apply throttle/coalescing for stream updates (target 300-500ms).
- Reconnect sequence:
  - fetch latest batch snapshot first
  - attach stream subscription with cursor
  - replay missed deltas idempotently

### Permission and Safety UX

- Action visibility follows role:
  - owner/editor: `steer/kill/retry`
  - viewer: read-only status and links
- Unauthorized actions must return clear user-visible reason.
- Stalled detection (> configured no-progress window):
  - show "possibly stuck"
  - offer `keep waiting` or `stop and summarize partial`

### Stream Ordering Rule

Do not close stream immediately on lifecycle `end` if there are pending
artifact/subagent-terminal events in the queue. Close only after tail flush.

### Runtime Unavailable Rule

`sessions_spawn` runtime-unavailable path must be explicit error (not accepted
placeholder) in user-facing semantics.

## Acceptance Criteria

1. User triggers `sessions_spawn` and immediately sees accepted state.
2. User sees running state changes without invoking `subagents list`.
3. On completion/failure, user sees automatic chat message with summary.
4. Artifact links are clickable in message and visible in attachment strip.
5. Refresh/reload still preserves visibility through transcript + attachment list.
6. All 3 previously unfinished runtime points are implemented and verified.
7. Task status can mark "Complete" only when every planned item is done.
8. Active SA batch lock + queue semantics are visible and deterministic.
9. SA mode transparency and one-click single-agent override are available.
10. Retry/stall/timeout/permission edge cases all have explicit user feedback.
