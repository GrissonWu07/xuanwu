# -*- coding: utf-8 -*-
"""Artifact presentation tool.

`present_files` marks generated files as final thread artifacts. The run
finalizer will prioritize these explicit paths instead of auto-exporting every
new runtime file.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from app.xuanwu.tools.base import ToolResult

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from app.xuanwu.core.deps import SkillDeps


def _resolve_attachment_root(ctx: "RunContext[SkillDeps]") -> Path:
    deps = ctx.deps
    extra = deps.extra if isinstance(deps.extra, dict) else {}
    root_value = str(extra.get("attachment_root") or "").strip()
    if not root_value:
        raise ValueError("attachment_root is not available in runtime context")
    return Path(root_value).resolve()


def _resolve_work_dir(ctx: "RunContext[SkillDeps]", attachment_root: Path) -> Path:
    deps = ctx.deps
    extra = deps.extra if isinstance(deps.extra, dict) else {}
    work_dir_value = str(extra.get("work_dir") or "").strip()
    if not work_dir_value:
        return attachment_root
    return Path(work_dir_value).resolve()


def _resolve_batch_id(ctx: "RunContext[SkillDeps]", attachment_root: Path) -> str:
    deps = ctx.deps
    extra = deps.extra if isinstance(deps.extra, dict) else {}
    batch_id = str(extra.get("attachment_batch_id") or "").strip()
    if batch_id:
        return batch_id
    fallback = str(attachment_root.name or "").strip()
    if fallback:
        return fallback
    raise ValueError("attachment_batch_id is not available in runtime context")


def _normalize_presented_path(
    *,
    raw_path: str,
    attachment_root: Path,
    work_dir: Path,
) -> str:
    text = str(raw_path or "").strip()
    if not text:
        raise ValueError("file path must not be empty")

    candidate = Path(text)
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (work_dir / candidate).resolve()
    )

    try:
        relative = resolved.relative_to(attachment_root)
    except ValueError as exc:
        raise ValueError(f"path must stay inside attachment root: {text}") from exc

    if not resolved.is_file():
        raise ValueError(f"path is not a file: {text}")

    return str(relative).replace("\\", "/")


async def present_files_tool(
    ctx: "RunContext[SkillDeps]",
    file_paths: list[str],
) -> dict:
    """Mark generated files as final artifacts for this run.

    Args:
        ctx: PydanticAI `RunContext` dependency injection payload.
        file_paths: File paths to mark as exported artifacts.

    Returns:
        Serialized `ToolResult` dictionary.
    """
    if not file_paths:
        return ToolResult.error("file_paths must not be empty").to_dict()

    try:
        attachment_root = _resolve_attachment_root(ctx)
        work_dir = _resolve_work_dir(ctx, attachment_root)
        batch_id = _resolve_batch_id(ctx, attachment_root)
    except ValueError as e:
        return ToolResult.error(str(e)).to_dict()

    normalized: list[str] = []
    seen: set[str] = set()
    for item in file_paths:
        try:
            relative_path = _normalize_presented_path(
                raw_path=item,
                attachment_root=attachment_root,
                work_dir=work_dir,
            )
        except ValueError as e:
            return ToolResult.error(str(e), details={"path": item}).to_dict()
        batched_relative_path = relative_path
        if not batched_relative_path.startswith(f"{batch_id}/"):
            batched_relative_path = f"{batch_id}/{batched_relative_path.lstrip('/')}"
        batched_relative_path = batched_relative_path.replace("\\", "/")
        if batched_relative_path not in seen:
            seen.add(batched_relative_path)
            normalized.append(batched_relative_path)

    deps = ctx.deps
    extra = deps.extra if isinstance(deps.extra, dict) else {}
    existing = extra.get("presented_artifacts")
    if isinstance(existing, list):
        merged = [str(item) for item in existing if isinstance(item, str)]
    else:
        merged = []
    for relative in normalized:
        if relative not in merged:
            merged.append(relative)
    extra["presented_artifacts"] = merged
    deps.extra = extra

    return ToolResult.text(
        "Presented files registered",
        details={"presented_relative_paths": normalized},
    ).to_dict()
