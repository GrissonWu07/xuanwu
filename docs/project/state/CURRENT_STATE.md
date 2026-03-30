# Current State

This document captures the current high-level state of the Xuanwu codebase.
It is intentionally short and should be read before continuing any active task.

## Product Shape

Xuanwu is a chat-first enterprise agent framework.

The product center is still conversational interaction, not a deep-research
workspace. Files, outputs, tools, and workflow features should support chat
runs rather than replace the chat surface as the primary interaction model.

## Core Architecture Baseline

- Backend code lives in `app/xuanwu/`
- Frontend code lives in `app/frontend/`
- Tests live in `tests/xuanwu/` and `tests/frontend/`
- Core runtime patterns are:
  - async-first request handling
  - thin core, rich providers
  - prompt-driven agent execution
  - per-user workspace storage under `workspace/users/<user_id>/`

## Important Current Capabilities

- `atlasclaw` naming has been restored to `xuanwu` across the active codebase.
- Runtime tool support has been restored under `app/xuanwu/tools/runtime/`.
- Session titles and related chat-header behavior are present.
- Thread-scoped chat attachments are implemented in the active attachments work:
  - backend thread file service
  - session attachment API
  - runtime attachment prompt injection
  - runtime attachment-path/export hints in system prompt
  - explicit `present_files` artifact selection tool
  - artifact SSE events
  - chat upload entry and bottom attachment strip

## Active Storage Conventions

- Per-user workspace root: `workspace/users/<user_id>/`
- User working directory: `workspace/users/<user_id>/work_dir/`
- Thread attachment storage:
  - `workspace/users/<user_id>/work_dir/attachments/<thread_id>/<unix_timestamp>/`

Each attachment batch may contain:

- `uploads/`
- `workspace/`
- `outputs/`
- `index.json`

## Active Frontend Conventions

- Chat remains the primary page model.
- Attachment UX should stay lightweight.
- Uploaded files should appear in a small strip below the input area.
- Generated outputs should appear both:
  - in the assistant response as clickable links
  - in the bottom attachment strip for later reuse

## Contributor Notes

- Do not treat chat attachments as a reason to redesign Xuanwu into a separate
  workbench product.
- Prefer extending existing routes and prompt/runtime structures over adding a
  second orchestration system.
- Before continuing an existing task, read its task files in
  `docs/project/tasks/`.
