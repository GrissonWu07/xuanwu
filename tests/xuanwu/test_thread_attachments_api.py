# -*- coding: utf-8 -*-

from __future__ import annotations

from io import BytesIO
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.xuanwu.api.routes import APIContext, create_router, set_api_context
from app.xuanwu.auth.models import UserInfo
from app.xuanwu.session.manager import SessionManager
from app.xuanwu.session.queue import SessionQueue
from app.xuanwu.skills.registry import SkillRegistry


def _build_client(tmp_path, user_id: str = "default") -> TestClient:
    ctx = APIContext(
        session_manager=SessionManager(workspace_path=str(tmp_path), user_id="default"),
        session_queue=SessionQueue(),
        skill_registry=SkillRegistry(),
    )
    set_api_context(ctx)

    app = FastAPI()

    @app.middleware("http")
    async def inject_user_info(request, call_next):
        request.state.user_info = UserInfo(user_id=user_id, display_name=user_id)
        return await call_next(request)

    app.include_router(create_router())
    return TestClient(app)


def test_upload_list_and_download_thread_attachments(tmp_path):
    client = _build_client(tmp_path, user_id="alice")

    session_response = client.post("/api/sessions/threads", json={"channel": "web", "chat_type": "dm"})
    assert session_response.status_code == 200
    session_key = session_response.json()["session_key"]
    encoded_key = quote(session_key, safe="")

    upload_response = client.post(
        f"/api/sessions/{encoded_key}/attachments",
        files={"file": ("hello.txt", BytesIO(b"hello world"), "text/plain")},
    )
    assert upload_response.status_code == 200
    uploaded = upload_response.json()["upload"]
    assert uploaded["filename"] == "hello.txt"
    assert uploaded["injection_mode"] == "full"
    assert uploaded["download_url"].endswith(f"/api/sessions/{encoded_key}/attachments/{uploaded['entry_id']}/content")

    list_response = client.get(f"/api/sessions/{encoded_key}/attachments")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert [item["filename"] for item in payload["uploads"]] == ["hello.txt"]
    assert payload["artifacts"] == []

    download_response = client.get(uploaded["download_url"])
    assert download_response.status_code == 200
    assert download_response.content == b"hello world"
