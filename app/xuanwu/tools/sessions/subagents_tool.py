"""Management tool for runtime-backed subagents."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from app.xuanwu.subagents.models import SubagentRunStatus
from app.xuanwu.tools.base import ToolResult

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from app.xuanwu.core.deps import SkillDeps


async def subagents_tool(
    ctx: "RunContext[SkillDeps]",
    action: str,
    subagent_id: Optional[str] = None,
    message: Optional[str] = None,
) -> dict:
    """List, kill, or steer running subagents."""
    deps = ctx.deps
    extra = deps.extra if isinstance(deps.extra, dict) else {}
    runtime = extra.get("subagent_runtime")
    user_info = getattr(deps, "user_info", None)
    user_id = str(getattr(user_info, "user_id", "default") or "default")
    controller_session_key = str(getattr(deps, "session_key", "") or "")
    normalized_action = (action or "").strip().lower()

    if runtime is None:
        return ToolResult.text(
            "(subagent runtime unavailable)",
            details={"action": normalized_action or "list", "subagents": [], "total": 0},
        ).to_dict()

    if normalized_action == "list":
        try:
            view = await runtime.list_runs_view(
                user_id=user_id,
                controller_session_key=controller_session_key,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.error(f"failed to list subagents: {exc}").to_dict()
        active = [_to_view_item(item) for item in view["active"]]
        recent = [_to_view_item(item) for item in view["recent"]]
        lines = ["active subagents:"]
        if active:
            lines.extend(
                [
                    f"{idx + 1}. {item['subagent_id']} ({item['run_id']}) {item['status']}"
                    for idx, item in enumerate(active)
                ]
            )
        else:
            lines.append("(none)")
        lines.append("")
        lines.append("recent subagents:")
        if recent:
            lines.extend(
                [
                    f"{idx + 1}. {item['subagent_id']} ({item['run_id']}) {item['status']}"
                    for idx, item in enumerate(recent)
                ]
            )
        else:
            lines.append("(none)")
        return ToolResult.text(
            "\n".join(lines),
            details={
                "action": "list",
                "total": view["total"],
                "active": active,
                "recent": recent,
                "active_batch_id": str(view.get("active_batch_id", "")),
                "queue_depth": int(view.get("queue_depth", 0) or 0),
            },
        ).to_dict()

    if normalized_action == "kill":
        target = (subagent_id or "").strip()
        if not target:
            return ToolResult.error("subagent_id is required for kill").to_dict()
        if target in {"all", "*"}:
            killed = await runtime.kill_all_for_controller(user_id, controller_session_key)
            return ToolResult.text(
                f"killed {killed} subagent(s)",
                details={"action": "kill", "target": "all", "killed": killed},
            ).to_dict()
        resolved = await runtime.resolve_controlled_target(
            user_id=user_id,
            controller_session_key=controller_session_key,
            target=target,
        )
        if resolved is None:
            return ToolResult.error(f"unknown subagent target: {target}").to_dict()
        killed = await runtime.kill_run(user_id, resolved.run_id, reason="killed", cascade=True)
        return ToolResult.text(
            f"Subagent {resolved.subagent_id} terminated",
            details={
                "action": "kill",
                "target": target,
                "run_id": resolved.run_id,
                "subagent_id": resolved.subagent_id,
                "killed": killed,
                "status": SubagentRunStatus.KILLED.value if killed > 0 else resolved.status.value,
            },
        ).to_dict()

    if normalized_action == "steer":
        target = (subagent_id or "").strip()
        steer_message = (message or "").strip()
        if not target:
            return ToolResult.error("subagent_id is required for steer").to_dict()
        if not steer_message:
            return ToolResult.error("message is required for steer").to_dict()
        resolved = await runtime.resolve_controlled_target(
            user_id=user_id,
            controller_session_key=controller_session_key,
            target=target,
        )
        if resolved is None:
            return ToolResult.error(f"unknown subagent target: {target}").to_dict()
        try:
            replacement = await runtime.steer_run(
                user_id=user_id,
                controller_session_key=controller_session_key,
                run_id=resolved.run_id,
                message=steer_message,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.error(f"failed to steer subagent: {exc}").to_dict()
        if replacement is None:
            return ToolResult.error(f"subagent not steerable: {target}").to_dict()
        return ToolResult.text(
            f"Steer accepted for {resolved.subagent_id}",
            details={
                "action": "steer",
                "target": target,
                "run_id": replacement.run_id,
                "subagent_id": replacement.subagent_id,
                "replaces_run_id": resolved.run_id,
                "status": "accepted",
            },
        ).to_dict()

    return ToolResult.error(f"unknown action: {normalized_action}").to_dict()


def _to_view_item(record) -> dict:
    return {
        "run_id": record.run_id,
        "subagent_id": record.subagent_id,
        "status": record.status.value,
        "task": record.task,
        "child_session_key": record.child_session_key,
        "batch_id": str((record.metadata or {}).get("batch_id", "")),
        "queue_state": str((record.metadata or {}).get("queue_state", "")),
        "spawn_outcome": str((record.metadata or {}).get("spawn_outcome", "")),
        "stalled": bool((record.metadata or {}).get("stalled", False)),
        "depth": record.depth,
        "created_at": record.created_at.isoformat(),
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "ended_at": record.ended_at.isoformat() if record.ended_at else None,
    }
