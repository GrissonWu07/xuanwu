# -*- coding: utf-8 -*-
"""Helpers for building executable subagent callbacks."""

from __future__ import annotations

from typing import Any, Optional

from app.xuanwu.auth.models import UserInfo
from app.xuanwu.core.deps import SkillDeps
from app.xuanwu.subagents.models import (
    SubagentExecutionRequest,
    SubagentExecutionResult,
    SubagentRunStatus,
)


def create_subagent_executor(
    *,
    runner: Any,
    session_manager: Any,
    user_info: UserInfo,
    request_cookies: Optional[dict[str, str]] = None,
    provider_config: Optional[dict[str, Any]] = None,
    base_extra: Optional[dict[str, Any]] = None,
    subagent_runtime: Optional[Any] = None,
) -> Any:
    """Create an async callback that executes a child run using AgentRunner."""
    cookies = dict(request_cookies or {})
    inherited_extra = dict(base_extra or {})
    provider_payload = dict(provider_config or {})

    async def _execute(req: SubagentExecutionRequest) -> SubagentExecutionResult:
        child_extra = {
            "_service_provider_registry": inherited_extra.get("_service_provider_registry"),
            "available_providers": inherited_extra.get("available_providers", {}),
            "provider_instances": inherited_extra.get("provider_instances", {}),
            "provider_config": provider_payload,
            "tools_snapshot": inherited_extra.get("tools_snapshot", []),
            "skills_snapshot": inherited_extra.get("skills_snapshot", []),
            "md_skills_snapshot": inherited_extra.get("md_skills_snapshot", []),
            "run_id": req.run_id,
            "subagent_depth": req.depth,
            "subagent_runtime": subagent_runtime,
            "subagent_parent_run_id": req.parent_run_id,
            "subagent_parent_session_key": req.requester_session_key,
        }
        if req.context_pack.summary:
            child_extra["subagent_context_summary"] = req.context_pack.summary
        if req.context_pack.transcript_tail:
            child_extra["subagent_context_tail"] = list(req.context_pack.transcript_tail)
        if req.metadata:
            child_extra["subagent_metadata"] = dict(req.metadata)

        child_deps = SkillDeps(
            user_info=UserInfo(
                user_id=user_info.user_id,
                display_name=user_info.display_name,
                tenant_id=user_info.tenant_id,
                roles=list(user_info.roles),
                raw_token=user_info.raw_token,
                provider_subject=user_info.provider_subject,
                extra=dict(user_info.extra),
            ),
            session_key=req.child_session_key,
            session_manager=session_manager,
            cookies=cookies,
            extra=child_extra,
        )

        child_user_message = _build_child_user_message(req)
        text_chunks: list[str] = []
        error_text = ""
        async for event in runner.run(
            session_key=req.child_session_key,
            user_message=child_user_message,
            deps=child_deps,
            timeout_seconds=req.timeout_seconds if req.timeout_seconds > 0 else 600,
            _emit_lifecycle_bounds=False,
        ):
            if event.type == "assistant" and event.content:
                text_chunks.append(event.content)
            elif event.type == "error":
                error_text = event.error or "subagent execution failed"
                break

        if error_text:
            return SubagentExecutionResult(
                status=SubagentRunStatus.FAILED,
                output="",
                error=error_text,
            )
        return SubagentExecutionResult(
            status=SubagentRunStatus.COMPLETED,
            output="".join(text_chunks).strip(),
            metadata={
                "summary_chars": req.context_pack.summary_chars,
                "tail_messages": req.context_pack.tail_messages,
                "tail_chars": req.context_pack.tail_chars,
                "truncated": req.context_pack.truncated,
            },
        )

    return _execute


def _build_child_user_message(req: SubagentExecutionRequest) -> str:
    blocks: list[str] = []
    if req.context_pack.summary:
        blocks.append("[Parent Summary]\n" + req.context_pack.summary)
    if req.context_pack.transcript_tail:
        blocks.append("[Parent Transcript Tail]\n" + "\n".join(req.context_pack.transcript_tail))
    blocks.append("[Task]\n" + req.task)
    return "\n\n".join(blocks)
