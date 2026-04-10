# Subagent UX Closure Implementation Plan

## Goal

Deliver a fully closed-loop subagent user experience and finish all pending
runtime foundation items in one task cycle.

## Hard Rule

All items in this plan must be completed before claiming task completion.
No partial delivery is allowed for this task.

## Workstreams

## Workstream 1 - Backend Event and Write-Back Closure

1. Add explicit subagent event emission path:
   - runtime status publish hooks
   - SSE event type and payload schema (`subagent_status`)
2. Add terminal write-back into transcript:
   - completed summary message
   - failed/killed/timed_out error summary
   - artifact links in message body when available
3. Remove accepted-placeholder semantics on runtime-unavailable spawn path:
   - return explicit error behavior to user
4. Ensure stream tail flush ordering:
   - lifecycle end does not drop late artifact/subagent events
5. Add thread-level active batch lock and queue policy:
   - single active SA batch per thread
   - queue slot limit (default 1, configurable)
   - explicit conflict outcomes (`continue/queue/reject`)
6. Add idempotent spawn guard:
   - idempotency key + atomic check to prevent duplicate spawn on retry/reconnect
7. Add terminal batch receipt generation:
   - completed/failed/canceled counts
   - artifact summary
   - next-step hint
8. Add retry and stall handling paths:
   - retry_same_context / retry_with_edit
   - stalled detection and timeout partial summary
9. Enforce role-based permission checks for steer/kill/retry.

## Workstream 2 - Frontend Interaction Closure

1. Add fixed compact subagent strip under attachment strip:
   - active and recent items
   - status chip
   - actions: `Steer`, `Kill`, `Open Result`
2. Subscribe and render `subagent_status` stream events in realtime.
3. Render terminal completion card in chat timeline from write-back message.
4. Keep artifact dual-surface behavior:
   - message card links
   - attachment strip links
5. Add SA-mode transparency UI:
   - why upgraded
   - planned subagent count
   - one-click switch to single-agent for current round
6. Add active-batch conflict UX:
   - continue current batch
   - queued next request
   - queue full rejection with action hints
7. Ensure multi-turn consistency while SA is active:
   - main-agent replies still available
   - no implicit extra SA spawn
8. Add retry/stall/timeout user actions:
   - retry same context
   - retry with edit
   - keep waiting
   - stop and summarize partial
9. Add reconnect recovery flow:
   - fetch snapshot then stream resume by cursor

## Workstream 3 - Finish Previous 3 Unresolved Runtime Items

1. Route orchestrator detached path through canonical runtime entry.
2. Implement persistence hardening:
   - malformed ledger tail handling
   - persist retry/backoff
   - degraded persistence marker
3. Promote runtime knobs to config schema and loading:
   - spawn depth
   - concurrent limits
   - timeout
   - steer rate limit
   - retention and sweep interval

## Workstream 4 - Verification

1. Unit tests:
   - runtime event publish/state transition
   - persistence degraded/recovery behavior
   - orchestrator detached runtime routing
2. API/SSE integration tests:
   - accepted -> running -> terminal stream continuity
   - artifact/subagent tail event delivery after lifecycle end boundary
3. Frontend interaction tests:
   - subagent strip realtime updates
   - action controls behavior
   - dual artifact surface
   - SA transparency + single-agent override
   - active batch conflict semantics
   - reconnect recovery and in-place progress coalescing
4. Full regression:
   - `pytest tests/xuanwu -q`
   - frontend tests/build if touched
5. E2E specific scenarios:
   - active batch exists: continue/queue/reject
   - SA running: follow-up message answered by main-agent
   - kill run vs kill batch semantics and artifact retention
   - permission denied for steer/kill/retry
   - stalled and timeout partial-summary behavior

## Workstream 5 - Documentation Closure

1. Update runtime implementation doc with final closed-loop architecture.
2. Update task status doc with evidence for every workstream.
3. Update state docs (`CURRENT_STATE.md` / `KNOWN_GAPS.md`).
4. Update workflow/template docs to encode no-half-delivery rule.

## Definition of Done

All of the following must be true:

1. Every planned item in Workstreams 1-5 is done.
2. Verification commands are executed and recorded with outcomes.
3. No "remaining items" section contains unresolved in-scope work.
4. Task status is marked complete with links to updated docs and tests.
