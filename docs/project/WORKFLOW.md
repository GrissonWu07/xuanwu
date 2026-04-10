# Xuanwu Project Workflow

This document defines the required workflow for any LLM or human contributor
making feature, bugfix, refactor, or documentation changes in Xuanwu.

The goal is simple:

- keep implementation aligned with project rules
- make the current project state easy to recover
- make task handoff possible without relying on chat history

## Required Read Order

Before making changes, read these documents in order:

1. `AGENTS.md`
2. `docs/project/WORKFLOW.md`
3. `docs/project/state/CURRENT_STATE.md`
4. `docs/project/state/KNOWN_GAPS.md`
5. Related task files in `docs/project/tasks/`

If the task already has design, plan, or status files, they are mandatory
reading before implementation continues.

## Project Layers

Xuanwu documentation is divided into three layers:

1. Stable rules
   - `AGENTS.md`
   - `docs/ARCHITECTURE.MD`
   - `docs/MODULE-DETAILS.MD`
   - `docs/DEVELOPMENT-SPEC.MD`
2. Current project state
   - `docs/project/state/CURRENT_STATE.md`
   - `docs/project/state/KNOWN_GAPS.md`
3. Task execution records
   - `docs/project/tasks/YYYY-MM-DD-<topic>-design.md`
   - `docs/project/tasks/YYYY-MM-DD-<topic>-plan.md`
   - `docs/project/tasks/YYYY-MM-DD-<topic>-status.md`

## Task Lifecycle

Every non-trivial change should follow this order:

1. Confirm the task scope from existing docs.
2. Create or update a task design doc if behavior or architecture changes.
3. Create or update a task plan before implementation.
4. Implement the change.
5. Run verification.
6. Update the task status doc with what changed and what remains.
7. Update project state docs if the change affects global understanding.

For small fixes, the design and plan can be short, but the status write-back is
still required if the task spans more than a quick one-file change.

## Task File Naming

Task files live under `docs/project/tasks/` and use this naming pattern:

- `YYYY-MM-DD-<topic>-design.md`
- `YYYY-MM-DD-<topic>-plan.md`
- `YYYY-MM-DD-<topic>-status.md`

Use the same `<topic>` segment across all files for the same task.

## Required Write-Back

Before ending work, update the relevant documentation:

- Update the task `status.md` with:
  - completed work
  - remaining work
  - verification commands and outcomes
  - next recommended step
- Update `docs/project/state/CURRENT_STATE.md` if the project-wide shape changed.
- Update `docs/project/state/KNOWN_GAPS.md` if new missing capabilities, risks,
  or technical debt were discovered.

Do not leave task progress only in commit messages or chat transcripts.

## Done Definition

A task is not complete unless all of the following are true:

1. Code or docs changes are implemented.
2. Relevant tests or builds were run.
3. Verification results are recorded in the task status doc or final handoff.
4. Any project-wide impact is reflected in the state docs.
5. The next step is explicit when work remains.

## No Half-Delivery Rule

Xuanwu tasks must be delivered as closed loops, not partial slices.

Required behavior:

1. If a task plan defines multiple in-scope workstreams, all must be completed
   before claiming completion.
2. "Core done, follow-up later" is allowed only when the task is explicitly
   re-scoped and the deferred part is moved into a new task with design/plan/status.
3. If blocked, status must be marked `Blocked` with:
   - blocker reason
   - blocker owner
   - unblock condition
   - expected unblock date (if known)
4. Final handoff must include an explicit closure statement confirming whether
   the task is fully closed.

## Current State Rules

`docs/project/state/CURRENT_STATE.md` should stay short and high-signal.
It should describe:

- the current architectural baseline
- important recently completed capabilities
- active conventions contributors must know before editing

`docs/project/state/KNOWN_GAPS.md` should describe:

- known missing features
- known risks
- known rough edges or follow-up work

Neither file should become a changelog.

## Task Status Rules

Each task status doc should answer:

- What was the goal?
- What is finished?
- What is not finished?
- Which files matter most?
- What verification was run?
- What should the next contributor do first?

If a task is paused, the status doc is the handoff artifact.

## Verification Expectations

Contributors should prefer recording exact commands and outcomes, for example:

- `pytest tests/xuanwu -q`
- `npm test -- --runInBand`
- `npm run build`

If full verification is too expensive, record what was run and what was skipped.

## When Scope Changes

If implementation diverges from the existing plan:

1. update the relevant plan
2. update the status doc
3. update the state docs if the divergence affects future work

Do not silently implement a new direction without writing it back.
