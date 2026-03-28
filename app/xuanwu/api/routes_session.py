# -*- coding: utf-8 -*-

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from ..auth.models import ANONYMOUS_USER, UserInfo
from ..session.context import ChatType as SessionChatType
from ..session.context import SessionKey, SessionScope
from ..session.queue import QueueMode
from ..thread_files.models import ThreadArtifactRecord, ThreadUploadRecord
from ..thread_files.service import ThreadFileService
from .deps_context import APIContext, get_api_context
from .schemas import (
    CompactRequest,
    QueueModeRequest,
    SessionAttachmentEntry,
    SessionAttachmentsResponse,
    SessionAttachmentUploadResponse,
    SessionCreateRequest,
    SessionHistoryMessage,
    SessionHistoryResponse,
    SessionResetRequest,
    SessionResponse,
    SessionThreadCreateRequest,
    StatusResponse,
)


def _current_user(request_obj: Request) -> UserInfo:
    return getattr(request_obj.state, "user_info", ANONYMOUS_USER)


def _resolve_scope(request: SessionCreateRequest) -> SessionScope:
    return SessionScope(request.scope)


def _resolve_session_scope_for_thread(account_id: str) -> SessionScope:
    return (
        SessionScope.PER_ACCOUNT_CHANNEL_PEER
        if account_id and account_id != "default"
        else SessionScope.PER_CHANNEL_PEER
    )


def _resolve_peer_id(
    auth_user: UserInfo,
    request: SessionCreateRequest | SessionThreadCreateRequest,
) -> str:
    return request.peer_id or auth_user.user_id or "default"


def _build_session_key(
    auth_user: UserInfo,
    request: SessionCreateRequest | SessionThreadCreateRequest,
    *,
    thread_id: str | None = None,
) -> SessionKey:
    return SessionKey(
        agent_id=request.agent_id,
        channel=request.channel,
        account_id=getattr(request, "account_id", "default") or "default",
        chat_type=SessionChatType(request.chat_type),
        user_id=auth_user.user_id,
        peer_id=_resolve_peer_id(auth_user, request),
        thread_id=thread_id,
    )


def _build_session_response(session_key: str, session: Any) -> SessionResponse:
    key = SessionKey.from_string(session_key)
    return SessionResponse(
        session_key=session_key,
        agent_id=key.agent_id,
        channel=key.channel,
        user_id=key.user_id,
        account_id=key.account_id,
        chat_type=key.chat_type.value,
        peer_id=key.peer_id,
        thread_id=key.thread_id,
        created_at=session.created_at,
        last_activity=session.updated_at,
        message_count=getattr(session, "message_count", 0),
        total_tokens=session.total_tokens,
        title=getattr(session, "title", "") or "",
        title_status=getattr(session, "title_status", "empty") or "empty",
    )


def _ensure_session_owner(auth_user: UserInfo, session_key: str) -> SessionKey:
    parsed = SessionKey.from_string(session_key)
    if parsed.user_id != auth_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_key}",
        )
    return parsed


def _build_session_history_response(transcript: list[Any]) -> SessionHistoryResponse:
    messages = [
        SessionHistoryMessage(
            role=entry.role,
            content=entry.content,
            timestamp=entry.timestamp,
        )
        for entry in transcript
        if entry.role in {"user", "assistant"} and entry.content
    ]
    return SessionHistoryResponse(messages=messages)


def _build_thread_file_service_for_session(
    auth_user: UserInfo,
    session_key: str,
    ctx: APIContext,
) -> ThreadFileService:
    parsed = SessionKey.from_string(session_key)
    thread_id = parsed.thread_id or "main"
    manager = ctx.session_manager_router.for_user(auth_user.user_id)
    return ThreadFileService(
        workspace_path=str(manager.workspace_path),
        user_id=auth_user.user_id,
        thread_id=thread_id,
    )


def _build_attachment_entry(
    session_key: str,
    record: ThreadUploadRecord | ThreadArtifactRecord,
    *,
    kind: str,
) -> SessionAttachmentEntry:
    encoded_session_key = quote(session_key, safe="")
    if kind == "upload":
        return SessionAttachmentEntry(
            entry_id=record.upload_id,
            filename=record.filename,
            batch_id=record.batch_id,
            relative_path=record.relative_path,
            size_bytes=record.size_bytes,
            content_type=record.content_type,
            injection_mode=record.injection_mode,
            status=None,
            created_at=record.created_at,
            download_url=f"/api/sessions/{encoded_session_key}/attachments/{record.upload_id}/content",
        )
    return SessionAttachmentEntry(
        entry_id=record.artifact_id,
        filename=record.name,
        batch_id=record.batch_id,
        relative_path=record.relative_path,
        size_bytes=record.size_bytes,
        content_type=None,
        injection_mode=None,
        status=record.status,
        created_at=record.created_at,
        download_url=f"/api/sessions/{encoded_session_key}/attachments/{record.artifact_id}/content",
    )


def register_session_routes(router: APIRouter) -> None:
    @router.get("/sessions", response_model=list[SessionResponse])
    async def list_sessions(
        request_obj: Request,
        ctx: APIContext = Depends(get_api_context),
    ) -> list[SessionResponse]:
        """List all sessions owned by the current user across all channels."""
        auth_user = _current_user(request_obj)
        manager = ctx.session_manager_router.for_user(auth_user.user_id)
        all_sessions = await manager.list_sessions()
        user_sessions = [_build_session_response(session.session_key, session) for session in all_sessions]

        user_sessions.sort(key=lambda s: s.last_activity or s.created_at, reverse=True)
        return user_sessions

    @router.post("/sessions", response_model=SessionResponse)
    async def create_session(
        request_obj: Request,
        request: SessionCreateRequest,
        ctx: APIContext = Depends(get_api_context),
    ) -> SessionResponse:
        auth_user = _current_user(request_obj)
        key = _build_session_key(auth_user, request)
        session_key_str = key.to_string(scope=_resolve_scope(request))
        manager = ctx.session_manager_router.for_user(auth_user.user_id)
        session = await manager.get_or_create(session_key_str)
        return _build_session_response(session_key_str, session)

    @router.post("/sessions/threads", response_model=SessionResponse)
    async def create_thread_session(
        request_obj: Request,
        request: SessionThreadCreateRequest,
        ctx: APIContext = Depends(get_api_context),
    ) -> SessionResponse:
        auth_user = _current_user(request_obj)
        thread_id = uuid.uuid4().hex
        key = _build_session_key(auth_user, request, thread_id=thread_id)
        session_key_str = key.to_string(
            scope=_resolve_session_scope_for_thread(request.account_id),
        )
        manager = ctx.session_manager_router.for_user(auth_user.user_id)
        session = await manager.get_or_create(session_key_str)
        return _build_session_response(session_key_str, session)

    @router.get("/sessions/{session_key}", response_model=SessionResponse)
    async def get_session(
        request_obj: Request,
        session_key: str,
        ctx: APIContext = Depends(get_api_context),
    ) -> SessionResponse:
        auth_user = _current_user(request_obj)
        _ensure_session_owner(auth_user, session_key)
        manager = ctx.session_manager_router.for_session_key(session_key)
        session = await manager.get_session(session_key)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session not found: {session_key}",
            )
        return _build_session_response(session_key, session)

    @router.get("/sessions/{session_key}/history", response_model=SessionHistoryResponse)
    async def get_session_history(
        request_obj: Request,
        session_key: str,
        ctx: APIContext = Depends(get_api_context),
    ) -> SessionHistoryResponse:
        auth_user = _current_user(request_obj)
        _ensure_session_owner(auth_user, session_key)
        manager = ctx.session_manager_router.for_session_key(session_key)
        session = await manager.get_session(session_key)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session not found: {session_key}",
            )
        transcript = await manager.load_transcript(session_key)
        return _build_session_history_response(transcript)

    @router.get("/sessions/{session_key}/attachments", response_model=SessionAttachmentsResponse)
    async def list_session_attachments(
        request_obj: Request,
        session_key: str,
        ctx: APIContext = Depends(get_api_context),
    ) -> SessionAttachmentsResponse:
        auth_user = _current_user(request_obj)
        _ensure_session_owner(auth_user, session_key)
        service = _build_thread_file_service_for_session(auth_user, session_key, ctx)
        uploads = [
            _build_attachment_entry(session_key, item, kind="upload")
            for item in await service.list_current_thread_attachments()
        ]
        artifacts = [
            _build_attachment_entry(session_key, item, kind="artifact")
            for item in await service.list_current_thread_artifacts()
        ]
        return SessionAttachmentsResponse(uploads=uploads, artifacts=artifacts)

    @router.post("/sessions/{session_key}/attachments", response_model=SessionAttachmentUploadResponse)
    async def upload_session_attachment(
        request_obj: Request,
        session_key: str,
        file: UploadFile = File(...),
        ctx: APIContext = Depends(get_api_context),
    ) -> SessionAttachmentUploadResponse:
        auth_user = _current_user(request_obj)
        _ensure_session_owner(auth_user, session_key)
        service = _build_thread_file_service_for_session(auth_user, session_key, ctx)
        payload = await file.read()
        record = await service.save_upload_bytes(
            file.filename or "upload.bin",
            payload,
            content_type=file.content_type,
        )
        return SessionAttachmentUploadResponse(
            upload=_build_attachment_entry(session_key, record, kind="upload")
        )

    @router.get("/sessions/{session_key}/attachments/{entry_id}/content")
    async def download_session_attachment(
        request_obj: Request,
        session_key: str,
        entry_id: str,
        ctx: APIContext = Depends(get_api_context),
    ):
        auth_user = _current_user(request_obj)
        _ensure_session_owner(auth_user, session_key)
        service = _build_thread_file_service_for_session(auth_user, session_key, ctx)
        _, record, path = await service.resolve_entry(entry_id)
        if not path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Attachment not found: {entry_id}",
            )
        filename = record.filename if hasattr(record, "filename") else record.name
        media_type = record.content_type if hasattr(record, "content_type") else None
        return FileResponse(path, media_type=media_type, filename=filename)

    @router.post("/sessions/{session_key}/reset")
    async def reset_session(
        request_obj: Request,
        session_key: str,
        request: SessionResetRequest,
        ctx: APIContext = Depends(get_api_context),
    ) -> dict[str, Any]:
        auth_user = _current_user(request_obj)
        _ensure_session_owner(auth_user, session_key)
        manager = ctx.session_manager_router.for_session_key(session_key)
        await manager.reset_session(session_key, archive=request.archive)
        return {"status": "reset", "session_key": session_key}

    @router.delete("/sessions/{session_key}")
    async def delete_session(
        request_obj: Request,
        session_key: str,
        ctx: APIContext = Depends(get_api_context),
    ) -> dict[str, Any]:
        auth_user = _current_user(request_obj)
        _ensure_session_owner(auth_user, session_key)
        manager = ctx.session_manager_router.for_session_key(session_key)
        success = await manager.delete_session(session_key)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session not found: {session_key}",
            )
        return {"status": "deleted", "session_key": session_key}

    @router.get("/sessions/{session_key}/status", response_model=StatusResponse)
    async def get_status(
        request_obj: Request,
        session_key: str,
        ctx: APIContext = Depends(get_api_context),
    ) -> StatusResponse:
        auth_user = _current_user(request_obj)
        _ensure_session_owner(auth_user, session_key)
        manager = ctx.session_manager_router.for_session_key(session_key)
        session = await manager.get_session(session_key)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session not found: {session_key}",
            )

        queue_mode = ctx.session_queue.get_mode(session_key)
        queue_size = ctx.session_queue.queue_size(session_key)
        return StatusResponse(
            session_key=session_key,
            context_tokens=session.context_tokens,
            input_tokens=session.input_tokens,
            output_tokens=session.output_tokens,
            queue_mode=queue_mode.value,
            queue_size=queue_size,
        )

    @router.post("/sessions/{session_key}/queue")
    async def set_queue_mode(
        request_obj: Request,
        session_key: str,
        request: QueueModeRequest,
        ctx: APIContext = Depends(get_api_context),
    ) -> dict[str, Any]:
        auth_user = _current_user(request_obj)
        _ensure_session_owner(auth_user, session_key)
        try:
            mode = QueueMode(request.mode)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid queue mode: {request.mode}",
            )

        ctx.session_queue.set_session_mode(session_key, mode)
        return {"session_key": session_key, "queue_mode": request.mode}

    @router.post("/sessions/{session_key}/compact")
    async def trigger_compact(
        request_obj: Request,
        session_key: str,
        request: CompactRequest,
        ctx: APIContext = Depends(get_api_context),
    ) -> dict[str, Any]:
        auth_user = _current_user(request_obj)
        _ensure_session_owner(auth_user, session_key)
        manager = ctx.session_manager_router.for_session_key(session_key)
        session = await manager.get_session(session_key)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session not found: {session_key}",
            )

        return {
            "session_key": session_key,
            "status": "compaction_triggered",
            "instruction": request.instruction,
        }
