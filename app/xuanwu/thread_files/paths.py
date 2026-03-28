# -*- coding: utf-8 -*-
"""Safe thread attachment path helpers."""

from __future__ import annotations

from pathlib import Path

from app.xuanwu.core.security_guard import ensure_user_work_dir


def _reject_segment(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    if text in {".", ".."}:
        raise ValueError(f"{field_name} must not be a traversal segment")
    if any(sep in text for sep in ("/", "\\")):
        raise ValueError(f"{field_name} must not contain path separators")
    if ":" in text:
        raise ValueError(f"{field_name} must not contain ':'")
    return text


def _resolve_child(base: Path, relative_path: str, field_name: str) -> Path:
    candidate = Path(str(relative_path or ""))
    if candidate.is_absolute():
        raise ValueError(f"{field_name} must be relative")
    if any(part in {"..", "."} for part in candidate.parts):
        raise ValueError(f"{field_name} must not contain traversal components")

    resolved = (base / candidate).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"{field_name} must stay inside {base}") from exc
    return resolved


class ThreadFilePaths:
    """Resolve thread-scoped attachment storage paths."""

    def __init__(self, workspace_path: str, user_id: str, thread_id: str) -> None:
        self._workspace_path = Path(workspace_path).resolve()
        self._user_id = _reject_segment(user_id, "user_id")
        self._thread_id = _reject_segment(thread_id, "thread_id")
        self._attachments_root = ensure_user_work_dir(self._workspace_path, self._user_id) / "attachments"
        self._root = self._attachments_root / self._thread_id

    @property
    def root(self) -> Path:
        return self._root

    def batch_root(self, batch_id: str) -> Path:
        return self.root / _reject_segment(batch_id, "batch_id")

    def uploads_dir(self, batch_id: str) -> Path:
        return self.batch_root(batch_id) / "uploads"

    def workspace_dir(self, batch_id: str) -> Path:
        return self.batch_root(batch_id) / "workspace"

    def outputs_dir(self, batch_id: str) -> Path:
        return self.batch_root(batch_id) / "outputs"

    def index_path(self, batch_id: str) -> Path:
        return self.batch_root(batch_id) / "index.json"

    def upload_path(self, batch_id: str, filename: str) -> Path:
        safe_filename = _reject_segment(Path(filename).name, "filename")
        return _resolve_child(self.uploads_dir(batch_id), safe_filename, "filename")

    def ensure_batch_dirs(self, batch_id: str) -> None:
        self.uploads_dir(batch_id).mkdir(parents=True, exist_ok=True)
        self.workspace_dir(batch_id).mkdir(parents=True, exist_ok=True)
        self.outputs_dir(batch_id).mkdir(parents=True, exist_ok=True)
