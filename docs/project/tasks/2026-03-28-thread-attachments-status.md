# Thread Attachments Status

## Goal

Restore and complete the chat-first thread attachments MVP for Xuanwu without
turning the product into a separate research workbench.

The implementation should keep chat as the main interaction surface while
supporting uploads, prompt injection, generated outputs, and lightweight
attachment visibility.

## Completed

- Added thread-scoped attachment storage under:
  - `workspace/users/<user_id>/work_dir/attachments/<thread_id>/<unix_timestamp>/`
- Added backend thread file foundation in `app/xuanwu/thread_files/`
- Added session attachment API for listing, uploading, and downloading entries
- Added runtime attachment context injection into prompt building
- Added runtime attachment-path hints to prompt building for deterministic export flow
- Added artifact SSE event emission and artifact download URLs
- Added explicit `present_files` tool for selecting which generated files are exported
- Added built-in document exporters: `export_docx`, `export_pptx`, `export_pdf`
- Added frontend upload entry on the chat page
- Added bottom attachment strip with uploads and outputs
- Added assistant-message artifact links
- Added backend and frontend test coverage for the MVP

## Remaining

- Broader extractor coverage for more document formats
- Attachment cleanup and quota policy
- Richer attachment management actions if product needs grow
- Optional UX refinements after broader usage review

## Key Files

- `app/xuanwu/thread_files/paths.py`
- `app/xuanwu/thread_files/service.py`
- `app/xuanwu/api/routes_session.py`
- `app/xuanwu/api/services/run_service.py`
- `app/xuanwu/agent/runner_prompt_context.py`
- `app/xuanwu/agent/prompt_builder.py`
- `app/xuanwu/agent/prompt_sections.py`
- `app/xuanwu/tools/filesystem/present_tool.py`
- `app/frontend/scripts/pages/chat.js`
- `app/frontend/scripts/chat-ui.js`
- `app/frontend/styles/main.css`

## Verification

- `pytest tests/xuanwu -q` -> `831 passed, 1 xfailed`
- `npm test -- --runInBand` -> `106 passed`
- `npm run build` -> success

## Risks or Notes

- Attachment UX is intentionally lightweight and should remain subordinate to
  chat.
- Custom prompt builders may not accept new keyword arguments, so prompt-context
  changes must stay backward compatible.
- Older design and plan documents may still exist outside `docs/project/tasks/`
  and should be normalized over time.

## Next Step

If attachment work continues, start by reading this file, then review
`docs/project/state/CURRENT_STATE.md` and decide whether the next step is:

- extractor expansion
- retention/quota policy
- UI refinement
- broader integration with future task-state features
