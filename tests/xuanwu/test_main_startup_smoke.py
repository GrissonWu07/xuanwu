# -*- coding: utf-8 -*-
"""Smoke coverage for the application startup import path."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_import_main_module() -> None:
    """Verify the renamed package import resolves."""
    from app.xuanwu import main

    assert main is not None


def test_app_instance_exists() -> None:
    """Verify the FastAPI app instance is exposed from the renamed package."""
    from app.xuanwu.main import app

    assert app is not None
    assert "XuanWu" in app.title


def test_app_has_lifespan() -> None:
    """Verify the app still configures a lifespan handler."""
    from app.xuanwu.main import app

    assert app.router.lifespan_context is not None


def test_startup_healthcheck() -> None:
    """Verify the renamed app starts and serves the health endpoint."""
    from app.xuanwu.main import app

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
