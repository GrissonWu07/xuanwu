# Xuanwu Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover the local `xuanwu` product identity and re-apply the lost runtime-tool and thread-attachment deltas on top of the latest upstream XuanWu codebase.

**Architecture:** Restore the repository in phases. First rename the product/package/test surface back to `xuanwu`, then reintroduce the already-finished runtime and thread-file backend deltas, then complete the remaining attachment MVP through the existing FastAPI, session/workspace, SSE, and vanilla-JS chat architecture.

**Tech Stack:** FastAPI, async Python services, Pydantic models, filesystem-backed workspace/session storage, vanilla JS frontend, Jest, pytest.

---

### Task 1: Restore repository identity from `xuanwu` to `xuanwu`

**Files:**
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\**`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\tests\xuanwu\**`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\xuanwu.json`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\tests\xuanwu.test.json`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\README.md`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\docs\*.MD`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\frontend\scripts\session-manager.js`

- [ ] **Step 1: Inventory rename-sensitive strings and file paths**

Run:
```powershell
git grep -n "xuanwu\|XuanWu\|app\.xuanwu\|XUANWU_"
```

Record the result groups:
- Python import/package paths
- test paths
- config filenames and env prefixes
- frontend storage keys / labels
- docs and command snippets

- [ ] **Step 2: Write or update failing smoke coverage for renamed imports**

Add/adjust startup and import coverage so the renamed package path is asserted by:
- `tests/xuanwu/test_main_startup.py`
- any import smoke test that currently hard-codes `app.xuanwu`

Target assertions:
- `import app.xuanwu`
- `import app.xuanwu.main`
- startup routes still mount successfully

- [ ] **Step 3: Rename package, tests, and config surface**

Make the minimum repository-wide rename:
- move `app/xuanwu` -> `app/xuanwu`
- move `tests/xuanwu` -> `tests/xuanwu`
- rename `xuanwu.json` -> `xuanwu.json`
- rename `tests/xuanwu.test.json` -> `tests/xuanwu.test.json`
- update imports, CLI examples, config lookups, and user-facing strings

Keep compatibility shims only if tests prove they are needed.

- [ ] **Step 4: Run targeted verification**

Run:
```powershell
python -c "import app.xuanwu; import app.xuanwu.main; print('import-ok')"
pytest tests/xuanwu/test_main_startup.py -q
git grep -n "xuanwu\|XuanWu\|app\.xuanwu\|tests/xuanwu\|XUANWU_" -- . ":(exclude)docs/plans/2026-03-28-xuanwu-recovery-design.md" ":(exclude)docs/plans/2026-03-28-xuanwu-recovery-implementation-plan.md"
```

Expected:
- Python import smoke prints `import-ok`
- startup tests pass
- grep output is limited to intentional compatibility/document-history references

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "refactor(rename): rename xuanwu to xuanwu"
```

### Task 2: Restore the runtime-tool delta

**Files:**
- Create: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\tools\runtime\xuanwu_runtime_client.py`
- Create: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\tools\runtime\xuanwu_runtime_tools.py`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\tools\runtime\__init__.py`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\tools\registration.py`
- Test: `C:\Projects\githubs\myaiagent\xuanwu\tests\xuanwu\test_xuanwu_runtime_tools.py`

- [ ] **Step 1: Write failing runtime-tool tests**

Add coverage for:
- runtime client request/response handling
- tool registration
- tool execution surface and error propagation

Run:
```powershell
pytest tests/xuanwu/test_xuanwu_runtime_tools.py -q
```

Expected: FAIL because the files and registration do not exist yet.

- [ ] **Step 2: Implement the runtime client**

Create `xuanwu_runtime_client.py` with:
- a focused client wrapper
- typed request/response helpers
- explicit exceptions for transport or protocol failures

Do not mix tool registration or UI concerns into the client module.

- [ ] **Step 3: Implement and register runtime tools**

Create `xuanwu_runtime_tools.py` and wire it into `tools/registration.py`:
- expose the intended tool functions
- reuse the runtime client
- keep registration conditional/explicit, matching existing tool patterns

- [ ] **Step 4: Run targeted verification**

Run:
```powershell
pytest tests/xuanwu/test_xuanwu_runtime_tools.py -q
pytest tests/xuanwu/test_main_startup.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/xuanwu/tools/runtime app/xuanwu/tools/registration.py tests/xuanwu/test_xuanwu_runtime_tools.py
git commit -m "feat(runtime): restore xuanwu runtime tools"
```

### Task 3: Restore thread-file foundation and safe storage paths

**Files:**
- Create: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\thread_files\__init__.py`
- Create: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\thread_files\models.py`
- Create: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\thread_files\paths.py`
- Create: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\thread_files\service.py`
- Test: `C:\Projects\githubs\myaiagent\xuanwu\tests\xuanwu\test_thread_file_service.py`

- [ ] **Step 1: Write failing thread-file service tests**

Add tests that cover:
- per-user/per-thread path derivation
- path traversal rejection for user id, thread key, and filenames
- upload persistence into `uploads/`
- `index.json` bootstrap and update behavior
- concurrent-safe metadata writes across service instances

Run:
```powershell
pytest tests/xuanwu/test_thread_file_service.py -q
```

Expected: FAIL because the `thread_files` package does not exist yet.

- [ ] **Step 2: Implement models and safe path helpers**

Add:
- metadata models for uploaded files and artifacts
- path helpers that guarantee containment under the thread root
- helper methods for `uploads/`, `workspace/`, `outputs/`, and `index.json`

Preserve the earlier fixes remembered from the lost implementation:
- reject path traversal via malformed user ids
- reject path traversal via filenames
- make first-write index creation safe on Windows

- [ ] **Step 3: Implement the persistence service**

Create `service.py` with operations for:
- saving upload bytes
- reading/writing index metadata
- listing current thread attachments
- reserving artifact metadata entries

Keep file I/O async where the existing codebase expects async behavior; use the
same style already used in session/workspace services.

- [ ] **Step 4: Run targeted verification**

Run:
```powershell
pytest tests/xuanwu/test_thread_file_service.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/xuanwu/thread_files tests/xuanwu/test_thread_file_service.py
git commit -m "feat(thread-files): restore thread file storage foundation"
```

### Task 4: Restore extractors and mixed context-bundle generation

**Files:**
- Create: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\thread_files\extractors.py`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\thread_files\models.py`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\thread_files\service.py`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\requirements.txt`
- Test: `C:\Projects\githubs\myaiagent\xuanwu\tests\xuanwu\test_thread_file_service.py`

- [ ] **Step 1: Extend tests for mixed injection modes**

Add cases for:
- small text-like files returning `full`
- large text-like files returning `summary`
- binary/unsupported files returning `reference`
- extraction failure degrading gracefully instead of failing the upload

Run:
```powershell
pytest tests/xuanwu/test_thread_file_service.py -q
```

Expected: FAIL because extractor and bundle logic are not implemented yet.

- [ ] **Step 2: Implement lightweight extractors**

Add `extractors.py` with a conservative first-pass extractor:
- support plain text and other low-risk text-like files first
- return structured extraction results
- do not crash on unsupported or malformed files

- [ ] **Step 3: Implement mixed context-bundle assembly**

Update the thread-file service to build a runtime-ready context bundle:
- `full` for small extracted text
- `summary` for large extracted text
- `reference` for unsupported/binary payloads

Persist enough metadata in `index.json` so later APIs and the frontend can show
file status and injection mode without reprocessing everything on each request.

- [ ] **Step 4: Run targeted verification**

Run:
```powershell
pytest tests/xuanwu/test_thread_file_service.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/xuanwu/thread_files requirements.txt tests/xuanwu/test_thread_file_service.py
git commit -m "feat(thread-files): restore mixed attachment context bundles"
```

### Task 5: Add thread attachment APIs and artifact download surface

**Files:**
- Create: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\api\routes_thread_files.py`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\api\schemas.py`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\main.py`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\thread_files\service.py`
- Test: `C:\Projects\githubs\myaiagent\xuanwu\tests\xuanwu\test_thread_file_api.py`

- [ ] **Step 1: Write failing API tests**

Add coverage for:
- `POST /api/threads/{thread_id}/uploads`
- `GET /api/threads/{thread_id}/attachments`
- `DELETE /api/threads/{thread_id}/uploads/{file_id}`
- `GET /api/threads/{thread_id}/artifacts/{artifact_name}`
- ownership/isolation behavior between two users or two threads

Run:
```powershell
pytest tests/xuanwu/test_thread_file_api.py -q
```

Expected: FAIL because the routes do not exist yet.

- [ ] **Step 2: Add API schemas and routes**

Create route handlers that stay thin:
- validate auth/request state
- resolve current user/thread context
- delegate to `thread_files.service`
- return metadata suitable for the chat attachment strip

Do not duplicate path or index logic in the API layer.

- [ ] **Step 3: Expose artifact downloads safely**

Implement download/open behavior with strict containment checks:
- only files inside the thread `outputs/` area are downloadable
- path normalization must reject attempts to escape the thread root

- [ ] **Step 4: Run targeted verification**

Run:
```powershell
pytest tests/xuanwu/test_thread_file_api.py -q
pytest tests/xuanwu/test_main_startup.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/xuanwu/api/routes_thread_files.py app/xuanwu/api/schemas.py app/xuanwu/main.py app/xuanwu/thread_files/service.py tests/xuanwu/test_thread_file_api.py
git commit -m "feat(api): add thread attachment upload and artifact routes"
```

### Task 6: Inject attachment context at runtime and surface artifacts in streams

**Files:**
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\agent\runner.py`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\agent\prompt_builder.py`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\api\sse.py`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\api\response_handler.py`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\xuanwu\thread_files\service.py`
- Test: `C:\Projects\githubs\myaiagent\xuanwu\tests\xuanwu\test_agent_run_api.py`
- Test: `C:\Projects\githubs\myaiagent\xuanwu\tests\xuanwu\test_sse_replay.py`

- [ ] **Step 1: Write failing runtime integration tests**

Add tests that verify:
- the current thread's attachment bundle is included before a run
- empty attachment state does not break runs
- generated outputs can be registered as artifacts
- SSE/replay payloads can surface artifact links

Run:
```powershell
pytest tests/xuanwu/test_agent_run_api.py -q
pytest tests/xuanwu/test_sse_replay.py -q
```

Expected: FAIL because no attachment-context injection or artifact events exist.

- [ ] **Step 2: Add prompt/context injection**

Update runtime execution so each run:
- resolves the current thread
- fetches its attachment context bundle
- appends a dedicated attachment section to the prompt/context construction

Keep transcript storage and attachment context separate; do not write attachment
content directly into persisted transcript history.

- [ ] **Step 3: Add artifact registration and stream exposure**

Introduce a small artifact-reporting flow:
- register outputs produced during the run
- include downloadable link metadata in the assistant response path
- emit stream/replay entries that frontend code can render as clickable links

- [ ] **Step 4: Run targeted verification**

Run:
```powershell
pytest tests/xuanwu/test_agent_run_api.py -q
pytest tests/xuanwu/test_sse_replay.py -q
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/xuanwu/agent app/xuanwu/api/sse.py app/xuanwu/api/response_handler.py app/xuanwu/thread_files/service.py tests/xuanwu/test_agent_run_api.py tests/xuanwu/test_sse_replay.py
git commit -m "feat(agent): inject thread attachments and stream artifacts"
```

### Task 7: Add chat upload UX, persistent attachment strip, and output links

**Files:**
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\frontend\scripts\api-client.js`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\frontend\scripts\chat-ui.js`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\frontend\scripts\session-manager.js`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\frontend\scripts\pages\chat.js`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\app\frontend\styles\*.css`
- Test: `C:\Projects\githubs\myaiagent\xuanwu\tests\frontend\**`

- [ ] **Step 1: Write failing frontend tests or reproducible UI checks**

Cover:
- composer upload action
- thin attachment strip below the input
- attachment/output refresh after upload and after a reply creates an artifact
- assistant message rendering of clickable output links

Run:
```powershell
cd app/frontend
npm test -- --runInBand
```

Expected: FAIL for new attachment behaviors before implementation.

- [ ] **Step 2: Implement upload and attachment-fetch client calls**

Update frontend API helpers to:
- upload files into the current thread
- fetch current `attachments + outputs`
- delete uploaded attachments when requested

- [ ] **Step 3: Implement the lightweight chat UI**

Add the agreed product shape:
- upload affordance in the composer
- a fixed, small attachment strip below the input
- output links visible both in-message and in the persistent strip

Do not add a side panel, workbench layout, or deep-research navigation.

- [ ] **Step 4: Run targeted verification**

Run:
```powershell
cd app/frontend
npm test -- --runInBand
npm run build
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/frontend
git commit -m "feat(frontend): add chat attachment strip and output links"
```

### Task 8: Update documentation and run full recovery verification

**Files:**
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\README.md`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\AGENTS.md`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\docs\ARCHITECTURE.MD`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\docs\MODULE-DETAILS.MD`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\docs\DEVELOPMENT-SPEC.MD`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\docs\plans\2026-03-28-xuanwu-recovery-design.md`
- Modify: `C:\Projects\githubs\myaiagent\xuanwu\docs\plans\2026-03-28-xuanwu-recovery-implementation-plan.md`

- [ ] **Step 1: Update canonical docs to match the recovered state**

Refresh docs so they describe:
- `xuanwu` naming and config entry points
- runtime-tool availability
- thread attachment architecture and light chat UX

- [ ] **Step 2: Run backend and frontend verification**

Run:
```powershell
pytest tests/xuanwu -q
cd app/frontend
npm test -- --runInBand
npm run build
```

Expected:
- backend test suite passes
- frontend tests pass
- frontend production build succeeds

- [ ] **Step 3: Run final rename sweep**

Run:
```powershell
git grep -n "xuanwu\|XuanWu\|app\.xuanwu\|tests/xuanwu\|XUANWU_"
```

Expected: only intentional compatibility or historical-document references remain.

- [ ] **Step 4: Commit**

```bash
git add README.md AGENTS.md docs
git commit -m "docs(recovery): document recovered xuanwu state"
```
