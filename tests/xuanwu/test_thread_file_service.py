# -*- coding: utf-8 -*-
"""Tests for thread attachment storage helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.xuanwu.thread_files.paths import ThreadFilePaths
from app.xuanwu.thread_files.service import ThreadFileService


class TestThreadFilePaths:
    def test_paths_are_scoped_under_user_work_dir_attachments(self, tmp_path):
        paths = ThreadFilePaths(
            workspace_path=str(tmp_path),
            user_id="u-alice",
            thread_id="thread-123",
        )

        assert paths.root == (
            tmp_path
            / "users"
            / "u-alice"
            / "work_dir"
            / "attachments"
            / "thread-123"
        )
        assert paths.batch_root("1711612345") == paths.root / "1711612345"
        assert paths.uploads_dir("1711612345") == paths.batch_root("1711612345") / "uploads"
        assert paths.workspace_dir("1711612345") == paths.batch_root("1711612345") / "workspace"
        assert paths.outputs_dir("1711612345") == paths.batch_root("1711612345") / "outputs"
        assert paths.index_path("1711612345") == paths.batch_root("1711612345") / "index.json"


class TestThreadFileService:
    @pytest.mark.asyncio
    async def test_save_upload_bytes_persists_into_timestamped_bucket(self, tmp_path):
        service = ThreadFileService(
            workspace_path=str(tmp_path),
            user_id="u-alice",
            thread_id="thread-123",
        )

        record = await service.save_upload_bytes(
            "hello.txt",
            b"hello world",
            content_type="text/plain",
            batch_id="1711612345",
        )

        upload_path = (
            tmp_path
            / "users"
            / "u-alice"
            / "work_dir"
            / "attachments"
            / "thread-123"
            / "1711612345"
            / "uploads"
            / Path(record.relative_path).name
        )
        assert upload_path.exists()
        assert upload_path.read_bytes() == b"hello world"
        assert record.filename == "hello.txt"
        assert record.batch_id == "1711612345"
        assert record.relative_path.startswith("1711612345/uploads/")

    @pytest.mark.asyncio
    async def test_list_attachments_and_build_prompt_bundle_aggregate_all_batches(self, tmp_path):
        service = ThreadFileService(
            workspace_path=str(tmp_path),
            user_id="u-alice",
            thread_id="thread-123",
        )

        await service.save_upload_bytes(
            "small.txt",
            b"hello from upload",
            content_type="text/plain",
            batch_id="1711612345",
        )
        await service.save_upload_bytes(
            "large.txt",
            ("abcdef " * 3000).encode("utf-8"),
            content_type="text/plain",
            batch_id="1711612399",
        )

        uploads = await service.list_current_thread_attachments()
        assert [item.filename for item in uploads] == ["large.txt", "small.txt"]

        bundle = await service.build_prompt_context_bundle()
        upload_entries = bundle["uploads"]
        assert [item["filename"] for item in upload_entries] == ["large.txt", "small.txt"]
        assert upload_entries[0]["injection_mode"] == "summary"
        assert upload_entries[1]["injection_mode"] == "full"
        assert "hello from upload" in upload_entries[1]["content"]

    @pytest.mark.asyncio
    async def test_finalize_runtime_artifacts_registers_new_workspace_and_output_files(self, tmp_path):
        service = ThreadFileService(
            workspace_path=str(tmp_path),
            user_id="u-alice",
            thread_id="thread-123",
        )

        runtime_batch = await service.create_runtime_batch(batch_id="1711612455")
        before = await service.snapshot_runtime_files(runtime_batch.batch_id)

        generated_workspace = runtime_batch.workspace_dir / "notes.md"
        generated_workspace.parent.mkdir(parents=True, exist_ok=True)
        generated_workspace.write_text("# Notes", encoding="utf-8")

        generated_output = runtime_batch.outputs_dir / "report.txt"
        generated_output.parent.mkdir(parents=True, exist_ok=True)
        generated_output.write_text("report body", encoding="utf-8")

        artifacts = await service.finalize_runtime_artifacts(runtime_batch.batch_id, before)

        assert [item.name for item in artifacts] == ["notes.md", "report.txt"]
        assert artifacts[0].relative_path == "1711612455/workspace/notes.md"
        assert artifacts[1].relative_path == "1711612455/outputs/report.txt"

    @pytest.mark.asyncio
    async def test_finalize_runtime_artifacts_honors_presented_paths_when_provided(self, tmp_path):
        service = ThreadFileService(
            workspace_path=str(tmp_path),
            user_id="u-alice",
            thread_id="thread-123",
        )

        runtime_batch = await service.create_runtime_batch(batch_id="1711612555")
        before = await service.snapshot_runtime_files(runtime_batch.batch_id)

        generated_workspace = runtime_batch.workspace_dir / "scratch.tmp"
        generated_workspace.parent.mkdir(parents=True, exist_ok=True)
        generated_workspace.write_text("temp", encoding="utf-8")

        generated_output = runtime_batch.outputs_dir / "final-report.pdf"
        generated_output.parent.mkdir(parents=True, exist_ok=True)
        generated_output.write_text("%PDF-1.7", encoding="utf-8")

        presented = [f"{runtime_batch.batch_id}/outputs/final-report.pdf"]
        artifacts = await service.finalize_runtime_artifacts(
            runtime_batch.batch_id,
            before,
            presented_relative_paths=presented,
        )

        assert [item.name for item in artifacts] == ["final-report.pdf"]
        assert artifacts[0].relative_path == "1711612555/outputs/final-report.pdf"
