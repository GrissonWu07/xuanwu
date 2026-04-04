# -*- coding: utf-8 -*-
"""E2E: unified heartbeat runtime with full app startup."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.xuanwu.api.deps_context import get_api_context
from app.xuanwu.heartbeat.agent_executor import AgentHeartbeatExecutionResult
from app.xuanwu.heartbeat.channel_executor import ChannelHeartbeatExecutionResult
from app.xuanwu.heartbeat.models import (
    HeartbeatJobDefinition,
    HeartbeatJobType,
    HeartbeatTargetDescriptor,
    HeartbeatTargetType,
)
from app.xuanwu.hooks.runtime_builtin import RUNTIME_AUDIT_MODULE


def _create_heartbeat_e2e_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "heartbeat-runtime-e2e.db"
    config_path = tmp_path / "xuanwu.heartbeat-runtime.e2e.json"

    config = {
        "workspace": {
            "path": str((tmp_path / ".xuanwu-e2e").resolve()),
        },
        "providers_root": "./app/xuanwu/providers",
        "skills_root": "./app/xuanwu/skills",
        "channels_root": "./app/xuanwu/channels",
        "database": {
            "type": "sqlite",
            "sqlite": {
                "path": str(db_path.resolve()),
            },
        },
        "auth": {
            "enabled": True,
            "provider": "local",
            "jwt": {
                "secret_key": "heartbeat-e2e-secret",
                "issuer": "atlasclaw-heartbeat-e2e",
                "header_name": "XuanWu-Authenticate",
                "cookie_name": "XuanWu-Authenticate",
                "expires_minutes": 60,
            },
            "local": {
                "enabled": True,
                "default_admin_username": "admin",
                "default_admin_password": "Admin@123",
            },
        },
        "model": {
            "primary": "test-token",
            "fallbacks": [],
            "temperature": 0.2,
            "selection_strategy": "health",
            "tokens": [
                {
                    "id": "test-token",
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "test-key",
                    "api_type": "openai",
                    "priority": 100,
                    "weight": 100,
                }
            ],
        },
        "heartbeat": {
            "enabled": True,
            "runtime": {
                "tick_seconds": 60,
                "max_concurrent_jobs": 4,
            },
            "agent_turn": {"enabled": False},
            "channel_connection": {"enabled": False},
        },
    }

    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setenv("XUANWU_CONFIG", str(config_path.resolve()))

    import app.xuanwu.core.config as config_module
    from app.xuanwu.main import create_app

    old_config_manager = config_module._config_manager
    config_module._config_manager = config_module.ConfigManager(config_path=str(config_path.resolve()))
    app = create_app()
    return app, config_module, old_config_manager


class _FakeAgentExecutor:
    async def execute(self, job: HeartbeatJobDefinition) -> AgentHeartbeatExecutionResult:
        return AgentHeartbeatExecutionResult(
            status="healthy",
            result_summary="HEARTBEAT_OK",
            should_notify=False,
            context_payload={
                "result_summary": "HEARTBEAT_OK",
                "status": "healthy",
                "assistant_message": "HEARTBEAT_OK",
                "metadata": {
                    "run_id": "heartbeat-run-e2e",
                    "session_key": "agent:main:user:admin:web:dm:admin:topic:heartbeat",
                },
            },
        )


class _FakeChannelExecutor:
    async def execute(self, job: HeartbeatJobDefinition) -> ChannelHeartbeatExecutionResult:
        return ChannelHeartbeatExecutionResult(
            status="degraded",
            result_summary="connection_failed",
            should_alert=True,
            consecutive_failures=3,
            error="connection_failed",
            context_payload={
                "result_summary": "connection_failed",
                "status": "degraded",
                "metadata": {
                    "channel_type": "feishu",
                    "connection_id": "conn-e2e",
                },
            },
        )


@pytest.mark.e2e
def test_agent_heartbeat_runtime_records_state_and_bridges_hook_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, config_module, old_config_manager = _create_heartbeat_e2e_app(tmp_path, monkeypatch)

    try:
        with TestClient(app) as client:
            login_resp = client.post(
                "/api/auth/local/login",
                json={"username": "admin", "password": "Admin@123"},
            )
            assert login_resp.status_code == 200
            headers = {"XuanWu-Authenticate": login_resp.json()["token"]}

            ctx = get_api_context()
            assert ctx.heartbeat_runtime is not None
            ctx.heartbeat_runtime.context.agent_executor = _FakeAgentExecutor()

            ctx.heartbeat_runtime.register_job(
                HeartbeatJobDefinition(
                    job_id="hb-agent-e2e",
                    job_type=HeartbeatJobType.AGENT_TURN,
                    owner_user_id="admin",
                    every_seconds=300,
                    target=HeartbeatTargetDescriptor(
                        type=HeartbeatTargetType.USER_CHAT,
                        user_id="admin",
                    ),
                )
            )

            asyncio.run(ctx.heartbeat_runtime.run_once())

            snapshot = ctx.heartbeat_runtime.get_job_state("hb-agent-e2e")
            assert snapshot is not None
            assert snapshot.status == "healthy"

            events_resp = client.get(f"/api/hooks/{RUNTIME_AUDIT_MODULE}/events", headers=headers)
            assert events_resp.status_code == 200
            event_types = {item["event_type"] for item in events_resp.json()}
            assert "heartbeat.agent.started" in event_types
            assert "heartbeat.agent.completed" in event_types
    finally:
        config_module._config_manager = old_config_manager


@pytest.mark.e2e
def test_channel_heartbeat_runtime_emits_degraded_event_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, config_module, old_config_manager = _create_heartbeat_e2e_app(tmp_path, monkeypatch)

    try:
        with TestClient(app) as client:
            login_resp = client.post(
                "/api/auth/local/login",
                json={"username": "admin", "password": "Admin@123"},
            )
            assert login_resp.status_code == 200
            headers = {"XuanWu-Authenticate": login_resp.json()["token"]}

            ctx = get_api_context()
            assert ctx.heartbeat_runtime is not None
            ctx.heartbeat_runtime.context.channel_executor = _FakeChannelExecutor()

            ctx.heartbeat_runtime.register_job(
                HeartbeatJobDefinition(
                    job_id="hb-channel-e2e",
                    job_type=HeartbeatJobType.CHANNEL_CONNECTION,
                    owner_user_id="admin",
                    every_seconds=30,
                    target=HeartbeatTargetDescriptor(
                        type=HeartbeatTargetType.CHANNEL_CONNECTION,
                        user_id="admin",
                        channel="feishu",
                        account_id="conn-e2e",
                    ),
                    metadata={"channel_type": "feishu", "connection_id": "conn-e2e"},
                )
            )

            asyncio.run(ctx.heartbeat_runtime.run_once())

            snapshot = ctx.heartbeat_runtime.get_job_state("hb-channel-e2e")
            assert snapshot is not None
            assert snapshot.status == "degraded"
            assert snapshot.last_target_resolution["account_id"] == "conn-e2e"

            events_resp = client.get(f"/api/hooks/{RUNTIME_AUDIT_MODULE}/events", headers=headers)
            assert events_resp.status_code == 200
            event_types = {item["event_type"] for item in events_resp.json()}
            assert "heartbeat.channel.check_started" in event_types
            assert "heartbeat.channel.degraded" in event_types
    finally:
        config_module._config_manager = old_config_manager
