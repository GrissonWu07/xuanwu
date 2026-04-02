# -*- coding: utf-8 -*-

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.xuanwu.auth.models import UserInfo
from app.xuanwu.core.deps import SkillDeps
from app.xuanwu.session.manager import SessionManager
from app.xuanwu.thread_files.service import ThreadFileService
from app.xuanwu.tools.filesystem.export_tools import (
    export_docx_tool,
    export_pdf_tool,
    export_pptx_tool,
)


def _build_ctx(tmp_path, *, user_id: str = "u-export") -> SimpleNamespace:
    manager = SessionManager(workspace_path=str(tmp_path), user_id=user_id)
    deps = SkillDeps(
        user_info=UserInfo(user_id=user_id),
        session_manager=manager,
    )
    return SimpleNamespace(deps=deps)


@pytest.mark.asyncio
async def test_export_docx_creates_file_and_registers_presented_artifact(tmp_path):
    ctx = _build_ctx(tmp_path)
    service = ThreadFileService(
        workspace_path=str(tmp_path),
        user_id="u-export",
        thread_id="thread-001",
    )
    runtime_batch = await service.create_runtime_batch(batch_id="1711615001")
    ctx.deps.extra.update(
        {
            "attachment_root": str(runtime_batch.root),
            "attachment_batch_id": runtime_batch.batch_id,
            "work_dir": str(runtime_batch.workspace_dir),
        }
    )

    result = await export_docx_tool(
        ctx,
        file_path="brief.docx",
        title="Weekly Brief",
        content="Line A\nLine B",
    )

    assert result["is_error"] is False
    assert (runtime_batch.workspace_dir / "brief.docx").exists()
    assert result["details"]["presented"] is True
    assert ctx.deps.extra["presented_artifacts"] == [
        "1711615001/workspace/brief.docx"
    ]


@pytest.mark.asyncio
async def test_export_pptx_creates_file_and_registers_presented_artifact(tmp_path):
    ctx = _build_ctx(tmp_path)
    service = ThreadFileService(
        workspace_path=str(tmp_path),
        user_id="u-export",
        thread_id="thread-001",
    )
    runtime_batch = await service.create_runtime_batch(batch_id="1711615002")
    ctx.deps.extra.update(
        {
            "attachment_root": str(runtime_batch.root),
            "attachment_batch_id": runtime_batch.batch_id,
            "work_dir": str(runtime_batch.workspace_dir),
        }
    )

    result = await export_pptx_tool(
        ctx,
        file_path="deck.pptx",
        title="Demo Deck",
        bullet_points=["Point 1", "Point 2"],
    )

    assert result["is_error"] is False
    assert (runtime_batch.workspace_dir / "deck.pptx").exists()
    assert result["details"]["presented"] is True
    assert ctx.deps.extra["presented_artifacts"] == [
        "1711615002/workspace/deck.pptx"
    ]


@pytest.mark.asyncio
async def test_export_pdf_adds_default_extension_and_registers_presented_artifact(tmp_path):
    ctx = _build_ctx(tmp_path)
    service = ThreadFileService(
        workspace_path=str(tmp_path),
        user_id="u-export",
        thread_id="thread-001",
    )
    runtime_batch = await service.create_runtime_batch(batch_id="1711615003")
    ctx.deps.extra.update(
        {
            "attachment_root": str(runtime_batch.root),
            "attachment_batch_id": runtime_batch.batch_id,
            "work_dir": str(runtime_batch.workspace_dir),
        }
    )

    result = await export_pdf_tool(
        ctx,
        file_path="final-report",
        title="Final Report",
        content="Body text",
    )

    assert result["is_error"] is False
    assert (runtime_batch.workspace_dir / "final-report.pdf").exists()
    assert result["details"]["presented"] is True
    assert ctx.deps.extra["presented_artifacts"] == [
        "1711615003/workspace/final-report.pdf"
    ]


@pytest.mark.asyncio
async def test_export_docx_succeeds_without_attachment_context_but_skips_present(tmp_path):
    ctx = _build_ctx(tmp_path)
    result = await export_docx_tool(
        ctx,
        file_path="local.docx",
        title="Local",
        content="Outside run context",
    )

    assert result["is_error"] is False
    assert result["details"]["presented"] is False
    assert "present_error" in result["details"]
