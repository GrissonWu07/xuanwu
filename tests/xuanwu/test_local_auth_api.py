# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.xuanwu.api.routes import APIContext, create_router, set_api_context
from app.xuanwu.auth.config import AuthConfig
from app.xuanwu.db.database import DatabaseConfig, init_database
from app.xuanwu.db.orm.user import UserService
from app.xuanwu.db.schemas import UserCreate, UserUpdate
from app.xuanwu.session.manager import SessionManager
from app.xuanwu.session.queue import SessionQueue
from app.xuanwu.skills.registry import SkillRegistry


def _build_client(tmp_path: Path) -> TestClient:
    ctx = APIContext(
        session_manager=SessionManager(agents_dir=str(tmp_path / "agents")),
        session_queue=SessionQueue(),
        skill_registry=SkillRegistry(),
    )
    set_api_context(ctx)

    app = FastAPI()
    app.include_router(create_router())
    app.state.config = SimpleNamespace(
        auth=AuthConfig(
            provider="local",
            jwt={
                "secret_key": "test-secret",
                "issuer": "xuanwu-test",
                "header_name": "XuanWu-Authenticate",
                "cookie_name": "XuanWu-Authenticate",
                "expires_minutes": 60,
            },
        )
    )
    return TestClient(app)



def test_local_login_success(tmp_path):
    manager = init_database_sync(tmp_path)
    client = _build_client(tmp_path)

    resp = client.post(
        "/api/auth/local/login",
        json={"username": "admin", "password": "adminpass1"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["user"]["username"] == "admin"
    assert body["user"]["auth_type"] == "local"
    assert body["token"]
    assert body["header_name"] == "XuanWu-Authenticate"
    assert "xuanwu_session" in resp.cookies
    assert "XuanWu-Authenticate" in resp.cookies


    manager_cleanup(manager)


def test_local_login_failure(tmp_path):
    manager = init_database_sync(tmp_path)
    client = _build_client(tmp_path)

    resp = client.post(
        "/api/auth/local/login",
        json={"username": "admin", "password": "wrong"},
    )

    assert resp.status_code == 401
    assert "failed" in resp.json()["detail"]

    manager_cleanup(manager)


def test_auth_me_requires_valid_jwt(tmp_path):
    manager = init_database_sync(tmp_path)
    client = _build_client(tmp_path)

    login_resp = client.post(
        "/api/auth/local/login",
        json={"username": "admin", "password": "adminpass1"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]

    me_ok = client.get(
        "/api/auth/me",
        headers={"XuanWu-Authenticate": token},
    )
    assert me_ok.status_code == 200
    assert me_ok.json()["user_id"] == "admin"

    me_fail = client.get(
        "/api/auth/me",
        headers={"XuanWu-Authenticate": "bad-token"},
    )
    assert me_fail.status_code == 401

    manager_cleanup(manager)


def test_auth_me_includes_avatar_from_profile(tmp_path):
    manager = init_database_sync(tmp_path)
    client = _build_client(tmp_path)

    async def _update_profile():
        async with manager.get_session() as session:
            user = await UserService.get_by_username(session, "admin")
            await UserService.update(
                session,
                user.id,
                UserUpdate(
                    display_name="Atlas Admin",
                    avatar_url="/user-content/avatars/admin-profile.png",
                ),
            )

    import asyncio

    asyncio.run(_update_profile())

    login_resp = client.post(
        "/api/auth/local/login",
        json={"username": "admin", "password": "adminpass1"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]

    me_resp = client.get(
        "/api/auth/me",
        headers={"XuanWu-Authenticate": token},
    )
    assert me_resp.status_code == 200
    body = me_resp.json()
    assert body["display_name"] == "Atlas Admin"
    assert body["avatar_url"] == "/user-content/avatars/admin-profile.png"
    assert body["username"] == "admin"

    manager_cleanup(manager)



def init_database_sync(tmp_path: Path):
    import asyncio

    async def _init():
        db_path = tmp_path / "local_auth_api_test.db"
        manager = await init_database(DatabaseConfig(db_type="sqlite", sqlite_path=str(db_path)))
        await manager.create_tables()
        async with manager.get_session() as session:
            await UserService.create(
                session,
                UserCreate(
                    username="admin",
                    password="adminpass1",
                    display_name="Administrator",
                    roles={"admin": True},
                    auth_type="local",
                    is_admin=True,
                    is_active=True,
                ),
            )
        return manager

    return asyncio.run(_init())


def manager_cleanup(manager):
    import asyncio

    asyncio.run(manager.close())
