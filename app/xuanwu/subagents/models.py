# -*- coding: utf-8 -*-
"""Subagent runtime models."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


def utc_now() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class SubagentRunStatus(str, Enum):
    """Lifecycle status of a subagent run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    KILLED = "killed"
    ORPHANED = "orphaned"

    @property
    def is_terminal(self) -> bool:
        return self in {
            SubagentRunStatus.COMPLETED,
            SubagentRunStatus.FAILED,
            SubagentRunStatus.TIMED_OUT,
            SubagentRunStatus.KILLED,
            SubagentRunStatus.ORPHANED,
        }


@dataclass
class SubagentContextPack:
    """Bounded context payload inherited from parent run."""

    summary: str = ""
    transcript_tail: list[str] = field(default_factory=list)
    summary_chars: int = 0
    tail_messages: int = 0
    tail_chars: int = 0
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "transcript_tail": list(self.transcript_tail),
            "summary_chars": self.summary_chars,
            "tail_messages": self.tail_messages,
            "tail_chars": self.tail_chars,
            "truncated": self.truncated,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> "SubagentContextPack":
        payload = data or {}
        return cls(
            summary=str(payload.get("summary", "")),
            transcript_tail=[str(item) for item in payload.get("transcript_tail", []) if item],
            summary_chars=int(payload.get("summary_chars", 0) or 0),
            tail_messages=int(payload.get("tail_messages", 0) or 0),
            tail_chars=int(payload.get("tail_chars", 0) or 0),
            truncated=bool(payload.get("truncated", False)),
        )


@dataclass
class SpawnSubagentRequest:
    """Input payload for scheduling a subagent run."""

    user_id: str
    requester_session_key: str
    controller_session_key: str
    task: str
    depth: int
    timeout_seconds: int = 0
    label: str = ""
    model: str = ""
    parent_run_id: str = ""
    cleanup_policy: str = "keep"
    context_pack: SubagentContextPack = field(default_factory=SubagentContextPack)
    child_session_key: str = ""
    batch_id: str = ""
    idempotency_key: str = ""
    single_active_batch: bool = False
    queue_if_busy: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubagentExecutionRequest:
    """Runtime execution payload consumed by executor callback."""

    run_id: str
    subagent_id: str
    user_id: str
    child_session_key: str
    requester_session_key: str
    controller_session_key: str
    parent_run_id: str
    task: str
    depth: int
    timeout_seconds: int
    context_pack: SubagentContextPack
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubagentExecutionResult:
    """Result payload returned by executor callback."""

    status: SubagentRunStatus
    output: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubagentRunRecord:
    """Persistent run registry record."""

    run_id: str
    subagent_id: str
    user_id: str
    requester_session_key: str
    controller_session_key: str
    child_session_key: str
    task: str
    depth: int
    status: SubagentRunStatus = SubagentRunStatus.PENDING
    created_at: datetime = field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    timeout_seconds: int = 0
    cleanup_policy: str = "keep"
    label: str = ""
    model: str = ""
    parent_run_id: str = ""
    output: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def generate_run_id() -> str:
        return f"subrun_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def generate_subagent_id() -> str:
        return f"sub_{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "subagent_id": self.subagent_id,
            "user_id": self.user_id,
            "requester_session_key": self.requester_session_key,
            "controller_session_key": self.controller_session_key,
            "child_session_key": self.child_session_key,
            "task": self.task,
            "depth": self.depth,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "timeout_seconds": self.timeout_seconds,
            "cleanup_policy": self.cleanup_policy,
            "label": self.label,
            "model": self.model,
            "parent_run_id": self.parent_run_id,
            "output": self.output,
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubagentRunRecord":
        return cls(
            run_id=str(data.get("run_id", "")),
            subagent_id=str(data.get("subagent_id", "")),
            user_id=str(data.get("user_id", "default")),
            requester_session_key=str(data.get("requester_session_key", "")),
            controller_session_key=str(data.get("controller_session_key", "")),
            child_session_key=str(data.get("child_session_key", "")),
            task=str(data.get("task", "")),
            depth=int(data.get("depth", 0) or 0),
            status=SubagentRunStatus(str(data.get("status", SubagentRunStatus.PENDING.value))),
            created_at=datetime.fromisoformat(str(data.get("created_at"))),
            started_at=(
                datetime.fromisoformat(str(data.get("started_at")))
                if data.get("started_at")
                else None
            ),
            ended_at=(
                datetime.fromisoformat(str(data.get("ended_at")))
                if data.get("ended_at")
                else None
            ),
            timeout_seconds=int(data.get("timeout_seconds", 0) or 0),
            cleanup_policy=str(data.get("cleanup_policy", "keep")),
            label=str(data.get("label", "")),
            model=str(data.get("model", "")),
            parent_run_id=str(data.get("parent_run_id", "")),
            output=str(data.get("output", "")),
            error=str(data.get("error", "")),
            metadata=dict(data.get("metadata", {}) or {}),
        )
