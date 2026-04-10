# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    agent_id: str = "main"
    channel: str = "api"
    chat_type: str = "dm"
    scope: str = "main"
    account_id: str = "default"
    peer_id: Optional[str] = None


class SessionThreadCreateRequest(BaseModel):
    agent_id: str = "main"
    channel: str = "web"
    chat_type: str = "dm"
    account_id: str = "default"
    peer_id: Optional[str] = None


class SessionResponse(BaseModel):
    session_key: str
    agent_id: str
    channel: str
    user_id: str
    account_id: str = "default"
    chat_type: str = "dm"
    peer_id: str = "default"
    thread_id: Optional[str] = None
    created_at: datetime
    last_activity: datetime
    message_count: int
    total_tokens: int
    title: str = ""
    title_status: str = "empty"


class SessionHistoryMessage(BaseModel):
    role: str
    content: str
    timestamp: datetime


class SessionHistoryResponse(BaseModel):
    messages: list[SessionHistoryMessage] = Field(default_factory=list)


class SessionAttachmentEntry(BaseModel):
    entry_id: str
    filename: str
    batch_id: str
    relative_path: str
    size_bytes: int = 0
    content_type: Optional[str] = None
    injection_mode: Optional[str] = None
    status: Optional[str] = None
    created_at: str
    download_url: str
    expires_at: Optional[int] = None


class SessionAttachmentsResponse(BaseModel):
    uploads: list[SessionAttachmentEntry] = Field(default_factory=list)
    artifacts: list[SessionAttachmentEntry] = Field(default_factory=list)


class SessionAttachmentUploadResponse(BaseModel):
    upload: SessionAttachmentEntry


class SessionSubagentRunEntry(BaseModel):
    run_id: str
    subagent_id: str
    status: str
    task: str
    child_session_key: str
    depth: int = 0
    created_at: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    batch_id: str = ""
    queue_state: str = ""
    spawn_outcome: str = ""
    stalled: bool = False
    output: str = ""
    error: str = ""


class SessionSubagentsResponse(BaseModel):
    runtime_available: bool = True
    total: int = 0
    active_batch_id: str = ""
    queue_depth: int = 0
    active: list[SessionSubagentRunEntry] = Field(default_factory=list)
    recent: list[SessionSubagentRunEntry] = Field(default_factory=list)


class SessionSubagentSteerRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class SessionSubagentKillResponse(BaseModel):
    status: str
    action: str
    killed: int
    target: str
    session_key: str


class SessionSubagentSteerResponse(BaseModel):
    status: str
    action: str
    target: str
    session_key: str
    run_id: str
    subagent_id: str
    child_session_key: str
    replaces_run_id: Optional[str] = None


class SessionSubagentRetryRequest(BaseModel):
    mode: str = Field(default="retry_same_context")
    edited_task: Optional[str] = Field(default=None, max_length=4000)


class SessionSubagentRetryResponse(BaseModel):
    status: str
    action: str
    target: str
    session_key: str
    run_id: str
    subagent_id: str
    child_session_key: str
    retries_run_id: Optional[str] = None


class SessionResetRequest(BaseModel):
    archive: bool = True


class AgentRunRequest(BaseModel):
    session_key: str
    message: str
    model: Optional[str] = None
    timeout_seconds: int = 600
    context: dict[str, Any] = Field(default_factory=dict)


class AgentRunResponse(BaseModel):
    run_id: str
    status: str
    session_key: str


class AgentStatusResponse(BaseModel):
    run_id: str
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    tokens_used: int = 0
    error: Optional[str] = None


class SkillExecuteRequest(BaseModel):
    skill_name: str
    args: dict[str, Any] = Field(default_factory=dict)


class SkillExecuteResponse(BaseModel):
    skill_name: str
    result: Any
    duration_ms: int


class MemorySearchRequest(BaseModel):
    query: str
    top_k: int = 10
    apply_recency: bool = True


class MemorySearchResult(BaseModel):
    id: str
    content: str
    score: float
    source: str
    timestamp: datetime
    highlights: list[str]


class MemoryWriteRequest(BaseModel):
    content: str
    memory_type: str = "daily"
    source: str = ""
    tags: list[str] = Field(default_factory=list)
    section: str = "General"


class QueueModeRequest(BaseModel):
    mode: str


class LocalLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1)


class StatusResponse(BaseModel):
    session_key: str
    context_tokens: int
    input_tokens: int
    output_tokens: int
    queue_mode: str
    queue_size: int


class CompactRequest(BaseModel):
    instruction: Optional[str] = None


class WebhookDispatchRequest(BaseModel):
    skill: str
    args: dict[str, Any] = Field(default_factory=dict)
    agent_id: Optional[str] = None
    timeout_seconds: int = 600


class WebhookDispatchResponse(BaseModel):
    status: str


class HookDecisionRequest(BaseModel):
    note: Optional[str] = None


class HookEventResponse(BaseModel):
    id: str
    event_type: str
    user_id: str
    session_key: str
    run_id: str
    channel: str
    agent_id: str
    created_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class HookPendingResponse(BaseModel):
    id: str
    module_name: str
    user_id: str
    source_event_ids: list[str] = Field(default_factory=list)
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str
    created_at: datetime
    updated_at: datetime


class HookDecisionResponse(BaseModel):
    pending_id: str
    module_name: str
    decision: str
    status: str

