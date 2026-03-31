# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.xuanwu.heartbeat.models import (
    HeartbeatJobDefinition,
    HeartbeatJobType,
    HeartbeatTargetDescriptor,
    HeartbeatTargetType,
)
from app.xuanwu.heartbeat.runtime import HeartbeatRuntime, HeartbeatRuntimeContext
from app.xuanwu.heartbeat.store import HeartbeatStateStore


@dataclass
class _FakeRuntimeExecutorResult:
    status: str = "healthy"
    result_summary: str = "HEARTBEAT_OK"
    should_notify: bool = False
    context_payload: dict = field(default_factory=dict)
    error: str = ""


class _FakeAgentExecutor:
    async def execute(self, job: HeartbeatJobDefinition) -> _FakeRuntimeExecutorResult:
        return _FakeRuntimeExecutorResult(
            context_payload={"job_id": job.job_id, "job_type": job.job_type.value}
        )


class _FakeChannelExecutor:
    async def execute(self, job: HeartbeatJobDefinition) -> _FakeRuntimeExecutorResult:
        return _FakeRuntimeExecutorResult(
            status="healthy",
            result_summary="channel_ok",
            context_payload={"job_id": job.job_id, "job_type": job.job_type.value},
        )


@dataclass
class _FakeHeartbeatRuntimeContext:
    store: HeartbeatStateStore
    emitted_event_types: list[str] = field(default_factory=list)

    def emit_event(self, event) -> None:
        self.emitted_event_types.append(event.event_type.value)


@pytest.mark.asyncio
async def test_runtime_executes_due_jobs_and_updates_next_run(tmp_path: Path) -> None:
    context = _FakeHeartbeatRuntimeContext(store=HeartbeatStateStore(str(tmp_path)))
    runtime = HeartbeatRuntime(
        HeartbeatRuntimeContext(
            store=context.store,
            agent_executor=_FakeAgentExecutor(),
            channel_executor=_FakeChannelExecutor(),
            emit_event=context.emit_event,
        )
    )
    runtime.register_job(
        HeartbeatJobDefinition(
            job_id="hb-agent-main",
            job_type=HeartbeatJobType.AGENT_TURN,
            owner_user_id="admin",
            every_seconds=60,
        )
    )

    await runtime.run_once()

    snapshot = runtime.get_job_state("hb-agent-main")
    assert snapshot is not None
    assert snapshot.last_run_at is not None
    assert snapshot.next_run_at is not None


@pytest.mark.asyncio
async def test_runtime_emits_heartbeat_events(tmp_path: Path) -> None:
    context = _FakeHeartbeatRuntimeContext(store=HeartbeatStateStore(str(tmp_path)))
    runtime = HeartbeatRuntime(
        HeartbeatRuntimeContext(
            store=context.store,
            agent_executor=_FakeAgentExecutor(),
            channel_executor=_FakeChannelExecutor(),
            emit_event=context.emit_event,
        )
    )
    runtime.register_job(
        HeartbeatJobDefinition(
            job_id="hb-agent-main",
            job_type=HeartbeatJobType.AGENT_TURN,
            owner_user_id="admin",
            every_seconds=60,
        )
    )

    await runtime.run_once()

    assert context.emitted_event_types
    assert "heartbeat.agent.started" in context.emitted_event_types
    assert "heartbeat.agent.completed" in context.emitted_event_types


@pytest.mark.asyncio
async def test_runtime_persists_target_resolution(tmp_path: Path) -> None:
    context = _FakeHeartbeatRuntimeContext(store=HeartbeatStateStore(str(tmp_path)))
    runtime = HeartbeatRuntime(
        HeartbeatRuntimeContext(
            store=context.store,
            agent_executor=_FakeAgentExecutor(),
            channel_executor=_FakeChannelExecutor(),
            emit_event=context.emit_event,
        )
    )
    runtime.register_job(
        HeartbeatJobDefinition(
            job_id="hb-agent-targeted",
            job_type=HeartbeatJobType.AGENT_TURN,
            owner_user_id="admin",
            every_seconds=60,
            target=HeartbeatTargetDescriptor(
                type=HeartbeatTargetType.GROUP_CHAT,
                user_id="admin",
                channel="feishu",
                account_id="conn-1",
                peer_id="chat-1",
            ),
        )
    )

    await runtime.run_once()

    snapshot = runtime.get_job_state("hb-agent-targeted")
    assert snapshot is not None
    assert snapshot.last_target_resolution["type"] == "group_chat"
    assert snapshot.last_target_resolution["delivery_mode"] == "summary_only"


@pytest.mark.asyncio
async def test_runtime_skips_jobs_outside_active_hours(tmp_path: Path) -> None:
    context = _FakeHeartbeatRuntimeContext(store=HeartbeatStateStore(str(tmp_path)))
    runtime = HeartbeatRuntime(
        HeartbeatRuntimeContext(
            store=context.store,
            agent_executor=_FakeAgentExecutor(),
            channel_executor=_FakeChannelExecutor(),
            emit_event=context.emit_event,
        )
    )
    runtime.register_job(
        HeartbeatJobDefinition(
            job_id="hb-agent-scheduled",
            job_type=HeartbeatJobType.AGENT_TURN,
            owner_user_id="admin",
            every_seconds=60,
            active_hours_timezone="UTC",
            active_hours_start="23:59",
            active_hours_end="23:59",
        )
    )

    await runtime.run_once()

    assert runtime.get_job_state("hb-agent-scheduled") is None


@pytest.mark.asyncio
async def test_runtime_appends_events_even_without_bridge_callback(tmp_path: Path) -> None:
    store = HeartbeatStateStore(str(tmp_path))
    runtime = HeartbeatRuntime(
        HeartbeatRuntimeContext(
            store=store,
            agent_executor=_FakeAgentExecutor(),
            channel_executor=_FakeChannelExecutor(),
            emit_event=None,
        )
    )
    runtime.register_job(
        HeartbeatJobDefinition(
            job_id="hb-agent-store-only",
            job_type=HeartbeatJobType.AGENT_TURN,
            owner_user_id="admin",
            every_seconds=60,
        )
    )

    await runtime.run_once()

    events = store.load_events("admin")
    assert [event.event_type.value for event in events] == [
        "heartbeat.agent.started",
        "heartbeat.agent.completed",
    ]
