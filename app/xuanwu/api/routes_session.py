# -*- coding: utf-8 -*-

from __future__ import annotations

import uuid
from mimetypes import guess_type
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from ..auth.models import ANONYMOUS_USER, UserInfo
from ..session.context import ChatType as SessionChatType
from ..session.context import SessionKey, SessionScope
from ..session.queue import QueueMode
from ..thread_files.models import ThreadArtifactRecord, ThreadUploadRecord
from ..thread_files.service import ThreadFileService
from ..subagents.streaming import build_subagent_status_stream_id
from .attachment_links import (
    AttachmentLinkSigner,
    resolve_attachment_link_secret,
    resolve_attachment_link_ttl_seconds,
)
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
    SessionSubagentKillResponse,
    SessionSubagentRetryRequest,
    SessionSubagentRetryResponse,
    SessionSubagentRunEntry,
    SessionSubagentsResponse,
    SessionSubagentSteerRequest,
    SessionSubagentSteerResponse,
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


def _is_session_owner(auth_user: UserInfo, session_key: str) -> bool:
    return SessionKey.from_string(session_key).user_id == auth_user.user_id


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
    session_key: str,
    ctx: APIContext,
) -> ThreadFileService:
    parsed = SessionKey.from_string(session_key)
    thread_id = parsed.thread_id or "main"
    manager = ctx.session_manager_router.for_user(parsed.user_id)
    return ThreadFileService(
        workspace_path=str(manager.workspace_path),
        user_id=parsed.user_id,
        thread_id=thread_id,
    )


def _build_attachment_entry(
    session_key: str,
    record: ThreadUploadRecord | ThreadArtifactRecord,
    signer: AttachmentLinkSigner,
    *,
    kind: str,
) -> SessionAttachmentEntry:
    entry_id = record.upload_id if kind == "upload" else record.artifact_id
    signed_download_url, expires_at = signer.build_signed_download_url(
        session_key=session_key,
        entry_id=entry_id,
    )
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
            download_url=signed_download_url,
            expires_at=expires_at,
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
        download_url=signed_download_url,
        expires_at=expires_at,
    )


def _build_attachment_signer(request_obj: Request) -> AttachmentLinkSigner:
    return AttachmentLinkSigner(
        secret_key=resolve_attachment_link_secret(request_obj),
        default_ttl_seconds=resolve_attachment_link_ttl_seconds(request_obj),
    )


def _build_subagent_entry(record: Any) -> SessionSubagentRunEntry:
    return SessionSubagentRunEntry(
        run_id=record.run_id,
        subagent_id=record.subagent_id,
        status=record.status.value,
        task=record.task,
        child_session_key=record.child_session_key,
        depth=record.depth,
        created_at=record.created_at.isoformat(),
        started_at=record.started_at.isoformat() if record.started_at else None,
        ended_at=record.ended_at.isoformat() if record.ended_at else None,
        batch_id=str((record.metadata or {}).get("batch_id", "")),
        queue_state=str((record.metadata or {}).get("queue_state", "")),
        spawn_outcome=str((record.metadata or {}).get("spawn_outcome", "")),
        stalled=bool((record.metadata or {}).get("stalled", False)),
        output=record.output or "",
        error=record.error or "",
    )


def _ensure_download_authorized(
    request_obj: Request,
    auth_user: UserInfo,
    session_key: str,
    entry_id: str,
) -> None:
    if _is_session_owner(auth_user, session_key):
        return
    signer = _build_attachment_signer(request_obj)
    is_valid, reason = signer.verify_signature(
        session_key=session_key,
        entry_id=entry_id,
        expires_at_raw=request_obj.query_params.get("expires_at"),
        signature=request_obj.query_params.get("sig"),
    )
    if not is_valid:
        if reason == "missing_signature":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session not found: {session_key}",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Attachment link expired or invalid",
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
        service = _build_thread_file_service_for_session(session_key, ctx)
        signer = _build_attachment_signer(request_obj)
        uploads = [
            _build_attachment_entry(session_key, item, signer, kind="upload")
            for item in await service.list_current_thread_attachments()
        ]
        artifacts = [
            _build_attachment_entry(session_key, item, signer, kind="artifact")
            for item in await service.list_current_thread_artifacts()
        ]
        return SessionAttachmentsResponse(uploads=uploads, artifacts=artifacts)

    @router.get("/sessions/{session_key}/subagents", response_model=SessionSubagentsResponse)
    async def list_session_subagents(
        request_obj: Request,
        session_key: str,
        recent_minutes: int = 30,
        ctx: APIContext = Depends(get_api_context),
    ) -> SessionSubagentsResponse:
        auth_user = _current_user(request_obj)
        _ensure_session_owner(auth_user, session_key)
        runtime = ctx.subagent_runtime
        if runtime is None:
            return SessionSubagentsResponse(runtime_available=False, total=0, active=[], recent=[])

        view = await runtime.list_runs_view(
            user_id=auth_user.user_id,
            controller_session_key=session_key,
            recent_minutes=max(1, int(recent_minutes)),
        )
        active = [_build_subagent_entry(item) for item in view.get("active", [])]
        recent = [_build_subagent_entry(item) for item in view.get("recent", [])]
        return SessionSubagentsResponse(
            runtime_available=True,
            total=int(view.get("total", 0) or 0),
            active_batch_id=str(view.get("active_batch_id", "") or ""),
            queue_depth=int(view.get("queue_depth", 0) or 0),
            active=active,
            recent=recent,
        )

    @router.get("/sessions/{session_key}/subagents/stream")
    async def stream_session_subagent_status(
        request_obj: Request,
        session_key: str,
        cursor: str | None = None,
        last_event_id: str | None = Header(None, alias="Last-Event-ID"),
        ctx: APIContext = Depends(get_api_context),
    ):
        auth_user = _current_user(request_obj)
        _ensure_session_owner(auth_user, session_key)
        if ctx.subagent_runtime is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Subagent runtime unavailable",
            )
        stream_id = build_subagent_status_stream_id(auth_user.user_id, session_key)
        ctx.sse_manager.create_stream(stream_id)
        effective_cursor = (cursor or "").strip() or (last_event_id or "").strip() or None
        return await ctx.sse_manager.create_response(
            stream_id,
            last_event_id=effective_cursor,
        )

    @router.post(
        "/sessions/{session_key}/subagents/{target}/kill",
        response_model=SessionSubagentKillResponse,
    )
    async def kill_session_subagent(
        request_obj: Request,
        session_key: str,
        target: str,
        ctx: APIContext = Depends(get_api_context),
    ) -> SessionSubagentKillResponse:
        auth_user = _current_user(request_obj)
        _ensure_session_owner(auth_user, session_key)
        runtime = ctx.subagent_runtime
        if runtime is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Subagent runtime unavailable",
            )

        normalized_target = (target or "").strip()
        if not normalized_target:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="target is required",
            )

        if normalized_target in {"all", "*"}:
            killed = await runtime.kill_all_for_controller(auth_user.user_id, session_key)
            return SessionSubagentKillResponse(
                status="ok",
                action="kill",
                killed=killed,
                target=normalized_target,
                session_key=session_key,
            )
        if normalized_target.startswith("batch:"):
            batch_id = normalized_target.split(":", 1)[1].strip()
            killed = await runtime.kill_batch(
                user_id=auth_user.user_id,
                controller_session_key=session_key,
                batch_id=batch_id,
            )
            return SessionSubagentKillResponse(
                status="ok",
                action="kill_batch",
                killed=killed,
                target=normalized_target,
                session_key=session_key,
            )

        resolved = await runtime.resolve_controlled_target(
            user_id=auth_user.user_id,
            controller_session_key=session_key,
            target=normalized_target,
        )
        if resolved is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subagent target not found: {normalized_target}",
            )
        killed = await runtime.kill_run(
            auth_user.user_id,
            resolved.run_id,
            reason="killed",
            cascade=True,
        )
        return SessionSubagentKillResponse(
            status="ok",
            action="kill",
            killed=killed,
            target=normalized_target,
            session_key=session_key,
        )

    @router.post(
        "/sessions/{session_key}/subagents/{target}/steer",
        response_model=SessionSubagentSteerResponse,
    )
    async def steer_session_subagent(
        request_obj: Request,
        session_key: str,
        target: str,
        request: SessionSubagentSteerRequest,
        ctx: APIContext = Depends(get_api_context),
    ) -> SessionSubagentSteerResponse:
        auth_user = _current_user(request_obj)
        _ensure_session_owner(auth_user, session_key)
        runtime = ctx.subagent_runtime
        if runtime is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Subagent runtime unavailable",
            )

        normalized_target = (target or "").strip()
        if not normalized_target:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="target is required",
            )

        resolved = await runtime.resolve_controlled_target(
            user_id=auth_user.user_id,
            controller_session_key=session_key,
            target=normalized_target,
        )
        if resolved is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subagent target not found: {normalized_target}",
            )
        replacement = await runtime.steer_run(
            user_id=auth_user.user_id,
            controller_session_key=session_key,
            run_id=resolved.run_id,
            message=request.message,
        )
        if replacement is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Subagent not steerable: {normalized_target}",
            )
        return SessionSubagentSteerResponse(
            status="accepted",
            action="steer",
            target=normalized_target,
            session_key=session_key,
            run_id=replacement.run_id,
            subagent_id=replacement.subagent_id,
            child_session_key=replacement.child_session_key,
            replaces_run_id=resolved.run_id,
        )

    @router.post(
        "/sessions/{session_key}/subagents/{target}/retry",
        response_model=SessionSubagentRetryResponse,
    )
    async def retry_session_subagent(
        request_obj: Request,
        session_key: str,
        target: str,
        request: SessionSubagentRetryRequest,
        ctx: APIContext = Depends(get_api_context),
    ) -> SessionSubagentRetryResponse:
        auth_user = _current_user(request_obj)
        _ensure_session_owner(auth_user, session_key)
        runtime = ctx.subagent_runtime
        if runtime is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Subagent runtime unavailable",
            )
        normalized_target = (target or "").strip()
        if not normalized_target:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="target is required",
            )
        normalized_mode = (request.mode or "").strip().lower() or "retry_same_context"
        if normalized_mode not in {"retry_same_context", "retry_with_edit"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported retry mode: {request.mode}",
            )
        if normalized_mode == "retry_with_edit" and not (request.edited_task or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="edited_task is required for retry_with_edit",
            )

        resolved = await runtime.resolve_controlled_target(
            user_id=auth_user.user_id,
            controller_session_key=session_key,
            target=normalized_target,
        )
        if resolved is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subagent target not found: {normalized_target}",
            )
        replacement = await runtime.retry_run(
            user_id=auth_user.user_id,
            controller_session_key=session_key,
            run_id=resolved.run_id,
            edited_task=(request.edited_task or "") if normalized_mode == "retry_with_edit" else "",
        )
        if replacement is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Subagent not retryable: {normalized_target}",
            )
        return SessionSubagentRetryResponse(
            status="accepted",
            action=normalized_mode,
            target=normalized_target,
            session_key=session_key,
            run_id=replacement.run_id,
            subagent_id=replacement.subagent_id,
            child_session_key=replacement.child_session_key,
            retries_run_id=resolved.run_id,
        )

    @router.post("/sessions/{session_key}/attachments", response_model=SessionAttachmentUploadResponse)
    async def upload_session_attachment(
        request_obj: Request,
        session_key: str,
        file: UploadFile = File(...),
        ctx: APIContext = Depends(get_api_context),
    ) -> SessionAttachmentUploadResponse:
        auth_user = _current_user(request_obj)
        _ensure_session_owner(auth_user, session_key)
        service = _build_thread_file_service_for_session(session_key, ctx)
        payload = await file.read()
        record = await service.save_upload_bytes(
            file.filename or "upload.bin",
            payload,
            content_type=file.content_type,
        )
        signer = _build_attachment_signer(request_obj)
        return SessionAttachmentUploadResponse(
            upload=_build_attachment_entry(session_key, record, signer, kind="upload")
        )

    @router.get("/sessions/{session_key}/attachments/{entry_id}/content")
    async def download_session_attachment(
        request_obj: Request,
        session_key: str,
        entry_id: str,
        ctx: APIContext = Depends(get_api_context),
    ):
        auth_user = _current_user(request_obj)
        _ensure_download_authorized(request_obj, auth_user, session_key, entry_id)
        service = _build_thread_file_service_for_session(session_key, ctx)
        _, record, path = await service.resolve_entry(entry_id)
        if not path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Attachment not found: {entry_id}",
            )
        filename = record.filename if hasattr(record, "filename") else record.name
        media_type = record.content_type if hasattr(record, "content_type") else None
        if not media_type:
            media_type = guess_type(filename)[0] or guess_type(str(path))[0]
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
