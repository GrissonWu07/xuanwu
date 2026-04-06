# -*- coding: utf-8 -*-
"""Subagent runtime and tool integration tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.xuanwu.core.deps import SkillDeps
from app.xuanwu.session.manager import SessionManager
from app.xuanwu.tools.sessions.spawn_tool import sessions_spawn_tool
from app.xuanwu.tools.sessions.subagents_tool import subagents_tool
from app.xuanwu.subagents.models import (
    SpawnSubagentRequest,
    SubagentExecutionRequest,
    SubagentExecutionResult,
    SubagentRunStatus,
)
from app.xuanwu.subagents.runtime import SubagentRuntimeManager


@dataclass
class _DummyCtx:
    deps: SkillDeps


@pytest.mark.asyncio
async def test_runtime_spawn_executes_and_completes(tmp_path: Path):
    runtime = SubagentRuntimeManager(workspace_path=str(tmp_path))
    await runtime.start()

    async def executor(req: SubagentExecutionRequest) -> SubagentExecutionResult:
        await asyncio.sleep(0.02)
        return SubagentExecutionResult(
            status=SubagentRunStatus.COMPLETED,
            output=f"done:{req.task}",
        )

    created = await runtime.spawn(
        SpawnSubagentRequest(
            user_id="u1",
            requester_session_key="agent:main:user:u1:main",
            controller_session_key="agent:main:user:u1:main",
            task="collect logs",
            depth=1,
        ),
        executor=executor,
    )

    assert created.run_id
    assert created.status in {SubagentRunStatus.PENDING, SubagentRunStatus.RUNNING}

    await asyncio.sleep(0.08)
    record = await runtime.get_run("u1", created.run_id)
    assert record is not None
    assert record.status == SubagentRunStatus.COMPLETED
    assert record.output == "done:collect logs"

    await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_single_active_batch_queues_and_drains(tmp_path: Path):
    runtime = SubagentRuntimeManager(
        workspace_path=str(tmp_path),
        max_queued_batches_per_controller=1,
    )
    await runtime.start()

    async def executor(req: SubagentExecutionRequest) -> SubagentExecutionResult:
        await asyncio.sleep(0.1)
        return SubagentExecutionResult(
            status=SubagentRunStatus.COMPLETED,
            output=f"done:{req.task}",
        )

    controller_key = "agent:main:user:u-queue:main"
    first = await runtime.spawn(
        SpawnSubagentRequest(
            user_id="u-queue",
            requester_session_key=controller_key,
            controller_session_key=controller_key,
            task="task-1",
            depth=1,
            single_active_batch=True,
            queue_if_busy=True,
        ),
        executor=executor,
    )
    second = await runtime.spawn(
        SpawnSubagentRequest(
            user_id="u-queue",
            requester_session_key=controller_key,
            controller_session_key=controller_key,
            task="task-2",
            depth=1,
            single_active_batch=True,
            queue_if_busy=True,
        ),
        executor=executor,
    )

    assert first.metadata.get("spawn_outcome") == "accepted"
    assert second.metadata.get("spawn_outcome") == "queued_next_request"
    assert second.metadata.get("queue_state") == "queued"

    await asyncio.sleep(0.35)
    first_record = await runtime.get_run("u-queue", first.run_id)
    second_record = await runtime.get_run("u-queue", second.run_id)
    assert first_record is not None
    assert second_record is not None
    assert first_record.status == SubagentRunStatus.COMPLETED
    assert second_record.status == SubagentRunStatus.COMPLETED

    await runtime.stop()


@pytest.mark.asyncio
async def test_spawn_tool_returns_error_when_runtime_unavailable(tmp_path: Path):
    workspace_path = str(tmp_path / "workspace")
    session_manager = SessionManager(workspace_path=workspace_path, user_id="user-tool")
    deps = SkillDeps(
        session_key="agent:main:user:user-tool:main",
        session_manager=session_manager,
        extra={},
    )
    ctx = _DummyCtx(deps=deps)
    result = await sessions_spawn_tool(ctx=ctx, prompt="prepare summary")
    assert result["is_error"] is True
    assert result["details"]["status"] == "runtime_unavailable"


@pytest.mark.asyncio
async def test_spawn_tool_queue_full_returns_rejected_status(tmp_path: Path):
    workspace_path = str(tmp_path / "workspace")
    session_manager = SessionManager(workspace_path=workspace_path, user_id="user-tool")
    runtime = SubagentRuntimeManager(
        workspace_path=workspace_path,
        max_queued_batches_per_controller=0,
    )
    await runtime.start()

    async def executor(req: SubagentExecutionRequest) -> SubagentExecutionResult:
        await asyncio.sleep(0.2)
        return SubagentExecutionResult(status=SubagentRunStatus.COMPLETED, output=req.task)

    deps = SkillDeps(
        session_key="agent:main:user:user-tool:main",
        session_manager=session_manager,
        extra={
            "run_id": "parent-run-1",
            "subagent_depth": 0,
            "subagent_runtime": runtime,
            "subagent_executor": executor,
        },
    )
    ctx = _DummyCtx(deps=deps)

    accepted = await sessions_spawn_tool(ctx=ctx, prompt="task A")
    rejected = await sessions_spawn_tool(ctx=ctx, prompt="task B")
    assert accepted["is_error"] is False
    assert rejected["is_error"] is True
    assert rejected["details"]["status"] == "rejected_queue_full"

    await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_emits_run_and_batch_terminal_callbacks(tmp_path: Path):
    run_terminal: list[str] = []
    batch_terminal: list[str] = []
    status_events: list[tuple[str, str]] = []

    async def on_run_terminal(record):
        run_terminal.append(record.run_id)

    async def on_batch_terminal(payload):
        batch_terminal.append(str(payload.get("batch_id", "")))

    async def on_status(payload):
        status_events.append(
            (
                str(payload.get("event", "")),
                str(payload.get("outcome", "")),
            )
        )

    runtime = SubagentRuntimeManager(
        workspace_path=str(tmp_path),
        on_run_terminal=on_run_terminal,
        on_batch_terminal=on_batch_terminal,
        on_status=on_status,
    )
    await runtime.start()

    async def executor(req: SubagentExecutionRequest) -> SubagentExecutionResult:
        await asyncio.sleep(0.02)
        return SubagentExecutionResult(
            status=SubagentRunStatus.COMPLETED,
            output=req.task,
        )

    created = await runtime.spawn(
        SpawnSubagentRequest(
            user_id="u-hook",
            requester_session_key="agent:main:user:u-hook:main",
            controller_session_key="agent:main:user:u-hook:main",
            task="emit callbacks",
            depth=1,
            single_active_batch=True,
            queue_if_busy=True,
        ),
        executor=executor,
    )
    batch_id = str((created.metadata or {}).get("batch_id", ""))
    await asyncio.sleep(0.15)
    assert created.run_id in run_terminal
    assert batch_id in batch_terminal
    assert ("spawn", "accepted") in status_events
    assert ("run_started", "running") in status_events
    assert ("run_terminal", SubagentRunStatus.COMPLETED.value) in status_events

    await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_kill_marks_run_killed(tmp_path: Path):
    runtime = SubagentRuntimeManager(workspace_path=str(tmp_path))
    await runtime.start()

    async def executor(req: SubagentExecutionRequest) -> SubagentExecutionResult:
        await asyncio.sleep(10)
        return SubagentExecutionResult(status=SubagentRunStatus.COMPLETED, output=req.task)

    created = await runtime.spawn(
        SpawnSubagentRequest(
            user_id="u2",
            requester_session_key="agent:main:user:u2:main",
            controller_session_key="agent:main:user:u2:main",
            task="long task",
            depth=1,
        ),
        executor=executor,
    )

    await asyncio.sleep(0.05)
    killed_count = await runtime.kill_run("u2", created.run_id, reason="killed", cascade=True)
    assert killed_count >= 1

    await asyncio.sleep(0.05)
    record = await runtime.get_run("u2", created.run_id)
    assert record is not None
    assert record.status == SubagentRunStatus.KILLED

    await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_steer_restarts_run(tmp_path: Path):
    runtime = SubagentRuntimeManager(workspace_path=str(tmp_path))
    await runtime.start()

    async def executor(req: SubagentExecutionRequest) -> SubagentExecutionResult:
        await asyncio.sleep(0.15)
        return SubagentExecutionResult(
            status=SubagentRunStatus.COMPLETED,
            output=f"exec:{req.task}",
        )

    created = await runtime.spawn(
        SpawnSubagentRequest(
            user_id="u3",
            requester_session_key="agent:main:user:u3:main",
            controller_session_key="agent:main:user:u3:main",
            task="draft report",
            depth=1,
        ),
        executor=executor,
    )
    await asyncio.sleep(0.03)

    replaced = await runtime.steer_run(
        user_id="u3",
        controller_session_key="agent:main:user:u3:main",
        run_id=created.run_id,
        message="focus on SLA section",
    )
    assert replaced is not None
    assert replaced.run_id != created.run_id

    await asyncio.sleep(0.30)
    old_record = await runtime.get_run("u3", created.run_id)
    new_record = await runtime.get_run("u3", replaced.run_id)
    assert old_record is not None
    assert new_record is not None
    assert old_record.status == SubagentRunStatus.KILLED
    assert new_record.status == SubagentRunStatus.COMPLETED
    assert "focus on SLA section" in (new_record.output or "")

    await runtime.stop()


@pytest.mark.asyncio
async def test_sessions_tools_use_runtime(tmp_path: Path):
    workspace_path = str(tmp_path / "workspace")
    session_manager = SessionManager(workspace_path=workspace_path, user_id="user-tool")
    runtime = SubagentRuntimeManager(workspace_path=workspace_path)
    await runtime.start()

    async def executor(req: SubagentExecutionRequest) -> SubagentExecutionResult:
        await asyncio.sleep(0.05)
        return SubagentExecutionResult(
            status=SubagentRunStatus.COMPLETED,
            output=f"tool:{req.task}",
        )

    deps = SkillDeps(
        session_key="agent:main:user:user-tool:main",
        session_manager=session_manager,
        extra={
            "run_id": "parent-run-1",
            "subagent_depth": 0,
            "subagent_runtime": runtime,
            "subagent_executor": executor,
        },
    )
    ctx = _DummyCtx(deps=deps)

    spawn_result = await sessions_spawn_tool(ctx=ctx, prompt="prepare summary")
    assert spawn_result["is_error"] is False
    assert spawn_result["details"]["status"] == "accepted"
    run_id = spawn_result["details"]["run_id"]

    list_result = await subagents_tool(ctx=ctx, action="list")
    assert list_result["is_error"] is False
    assert list_result["details"]["action"] == "list"
    assert list_result["details"]["total"] >= 1

    await asyncio.sleep(0.10)
    record = await runtime.get_run("anonymous", run_id)
    assert record is not None
    assert record.status == SubagentRunStatus.COMPLETED

    await runtime.stop()
