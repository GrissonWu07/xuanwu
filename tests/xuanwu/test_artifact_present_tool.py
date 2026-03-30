# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.xuanwu.auth.models import UserInfo
from app.xuanwu.core.deps import SkillDeps
from app.xuanwu.session.manager import SessionManager
from app.xuanwu.thread_files.service import ThreadFileService
from app.xuanwu.tools.filesystem.present_tool import present_files_tool


def _build_ctx(tmp_path, *, user_id: str = "u-present") -> SimpleNamespace:
    manager = SessionManager(workspace_path=str(tmp_path), user_id=user_id)
    deps = SkillDeps(
        user_info=UserInfo(user_id=user_id),
        session_manager=manager,
    )
    return SimpleNamespace(deps=deps)


@pytest.mark.asyncio
async def test_present_files_tool_registers_relative_artifacts_in_deps(tmp_path):
    ctx = _build_ctx(tmp_path)
    service = ThreadFileService(
        workspace_path=str(tmp_path),
        user_id="u-present",
        thread_id="thread-123",
    )
    runtime_batch = await service.create_runtime_batch(batch_id="1711613000")
    outputs_file = runtime_batch.outputs_dir / "report.md"
    outputs_file.parent.mkdir(parents=True, exist_ok=True)
    outputs_file.write_text("# report", encoding="utf-8")

    ctx.deps.extra["attachment_root"] = str(runtime_batch.root)
    result = await present_files_tool(ctx, [str(outputs_file)])

    assert result["is_error"] is False
    assert result["details"]["presented_relative_paths"] == [
        "1711613000/outputs/report.md"
    ]
    assert ctx.deps.extra["presented_artifacts"] == ["1711613000/outputs/report.md"]


@pytest.mark.asyncio
async def test_present_files_tool_rejects_paths_outside_attachment_root(tmp_path):
    ctx = _build_ctx(tmp_path)
    outside_file = Path(tmp_path) / "outside.txt"
    outside_file.write_text("x", encoding="utf-8")
    ctx.deps.extra["attachment_root"] = str(Path(tmp_path) / "users" / "u-present" / "work_dir")

    result = await present_files_tool(ctx, [str(outside_file)])
    assert result["is_error"] is True
