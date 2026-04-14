# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status

from ...auth.models import ANONYMOUS_USER, UserInfo
from ...core.security_guard import encode_if_untrusted
from ...session.context import SessionKey
from ...thread_files.service import ThreadFileService
from ..attachment_links import (
    AttachmentLinkSigner,
    resolve_attachment_link_secret,
    resolve_attachment_link_ttl_seconds,
)
from ..deps_context import APIContext, build_scoped_deps

logger = logging.getLogger(__name__)


def build_provider_config(ctx: APIContext) -> dict[str, Any]:
    if ctx.service_provider_registry:
        return ctx.service_provider_registry.get_all_instance_configs()
    return {}


def init_run(
    ctx: APIContext,
    run_id: str,
    session_key: str,
    message: str,
    timeout_seconds: int,
) -> None:
    ctx.active_runs[run_id] = {
        "status": "running",
        "session_key": session_key,
        "started_at": datetime.now(timezone.utc),
        "message": message,
        "timeout_seconds": timeout_seconds,
    }
    ctx.sse_manager.create_stream(run_id)


def normalize_user_message(message: str) -> str:
    normalized, _ = encode_if_untrusted(message)
    return normalized


def get_run_or_404(ctx: APIContext, run_id: str) -> dict[str, Any]:
    run_info = ctx.active_runs.get(run_id)
    if not run_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run not found: {run_id}",
        )
    return run_info


def abort_run(ctx: APIContext, run_id: str) -> None:
    run_info = get_run_or_404(ctx, run_id)
    run_info["status"] = "aborted"


def _build_thread_file_service(ctx: APIContext, session_key: str, user_info: UserInfo) -> ThreadFileService:
    manager = ctx.session_manager_router.for_user(user_info.user_id)
    parsed = SessionKey.from_string(session_key)
    thread_id = parsed.thread_id or "main"
    return ThreadFileService(
        workspace_path=str(manager.workspace_path),
        user_id=user_info.user_id,
        thread_id=thread_id,
    )


async def execute_agent_run(
    ctx: APIContext,
    run_id: str,
    session_key: str,
    message: str,
    timeout_seconds: int,
    user_info: Optional[UserInfo] = None,
    request_cookies: Optional[dict[str, str]] = None,
    provider_config: Optional[dict[str, Any]] = None,
    request_context: Optional[dict[str, Any]] = None,
    attachment_link_secret: Optional[str] = None,
    attachment_link_ttl_seconds: Optional[int] = None,
) -> None:
    _user_info = user_info or ANONYMOUS_USER
    encountered_error = False
    final_error_message = ""
    final_answer_committed = False

    try:
        target_agent_id = SessionKey.from_string(session_key).agent_id or "main"
        runner = None
        if ctx.agent_runners:
            runner = ctx.agent_runners.get(target_agent_id) or ctx.agent_runners.get("main")
        if runner is None:
            runner = ctx.agent_runner

        if not runner:
            raise RuntimeError(
                "AgentRunner not configured. Ensure LLM provider is properly configured in xuanwu.json",
            )

        deps = build_scoped_deps(
            ctx,
            _user_info,
            session_key,
            request_cookies=request_cookies,
            provider_config=provider_config,
            extra={
                "agent_id": target_agent_id,
                "run_id": run_id,
                "context": request_context or {},
                "attachment_context": await thread_files.build_prompt_context_bundle(),
                "attachment_batch_id": runtime_batch.batch_id,
                "attachment_root": str(runtime_batch.root),
                "attachment_uploads_dir": str(runtime_batch.uploads_dir),
                "attachment_outputs_dir": str(runtime_batch.outputs_dir),
                "attachment_workspace_dir": str(runtime_batch.workspace_dir),
            },
        )
        deps.extra["user_work_dir"] = deps.extra.get("work_dir")
        deps.extra["work_dir"] = str(runtime_batch.workspace_dir)

        async for event in runner.run(
            session_key=session_key,
            user_message=message,
            deps=deps,
            timeout_seconds=timeout_seconds,
        ):
            if event.type == "lifecycle":
                ctx.sse_manager.push_lifecycle(run_id, event.phase)
            elif event.type == "assistant":
                ctx.sse_manager.push_assistant(run_id, event.content)
            elif event.type == "tool":
                result_str = str(event.content) if event.content else None
                ctx.sse_manager.push_tool(
                    run_id,
                    event.tool,
                    event.phase,
                    result=result_str,
                )
            elif event.type == "error":
                encountered_error = True
                final_error_message = str(event.error or final_error_message or "")
                ctx.sse_manager.push_error(run_id, event.error)
            elif event.type == "thinking":
                ctx.sse_manager.push_thinking(
                    run_id,
                    event.phase,
                    event.content,
                    metadata=event.metadata if event.metadata else None,
                )
            elif event.type == "runtime":
                runtime_state = str((event.metadata or {}).get("state", "") or "").strip().lower()
                if runtime_state == "failed":
                    encountered_error = True
                    final_error_message = str(event.content or final_error_message or "")
                elif runtime_state == "answered" and str(event.content or "").strip() == "Final answer ready.":
                    final_answer_committed = True
                ctx.sse_manager.push_runtime(
                    run_id,
                    str((event.metadata or {}).get("state", "")),
                    event.content,
                    metadata=event.metadata if event.metadata else None,
                )

        if run_id in ctx.active_runs:
            if encountered_error or not final_answer_committed:
                ctx.active_runs[run_id]["status"] = "error"
                ctx.active_runs[run_id]["error"] = (
                    final_error_message or "Run ended without a committed final answer"
                )
            else:
                ctx.active_runs[run_id]["status"] = "completed"
                ctx.active_runs[run_id]["completed_at"] = datetime.now(timezone.utc)

    except asyncio.TimeoutError:
        ctx.sse_manager.push_error(run_id, "Agent execution timed out")
        ctx.sse_manager.push_lifecycle(run_id, "error")
        if run_id in ctx.active_runs:
            ctx.active_runs[run_id]["status"] = "timeout"
            ctx.active_runs[run_id]["error"] = "Execution timed out"

    except Exception as e:
        error_msg = str(e)
        ctx.sse_manager.push_error(run_id, error_msg)
        ctx.sse_manager.push_lifecycle(run_id, "error")
        if run_id in ctx.active_runs:
            ctx.active_runs[run_id]["status"] = "error"
            ctx.active_runs[run_id]["error"] = error_msg

    finally:
        try:
            presented_paths = None
            if deps is not None and isinstance(getattr(deps, "extra", None), dict):
                raw_presented = deps.extra.get("presented_artifacts")
                if isinstance(raw_presented, list):
                    presented_paths = [
                        str(item)
                        for item in raw_presented
                        if isinstance(item, str) and str(item).strip()
                    ]
            artifacts = await thread_files.finalize_runtime_artifacts(
                runtime_batch.batch_id,
                runtime_snapshot,
                presented_relative_paths=presented_paths,
            )
            signer = AttachmentLinkSigner(
                secret_key=attachment_link_secret or resolve_attachment_link_secret(),
                default_ttl_seconds=(
                    attachment_link_ttl_seconds
                    if attachment_link_ttl_seconds is not None
                    else resolve_attachment_link_ttl_seconds()
                ),
            )
            for artifact in artifacts:
                download_url, expires_at = signer.build_signed_download_url(
                    session_key=session_key,
                    entry_id=artifact.artifact_id,
                )
                ctx.sse_manager.push_artifact(
                    run_id,
                    artifact_id=artifact.artifact_id,
                    name=artifact.name,
                    relative_path=artifact.relative_path,
                    download_url=download_url,
                    expires_at=expires_at,
                )
        except Exception as exc:
            logger.warning("Failed to finalize runtime artifacts for %s: %s", run_id, exc)
        ctx.sse_manager.close_stream(run_id)

