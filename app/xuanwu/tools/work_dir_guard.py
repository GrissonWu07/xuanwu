# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from app.xuanwu.core.security_guard import (
    ensure_user_work_dir,
    resolve_path_in_user_work_dir,
)

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from app.xuanwu.core.deps import SkillDeps


def get_user_work_dir(ctx: "RunContext[SkillDeps]") -> Path:
    deps = ctx.deps
    session_manager = getattr(deps, "session_manager", None)
    workspace_path = getattr(session_manager, "workspace_path", Path("."))
    user_id = getattr(getattr(deps, "user_info", None), "user_id", "") or "default"
    return ensure_user_work_dir(workspace_path, user_id)


def _get_workspace_and_user(ctx: "RunContext[SkillDeps]") -> tuple[Path, str]:
    deps = ctx.deps
    session_manager = getattr(deps, "session_manager", None)
    workspace_path = Path(getattr(session_manager, "workspace_path", Path(".")))
    user_id = getattr(getattr(deps, "user_info", None), "user_id", "") or "default"
    return workspace_path, user_id


def _resolve_override_work_dir(ctx: "RunContext[SkillDeps]") -> Optional[Path]:
    deps = ctx.deps
    extra = deps.extra if isinstance(deps.extra, dict) else {}
    override_raw = str(extra.get("work_dir") or "").strip()
    if not override_raw:
        return None

    workspace_path, user_id = _get_workspace_and_user(ctx)
    return resolve_path_in_user_work_dir(workspace_path, user_id, override_raw)


def resolve_file_path(ctx: "RunContext[SkillDeps]", file_path: str) -> Path:
    workspace_path, user_id = _get_workspace_and_user(ctx)
    user_work_dir = ensure_user_work_dir(workspace_path, user_id)
    candidate = Path(file_path)

    if candidate.is_absolute():
        return resolve_path_in_user_work_dir(workspace_path, user_id, file_path)

    base_dir = _resolve_override_work_dir(ctx) or user_work_dir
    resolved = (base_dir / candidate).resolve()
    try:
        resolved.relative_to(user_work_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"path must be inside user work_dir: {user_work_dir}") from exc
    return resolved


def resolve_cwd(ctx: "RunContext[SkillDeps]", cwd: Optional[str]) -> Path:
    workspace_path, user_id = _get_workspace_and_user(ctx)
    user_work_dir = ensure_user_work_dir(workspace_path, user_id)
    if not cwd:
        return _resolve_override_work_dir(ctx) or user_work_dir

    candidate = Path(cwd)
    if candidate.is_absolute():
        return resolve_path_in_user_work_dir(workspace_path, user_id, cwd)

    base_dir = _resolve_override_work_dir(ctx) or user_work_dir
    resolved = (base_dir / candidate).resolve()
    try:
        resolved.relative_to(user_work_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"path must be inside user work_dir: {user_work_dir}") from exc
    return resolved
