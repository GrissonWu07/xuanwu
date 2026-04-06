# -*- coding: utf-8 -*-
"""Subagent stream identifier helpers."""

from __future__ import annotations

import hashlib


def build_subagent_status_stream_id(user_id: str, controller_session_key: str) -> str:
    """Build deterministic SSE stream id for one controller session."""
    normalized_user = str(user_id or "").strip() or "default"
    normalized_session = str(controller_session_key or "").strip() or "main"
    digest = hashlib.sha1(
        f"{normalized_user}\n{normalized_session}".encode("utf-8")
    ).hexdigest()
    return f"subagent-status-{digest}"

