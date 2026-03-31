# Xuanwu Recovery Design

## Background

`C:\Projects\githubs\myaiagent\xuanwu` is now attached to the latest upstream
`CloudChef/xuanwu` codebase. The repository is healthy again, but it has
lost the local deltas that existed earlier in this project:

1. The repository identity is back to `xuanwu`, not `xuanwu`.
2. The runtime-tool additions that had already been implemented locally are no
   longer present.
3. The thread-attachments foundation that had already reached a tested backend
   state is no longer present.

This design defines how to recover those missing deltas on top of the current
upstream code without forking the architecture away from upstream XuanWu.

## Current Snapshot

The current upstream snapshot is characterized by:

- backend package path: `app/xuanwu`
- backend tests: `tests/xuanwu`
- root config: `xuanwu.json`
- frontend session/local-storage naming still using `xuanwu`
- runtime tools limited to:
  - `app/xuanwu/tools/runtime/exec_tool.py`
  - `app/xuanwu/tools/runtime/process_tool.py`
- no thread attachment module under `app/xuanwu/thread_files`

This means recovery must be treated as a staged re-application of local product
identity and missing features, not as a bugfix inside an already-renamed tree.

## Recovery Goals

1. Re-establish the local product identity as `xuanwu` across code, tests,
   configuration, and user-facing text.
2. Restore the previously completed runtime-tool delta with tests.
3. Restore the previously completed thread-file backend foundation with tests.
4. Finish the remaining thread-attachments MVP that was only partially built.
5. Keep the final result aligned with the existing XuanWu architecture:
   async-first, thin core, provider-oriented, permission-safe.

## Non-Goals

- Re-architecting XuanWu core concepts or replacing FastAPI/PydanticAI.
- Turning the chat product into a deep-research workspace UI.
- Building a full document-conversion pipeline in the first recovery pass.
- Replaying every historic local commit exactly as before. The goal is functional
  recovery on top of the current upstream base, not commit-history restoration.

## Constraints

### Product constraint

`xuanwu` should remain a chat-first enterprise agent. Thread attachments are a
lightweight conversation enhancement, not the center of the product.

### Architecture constraint

Recovered functionality must fit the current XuanWu structure:

- request routing and auth remain in the existing API/auth layers
- session and workspace storage stay file-system based unless the code already
  supports database-backed metadata
- new capability modules should be added as focused services instead of pushing
  logic into route handlers or frontend page files

### Recovery constraint

Part of the recovery depends on conversation memory of previously implemented
local changes. Those pieces must be reintroduced conservatively and validated
against the current upstream code instead of pasted back blindly.

## Recovered Scope

### Scope A: Repository identity recovery

Recover the local `xuanwu` identity everywhere it matters:

- Python package/import path
- test package path
- config filenames and environment variable prefixes where required
- frontend storage keys and user-visible branding
- docs, examples, and verification commands

This phase is intentionally isolated so later feature recovery happens inside the
correct package namespace.

### Scope B: Runtime tool recovery

Recover the previously added runtime integration layer:

- runtime client module
- runtime tools module
- tool registration wiring
- backend tests for tool behavior and registration

This phase restores capabilities that had already been working locally and keeps
them separate from the attachment project.

### Scope C: Thread-file backend recovery

Recover the previously completed backend foundation for thread-level file state:

- `thread_files` package
- safe path resolution
- per-thread `uploads/`, `workspace/`, `outputs/`, `index.json`
- upload persistence service
- lightweight text extraction with graceful degradation
- mixed context bundle generation:
  - small text-like files -> `full`
  - large text-like files -> `summary`
  - binary/unsupported files -> `reference`

This is the storage and context-preparation layer only. It does not yet expose
user-facing upload APIs or frontend controls.

### Scope D: Remaining attachments MVP

Finish the user-facing part of thread attachments:

- upload/list/delete/download APIs
- runtime attachment-context injection before agent execution
- artifact registration and streaming exposure
- chat UI upload entry in the composer
- small persistent attachment strip below the input
- assistant-message output links plus persistent output links in the strip

The UI must stay intentionally light. No side workspace, no file-centric page,
no deep-research layout.

## Chosen Recovery Strategy

Use a **phased delta-recovery strategy**:

1. Recover naming and namespace first.
2. Recover already-finished backend/runtime deltas next.
3. Complete the remaining attachment MVP only after the recovered foundation is
   back in place and passing tests.

This is preferable to either of the alternatives:

- **Big-bang replay**: fast in theory, but too risky because the upstream base
  has moved and the prior local tree is gone.
- **Attachments-first without rename**: would force new work into `xuanwu`
  paths and create avoidable churn when the rename is restored later.

## Target Architecture

### 1. Product identity layer

The repository becomes `xuanwu` again at the package and product level, while
remaining structurally compatible with the current upstream architecture.

### 2. Runtime tools layer

Runtime integration remains a focused tool/runtime submodule under the existing
tools system. It should not leak provider logic into unrelated core modules.

### 3. Thread file service layer

Introduce a focused backend subsystem responsible for thread-scoped file state:

- `models.py` for thread file records, artifact records, and context bundles
- `paths.py` for safe directory/key resolution and containment checks
- `extractors.py` for content extraction and summary generation
- `service.py` for persistence, metadata updates, and context-bundle assembly

Routes and runtime consume this service; they do not own its storage logic.

### 4. Lightweight chat attachment UX

The frontend keeps chat as the primary surface:

- upload affordance lives inside the composer
- thread attachments appear in a thin strip below the input
- outputs appear both in the reply that created them and in the strip as
  clickable links

This preserves the existing mental model: chat with optional attached context.

## Data and Storage Model

After recovery, each thread should have a dedicated storage area under the user
workspace. The logical shape is:

- `workspace/users/<user_id>/threads/<thread_key>/uploads/`
- `workspace/users/<user_id>/threads/<thread_key>/workspace/`
- `workspace/users/<user_id>/threads/<thread_key>/outputs/`
- `workspace/users/<user_id>/threads/<thread_key>/index.json`

The exact path helper may derive `thread_key` from the canonical session/thread
identity, but the isolation rule is fixed: thread-scoped storage nested under
the authenticated user.

## Failure Handling

Recovery work should preserve predictable degradation:

- rename mismatches should fail fast in tests and grep-based verification
- unsupported file extraction should not fail uploads; it should fall back to a
  metadata/reference-only context entry
- invalid artifact/download paths must be rejected with containment checks
- missing attachment metadata should not crash a run; runtime should inject an
  empty attachment section instead

## Testing Strategy

Testing is split by phase:

- rename phase: import smoke tests, grep sweeps, startup tests
- runtime phase: targeted runtime tool tests plus registration checks
- thread-file phase: unit tests for path safety, persistence, mixed bundle
  generation, and concurrency-sensitive index updates
- attachments MVP phase: API tests, runtime integration tests, frontend Jest
  tests, and a production build

The recovered code is only considered complete when the final repository passes
both targeted tests and the broader regression checks that already exist.

## Acceptance Criteria

The recovery is complete when all of the following are true:

1. The active codebase is consistently `xuanwu`-named in package paths, test
   paths, root config naming, and user-visible frontend identity.
2. The runtime-tool additions are present, registered, and covered by tests.
3. `thread_files` exists with safe path handling, upload persistence, extractor
   fallback behavior, and mixed context bundle generation covered by tests.
4. Thread attachment APIs and frontend chat integration work end to end.
5. Attachment outputs are exposed as clickable links both in-message and in the
   persistent attachment/output strip.
6. Documentation is updated to describe the recovered `xuanwu` state and the
   thread-attachment behavior.

## Risks And Mitigations

### Risk: memory-driven reconstruction drifts from current upstream

Mitigation:

- restore in small phases
- validate each phase against current tests
- prefer upstream patterns when remembered details conflict with current code

### Risk: rename touches many files and creates noisy diffs

Mitigation:

- isolate rename as its own early phase
- verify with grep and startup tests before layering features on top

### Risk: attachment work expands into a workspace-centric product

Mitigation:

- keep the UI constrained to composer upload + thin strip + output links
- explicitly reject side panels and heavy file workbench behavior in this MVP

## Delivery Order

1. `xuanwu` identity recovery
2. runtime-tool recovery
3. thread-file backend recovery
4. remaining thread-attachments MVP
5. documentation and full verification

This order keeps namespace churn behind us before feature work continues.
