"""`sessions_spawn` tool backed by subagent runtime manager."""

from __future__ import annotations

import hashlib
from typing import Optional, TYPE_CHECKING

from app.xuanwu.session.context import TranscriptEntry
from app.xuanwu.subagents.models import SpawnSubagentRequest, SubagentContextPack
from app.xuanwu.subagents.runtime import SubagentSpawnPolicyError
from app.xuanwu.tools.base import ToolResult

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from app.xuanwu.core.deps import SkillDeps


async def sessions_spawn_tool(
    ctx: "RunContext[SkillDeps]",
    prompt: str,
    tools: Optional[str] = None,
) -> dict:
    """Spawn an isolated background subagent run."""
    normalized_prompt = (prompt or "").strip()
    if not normalized_prompt:
        return ToolResult.error("prompt is required").to_dict()

    deps = ctx.deps
    extra = deps.extra if isinstance(deps.extra, dict) else {}
    runtime = extra.get("subagent_runtime")
    executor = extra.get("subagent_executor")
    user_info = getattr(deps, "user_info", None)
    user_id = str(getattr(user_info, "user_id", "default") or "default")
    controller_session_key = str(getattr(deps, "session_key", "") or "")
    if not controller_session_key:
        controller_session_key = f"agent:main:user:{user_id}:main"

    session_manager = getattr(deps, "session_manager", None)
    context_pack = await _build_context_pack(
        prompt=normalized_prompt,
        session_manager=session_manager,
        session_key=controller_session_key,
    )
    depth = int(extra.get("subagent_depth", 0) or 0) + 1
    timeout_seconds = int(extra.get("subagent_timeout_seconds", 0) or 0)

    if runtime is None or not callable(executor):
        return ToolResult.error(
            "Subagent runtime is unavailable in this context.",
            details={
                "status": "runtime_unavailable",
                "prompt": normalized_prompt,
                "tools": tools,
                "runtime_available": False,
            },
        ).to_dict()

    idempotency_key = hashlib.sha1(
        f"{controller_session_key}\n{normalized_prompt}".encode("utf-8")
    ).hexdigest()

    try:
        created = await runtime.spawn(
            SpawnSubagentRequest(
                user_id=user_id,
                requester_session_key=controller_session_key,
                controller_session_key=controller_session_key,
                parent_run_id=str(extra.get("run_id", "") or ""),
                task=normalized_prompt,
                depth=depth,
                timeout_seconds=timeout_seconds,
                metadata={
                    "requested_tools": str(tools or ""),
                    "request_channel": str(getattr(deps, "channel", "") or ""),
                },
                context_pack=context_pack,
                idempotency_key=idempotency_key,
                single_active_batch=True,
                queue_if_busy=True,
            ),
            executor=executor,
        )
    except SubagentSpawnPolicyError as exc:
        return ToolResult.error(
            exc.message,
            details={
                "status": exc.outcome,
                "prompt": normalized_prompt,
                "depth": depth,
            },
        ).to_dict()
    except Exception as exc:  # noqa: BLE001
        return ToolResult.error(
            f"failed to spawn subagent: {exc}",
            details={
                "status": "error",
                "prompt": normalized_prompt,
                "depth": depth,
            },
        ).to_dict()

    spawn_outcome = str((created.metadata or {}).get("spawn_outcome", "accepted"))
    if spawn_outcome == "continue_current_batch":
        message = f"Continue current subagent batch: {created.subagent_id}"
    elif spawn_outcome == "queued_next_request":
        message = f"Subagent queued: {created.subagent_id}"
    elif spawn_outcome == "accepted_from_queue":
        message = f"Subagent resumed from queue: {created.subagent_id}"
    else:
        message = f"Subagent accepted: {created.subagent_id}"

    return ToolResult.text(
        message,
        details={
            "status": spawn_outcome,
            "run_id": created.run_id,
            "subagent_id": created.subagent_id,
            "child_session_key": created.child_session_key,
            "session_key": created.child_session_key,
            "depth": created.depth,
            "timeout_seconds": created.timeout_seconds,
            "batch_id": str((created.metadata or {}).get("batch_id", "")),
            "queue_state": str((created.metadata or {}).get("queue_state", "")),
            "tools": tools,
            "context_pack": context_pack.to_dict(),
        },
    ).to_dict()


async def _build_context_pack(
    *,
    prompt: str,
    session_manager: Optional[object],
    session_key: str,
) -> SubagentContextPack:
    """Build bounded inherited context for child run."""
    summary_budget = 2000
    tail_message_budget = 20
    tail_chars_budget = 12000
    combined_budget = 16000

    summary = prompt[:summary_budget]
    truncated = len(prompt) > summary_budget
    tail_lines: list[str] = []

    if session_manager is not None:
        try:
            transcript = await session_manager.load_transcript(session_key)
        except Exception:
            transcript = []
        tail_entries = transcript[-tail_message_budget:]
        for entry in tail_entries:
            if isinstance(entry, TranscriptEntry):
                role = str(entry.role or "unknown")
                content = str(entry.content or "")
            else:
                role = str(getattr(entry, "role", "unknown"))
                content = str(getattr(entry, "content", ""))
            if content:
                tail_lines.append(f"{role}: {content}")

    tail_text = "\n".join(tail_lines)
    if len(tail_text) > tail_chars_budget:
        tail_text = tail_text[-tail_chars_budget:]
        truncated = True
    tail_lines = [line for line in tail_text.splitlines() if line.strip()]

    combined = len(summary) + len(tail_text)
    if combined > combined_budget:
        allowed_tail_chars = max(0, combined_budget - len(summary))
        if len(tail_text) > allowed_tail_chars:
            tail_text = tail_text[-allowed_tail_chars:]
            tail_lines = [line for line in tail_text.splitlines() if line.strip()]
            truncated = True

    return SubagentContextPack(
        summary=summary,
        transcript_tail=tail_lines,
        summary_chars=len(summary),
        tail_messages=len(tail_lines),
        tail_chars=len(tail_text),
        truncated=truncated,
    )
