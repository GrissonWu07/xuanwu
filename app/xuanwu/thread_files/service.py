# -*- coding: utf-8 -*-
"""Persistence and prompt-context helpers for thread attachments."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from app.xuanwu.thread_files.models import (
    ThreadArtifactRecord,
    ThreadFileIndex,
    ThreadRuntimeBatch,
    ThreadUploadRecord,
)
from app.xuanwu.thread_files.paths import ThreadFilePaths

_INDEX_LOCKS: dict[str, asyncio.Lock] = {}
_INDEX_LOCKS_GUARD = threading.Lock()
_SMALL_TEXT_THRESHOLD_BYTES = 8 * 1024
_SUMMARY_MAX_CHARS = 1200


def _get_index_lock(lock_key: str) -> asyncio.Lock:
    with _INDEX_LOCKS_GUARD:
        lock = _INDEX_LOCKS.get(lock_key)
        if lock is None:
            lock = asyncio.Lock()
            _INDEX_LOCKS[lock_key] = lock
        return lock


def _utc_timestamp_bucket() -> str:
    return str(int(time.time()))


class ThreadFileService:
    """Manage thread-scoped uploads, runtime batches, and generated artifacts."""

    def __init__(self, workspace_path: str, user_id: str, thread_id: str) -> None:
        self.paths = ThreadFilePaths(
            workspace_path=workspace_path,
            user_id=user_id,
            thread_id=thread_id,
        )

    async def save_upload_bytes(
        self,
        filename: str,
        data: bytes,
        *,
        content_type: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> ThreadUploadRecord:
        """Persist an uploaded file into a timestamped batch."""
        target_batch = batch_id or _utc_timestamp_bucket()
        extract = self._extract_prompt_content(
            filename=filename,
            data=data,
            content_type=content_type,
        )
        record = ThreadUploadRecord.create(
            batch_id=target_batch,
            filename=Path(filename).name,
            relative_path="",
            size_bytes=len(data),
            content_type=content_type,
            sha256=hashlib.sha256(data).hexdigest(),
            injection_mode=extract["injection_mode"],
            content=extract["content"],
            summary=extract["summary"],
        )
        upload_path = self.paths.upload_path(
            target_batch,
            f"{record.upload_id}-{record.filename}",
        )
        record.relative_path = str(upload_path.relative_to(self.paths.root)).replace(os.sep, "/")

        await asyncio.to_thread(self.paths.ensure_batch_dirs, target_batch)
        await asyncio.to_thread(upload_path.write_bytes, data)

        lock_key = str(self.paths.index_path(target_batch))
        async with _get_index_lock(lock_key):
            index = await asyncio.to_thread(self._read_index_locked, target_batch)
            index.upsert_upload(record)
            await asyncio.to_thread(self._write_index_locked, target_batch, index)

        return record

    async def list_current_thread_attachments(self) -> list[ThreadUploadRecord]:
        """Return uploads across all batches for the thread, newest first."""
        uploads: list[ThreadUploadRecord] = []
        for batch_id in await self.list_batch_ids():
            index = await self.read_index(batch_id)
            uploads.extend(index.uploads)
        return sorted(uploads, key=lambda item: item.created_at, reverse=True)

    async def list_current_thread_artifacts(self) -> list[ThreadArtifactRecord]:
        """Return artifacts across all batches for the thread, newest first."""
        artifacts: list[ThreadArtifactRecord] = []
        for batch_id in await self.list_batch_ids():
            index = await self.read_index(batch_id)
            artifacts.extend(index.artifacts)
        return sorted(artifacts, key=lambda item: item.created_at, reverse=True)

    async def build_prompt_context_bundle(self) -> dict[str, list[dict[str, object]]]:
        """Build a structured prompt bundle for the current thread attachments."""
        uploads = [
            {
                "filename": item.filename,
                "relative_path": item.relative_path,
                "batch_id": item.batch_id,
                "content_type": item.content_type or "",
                "size_bytes": item.size_bytes,
                "injection_mode": item.injection_mode,
                "content": item.content if item.injection_mode == "full" else item.summary,
                "summary": item.summary,
            }
            for item in await self.list_current_thread_attachments()
        ]
        artifacts = [
            {
                "name": item.name,
                "relative_path": item.relative_path,
                "batch_id": item.batch_id,
                "status": item.status,
                "size_bytes": item.size_bytes,
            }
            for item in await self.list_current_thread_artifacts()
        ]
        return {"uploads": uploads, "artifacts": artifacts}

    async def create_runtime_batch(self, *, batch_id: Optional[str] = None) -> ThreadRuntimeBatch:
        """Create or resolve the active runtime batch paths for a run."""
        target_batch = batch_id or _utc_timestamp_bucket()
        await asyncio.to_thread(self.paths.ensure_batch_dirs, target_batch)
        return ThreadRuntimeBatch(
            batch_id=target_batch,
            root=self.paths.batch_root(target_batch),
            uploads_dir=self.paths.uploads_dir(target_batch),
            workspace_dir=self.paths.workspace_dir(target_batch),
            outputs_dir=self.paths.outputs_dir(target_batch),
            index_path=self.paths.index_path(target_batch),
        )

    async def snapshot_runtime_files(self, batch_id: str) -> set[str]:
        """Snapshot files currently present in the runtime workspace/output dirs."""
        return await asyncio.to_thread(self._snapshot_runtime_files_sync, batch_id)

    async def finalize_runtime_artifacts(
        self,
        batch_id: str,
        before_paths: set[str],
    ) -> list[ThreadArtifactRecord]:
        """Register new workspace/output files as downloadable artifacts."""
        new_paths = await asyncio.to_thread(self._snapshot_runtime_files_sync, batch_id)
        created_paths = sorted(new_paths - set(before_paths))
        created_paths.sort(
            key=lambda item: (
                0 if item.startswith(f"{batch_id}/workspace/") else 1,
                item,
            )
        )
        if not created_paths:
            return []

        lock_key = str(self.paths.index_path(batch_id))
        async with _get_index_lock(lock_key):
            index = await asyncio.to_thread(self._read_index_locked, batch_id)
            created_records: list[ThreadArtifactRecord] = []
            for relative_path in created_paths:
                full_path = self.paths.root / relative_path
                record = ThreadArtifactRecord.create(
                    batch_id=batch_id,
                    name=Path(relative_path).name,
                    relative_path=relative_path.replace(os.sep, "/"),
                    size_bytes=full_path.stat().st_size if full_path.exists() else 0,
                )
                index.upsert_artifact(record)
                created_records.append(record)
            await asyncio.to_thread(self._write_index_locked, batch_id, index)
            return created_records

    async def read_index(self, batch_id: str) -> ThreadFileIndex:
        """Load the batch-local index, bootstrapping an empty file when needed."""
        lock_key = str(self.paths.index_path(batch_id))
        async with _get_index_lock(lock_key):
            return await asyncio.to_thread(self._read_index_locked, batch_id)

    async def list_batch_ids(self) -> list[str]:
        """Return known batch ids for the current thread, newest first."""
        root = self.paths.root
        if not root.exists():
            return []
        return sorted([item.name for item in root.iterdir() if item.is_dir()], reverse=True)

    async def resolve_entry(
        self,
        entry_id: str,
    ) -> tuple[str, ThreadUploadRecord | ThreadArtifactRecord, Path]:
        """Resolve a saved upload or artifact by entry id."""
        for item in await self.list_current_thread_attachments():
            if item.upload_id == entry_id:
                return "upload", item, (self.paths.root / item.relative_path).resolve()
        for item in await self.list_current_thread_artifacts():
            if item.artifact_id == entry_id:
                return "artifact", item, (self.paths.root / item.relative_path).resolve()
        raise FileNotFoundError(f"Unknown attachment entry: {entry_id}")

    def _snapshot_runtime_files_sync(self, batch_id: str) -> set[str]:
        collected: set[str] = set()
        for base_dir in (self.paths.workspace_dir(batch_id), self.paths.outputs_dir(batch_id)):
            if not base_dir.exists():
                continue
            for path in base_dir.rglob("*"):
                if path.is_file():
                    collected.add(str(path.relative_to(self.paths.root)).replace(os.sep, "/"))
        return collected

    def _read_index_locked(self, batch_id: str) -> ThreadFileIndex:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.paths.ensure_batch_dirs(batch_id)
        index_path = self.paths.index_path(batch_id)
        if not index_path.exists():
            index = ThreadFileIndex()
            self._write_index_locked(batch_id, index)
            return index
        raw = index_path.read_text(encoding="utf-8").strip()
        if not raw:
            index = ThreadFileIndex()
            self._write_index_locked(batch_id, index)
            return index
        return ThreadFileIndex.from_dict(json.loads(raw))

    def _write_index_locked(self, batch_id: str, index: ThreadFileIndex) -> None:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.paths.ensure_batch_dirs(batch_id)
        index_path = self.paths.index_path(batch_id)
        tmp_path = index_path.parent / f"{index_path.name}.{uuid.uuid4().hex}.tmp"
        tmp_path.write_text(
            json.dumps(index.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, index_path)

    def _extract_prompt_content(
        self,
        *,
        filename: str,
        data: bytes,
        content_type: Optional[str],
    ) -> dict[str, str]:
        extension = Path(filename).suffix.lower()
        normalized_content_type = (content_type or "").lower()
        is_text = normalized_content_type.startswith("text/") or extension in {
            ".txt",
            ".md",
            ".json",
            ".py",
            ".js",
            ".ts",
            ".html",
            ".css",
            ".csv",
            ".yml",
            ".yaml",
        }
        if not is_text:
            return {"injection_mode": "reference", "content": "", "summary": ""}

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="ignore")

        normalized = " ".join(text.split())
        if not normalized:
            return {"injection_mode": "reference", "content": "", "summary": ""}
        if len(data) <= _SMALL_TEXT_THRESHOLD_BYTES:
            return {
                "injection_mode": "full",
                "content": text.strip(),
                "summary": normalized[:_SUMMARY_MAX_CHARS],
            }
        return {
            "injection_mode": "summary",
            "content": "",
            "summary": normalized[:_SUMMARY_MAX_CHARS],
        }
