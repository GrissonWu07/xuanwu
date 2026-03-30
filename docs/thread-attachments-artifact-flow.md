# Thread Attachments & Artifact Flow

This document describes the end-to-end thread attachment flow in XuanWu, including:

- user uploads
- runtime generated artifacts
- signed in-session download links with expiration

## 1. Storage Layout

All thread files are scoped under user workspace:

`workspace/users/<user_id>/work_dir/attachments/<thread_id>/<unix-timestamp>/`

Each batch contains:

- `uploads/` user uploaded files
- `workspace/` runtime workspace files
- `outputs/` final/generated deliverables
- `index.json` attachment index metadata

## 2. Upload API

Route:

- `POST /api/sessions/{session_key}/attachments`

Behavior:

- backend reads upload bytes and persists to thread batch `uploads/`
- upload metadata is written into `index.json`
- response returns upload entry with signed `download_url` and `expires_at`

Implementation references:

- `app/xuanwu/api/routes_session.py`
- `app/xuanwu/thread_files/service.py`
- `app/xuanwu/api/attachment_links.py`

## 3. Runtime Injection

When running `POST /api/agent/run`, backend creates a runtime batch and injects:

- `attachment_context` (uploads/artifacts summary for prompt)
- `attachment_batch_id`
- `attachment_root`
- `attachment_uploads_dir`
- `attachment_workspace_dir`
- `attachment_outputs_dir`
- scoped `work_dir` defaulting to batch workspace

Implementation references:

- `app/xuanwu/api/services/run_service.py`
- `app/xuanwu/agent/runner_prompt_context.py`
- `app/xuanwu/agent/prompt_builder.py`
- `app/xuanwu/agent/prompt_sections.py`
- `app/xuanwu/tools/work_dir_guard.py`

## 4. Runtime Artifact Export

### 4.1 Explicit export (recommended)

Tool:

- `present_files(file_paths=[...])`

Rules:

- paths must stay inside current attachment batch root
- tool normalizes to `batch_id/...` relative path
- tool records `deps.extra["presented_artifacts"]`

At run finalization:

- backend prioritizes `presented_artifacts`
- only presented files are exported as thread artifacts
- SSE emits `artifact` events with signed download link

Implementation references:

- `app/xuanwu/tools/filesystem/present_tool.py`
- `app/xuanwu/thread_files/service.py`
- `app/xuanwu/api/services/run_service.py`
- `app/xuanwu/api/sse.py`

### 4.2 Fallback export

If no `present_files` selection exists, finalizer falls back to legacy behavior:

- export newly-created files in current batch `workspace/` and `outputs/`

## 5. Signed Download Link

Download route:

- `GET /api/sessions/{session_key}/attachments/{entry_id}/content`

Authorization:

- session owner can access directly
- non-owner requires valid signed query:
  - `expires_at`
  - `sig`
- invalid/expired signature returns `403`

The same signed-link mechanism is used for:

- upload list API
- upload response
- runtime artifact SSE payload

## 6. ACP / Sub-agent Output Convention

If a sub-agent writes outputs under `/mnt/acp-workspace`:

1. copy files into current thread batch `outputs/` or `workspace/`
2. call `present_files` on copied paths
3. let finalizer expose signed artifact links

This keeps all customer-visible deliverables inside thread-scoped, user-scoped storage.

## 7. Frontend Surface

Current chat UX presents files in two places:

- inline artifact links in assistant messages
- persistent attachment strip below chat input (uploads + artifacts)

This keeps chat as the primary interaction surface while allowing revisit/download.
