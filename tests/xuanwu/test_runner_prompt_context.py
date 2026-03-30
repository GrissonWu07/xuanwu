# -*- coding: utf-8 -*-

from __future__ import annotations

from app.xuanwu.agent.runner_prompt_context import (
    build_system_prompt,
    collect_attachment_runtime,
)
from app.xuanwu.auth.models import UserInfo
from app.xuanwu.core.deps import SkillDeps


class _PromptBuilderWithRuntime:
    def __init__(self) -> None:
        self.last_kwargs = None

    def build(
        self,
        session=None,
        skills=None,
        tools=None,
        md_skills=None,
        target_md_skill=None,
        user_info=None,
        provider_contexts=None,
        attachment_context=None,
        attachment_runtime=None,
    ) -> str:
        self.last_kwargs = {
            "session": session,
            "skills": skills,
            "tools": tools,
            "md_skills": md_skills,
            "target_md_skill": target_md_skill,
            "user_info": user_info,
            "provider_contexts": provider_contexts,
            "attachment_context": attachment_context,
            "attachment_runtime": attachment_runtime,
        }
        return "ok"


class _PromptBuilderWithoutRuntime:
    def __init__(self) -> None:
        self.last_kwargs = None

    def build(
        self,
        session=None,
        skills=None,
        tools=None,
        md_skills=None,
        target_md_skill=None,
        user_info=None,
        provider_contexts=None,
        attachment_context=None,
    ) -> str:
        self.last_kwargs = {
            "session": session,
            "skills": skills,
            "tools": tools,
            "md_skills": md_skills,
            "target_md_skill": target_md_skill,
            "user_info": user_info,
            "provider_contexts": provider_contexts,
            "attachment_context": attachment_context,
        }
        return "ok"


def _build_deps() -> SkillDeps:
    return SkillDeps(
        user_info=UserInfo(user_id="alice"),
        extra={
            "attachment_context": {
                "uploads": [],
                "artifacts": [],
            },
            "attachment_batch_id": "1711612555",
            "attachment_root": "/tmp/attachments/thread-1/1711612555",
            "attachment_uploads_dir": "/tmp/attachments/thread-1/1711612555/uploads",
            "attachment_workspace_dir": "/tmp/attachments/thread-1/1711612555/workspace",
            "attachment_outputs_dir": "/tmp/attachments/thread-1/1711612555/outputs",
        },
    )


def test_collect_attachment_runtime_returns_expected_fields():
    deps = _build_deps()
    runtime = collect_attachment_runtime(deps)
    assert runtime is not None
    assert runtime["attachment_batch_id"] == "1711612555"
    assert runtime["attachment_outputs_dir"].endswith("/outputs")


def test_build_system_prompt_injects_attachment_runtime_when_supported():
    prompt_builder = _PromptBuilderWithRuntime()
    deps = _build_deps()
    result = build_system_prompt(prompt_builder, session=object(), deps=deps, agent=None)

    assert result == "ok"
    assert prompt_builder.last_kwargs is not None
    assert prompt_builder.last_kwargs["attachment_runtime"]["attachment_batch_id"] == "1711612555"


def test_build_system_prompt_keeps_backward_compat_for_builders_without_runtime():
    prompt_builder = _PromptBuilderWithoutRuntime()
    deps = _build_deps()
    result = build_system_prompt(prompt_builder, session=object(), deps=deps, agent=None)

    assert result == "ok"
    assert prompt_builder.last_kwargs is not None
    assert "attachment_runtime" not in prompt_builder.last_kwargs
