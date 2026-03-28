# Task Records

This directory stores task-specific design, implementation, and handoff records.

## Naming

Use one topic slug per task and keep the files aligned:

- `YYYY-MM-DD-<topic>-design.md`
- `YYYY-MM-DD-<topic>-plan.md`
- `YYYY-MM-DD-<topic>-status.md`

Example:

- `2026-03-28-thread-attachments-design.md`
- `2026-03-28-thread-attachments-plan.md`
- `2026-03-28-thread-attachments-status.md`

## Purpose of Each File

- `design.md`
  - architecture and product decisions
  - boundaries and trade-offs
- `plan.md`
  - ordered implementation tasks
  - verification strategy
- `status.md`
  - what is done
  - what is not done
  - key files
  - verification results
  - next step

## Rules

- If a task resumes after a pause, update the existing `status.md` instead of
  creating a second handoff note elsewhere.
- If the implementation changes direction, update the `plan.md` and mention the
  change in `status.md`.
- If the work affects project-wide understanding, also update
  `docs/project/state/CURRENT_STATE.md` or `KNOWN_GAPS.md`.
