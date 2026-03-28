# Known Gaps

This document lists known missing capabilities, risks, and follow-up areas that
contributors should be aware of before starting new work.

## Product and UX Gaps

- Chat attachments currently focus on a lightweight MVP and do not yet provide:
  - richer attachment management actions
  - advanced previews
  - heavier task-workbench affordances
- The chat product still needs consistent UX review across desktop and mobile
  after each new surface is added.

## Attachments Follow-Up

- More file extractors may still be needed for broader office-document support.
- Artifact presentation is link-first; richer previews are intentionally out of
  scope for now.
- Long-term retention, cleanup, and quota policies for attachment batches should
  be reviewed if storage usage grows.

## Runtime and Orchestration Gaps

- Sub-agent runtime remains a separate follow-up area and should not be mixed
  casually into attachment work.
- Structured long-term memory improvements are still a separate track from the
  attachment context bundle.

## Documentation Gaps

- Not every historical task has been normalized into the new
  `docs/project/tasks/` structure yet.
- Older docs in `docs/plans/` may still contain useful context but should not be
  treated as the canonical task handoff format going forward.

## Process Gaps

- Contributors may still leave progress only in chat or commit history unless
  task status docs are actively maintained.
- When a task changes system shape, `CURRENT_STATE.md` must be updated or the
  next contributor will start from stale assumptions.
