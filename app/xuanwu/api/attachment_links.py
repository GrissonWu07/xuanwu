# -*- coding: utf-8 -*-
"""Signed attachment download link helpers."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

from fastapi import Request

from app.xuanwu.auth.config import DEFAULT_JWT_SECRET

DEFAULT_ATTACHMENT_LINK_TTL_SECONDS = 3600
MIN_ATTACHMENT_LINK_TTL_SECONDS = 60
MAX_ATTACHMENT_LINK_TTL_SECONDS = 7 * 24 * 60 * 60


def _clamp_ttl_seconds(value: int) -> int:
    return max(MIN_ATTACHMENT_LINK_TTL_SECONDS, min(value, MAX_ATTACHMENT_LINK_TTL_SECONDS))


def _parse_ttl_seconds(raw_value: str) -> Optional[int]:
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        return _clamp_ttl_seconds(int(text))
    except ValueError:
        return None


def resolve_attachment_link_secret(request_obj: Optional[Request] = None) -> str:
    configured_secret = ""
    if request_obj is not None:
        config = getattr(request_obj.app.state, "config", None)
        auth_config = getattr(config, "auth", None) if config is not None else None
        jwt_config = getattr(auth_config, "jwt", None) if auth_config is not None else None
        configured_secret = str(getattr(jwt_config, "secret_key", "") or "").strip()
    if configured_secret:
        return configured_secret
    env_secret = str(os.environ.get("XUANWU_ATTACHMENT_LINK_SECRET", "")).strip()
    if env_secret:
        return env_secret
    env_fallback = str(os.environ.get("XUANWU_JWT_SECRET", "")).strip()
    if env_fallback:
        return env_fallback
    return DEFAULT_JWT_SECRET


def resolve_attachment_link_ttl_seconds(request_obj: Optional[Request] = None) -> int:
    ttl_value = None
    if request_obj is not None:
        config = getattr(request_obj.app.state, "config", None)
        security_config = getattr(config, "security", None) if config is not None else None
        ttl_value = getattr(security_config, "attachment_link_ttl_seconds", None)
    if isinstance(ttl_value, int) and ttl_value > 0:
        return _clamp_ttl_seconds(ttl_value)
    env_ttl = _parse_ttl_seconds(os.environ.get("XUANWU_ATTACHMENT_LINK_TTL_SECONDS", ""))
    if env_ttl is not None:
        return env_ttl
    return DEFAULT_ATTACHMENT_LINK_TTL_SECONDS


@dataclass
class AttachmentLinkSigner:
    """Create and verify session attachment download signatures."""

    secret_key: str
    default_ttl_seconds: int = DEFAULT_ATTACHMENT_LINK_TTL_SECONDS

    def __post_init__(self) -> None:
        self.default_ttl_seconds = _clamp_ttl_seconds(self.default_ttl_seconds)
        self._secret_bytes = self.secret_key.encode("utf-8")

    def _sign(self, session_key: str, entry_id: str, expires_at: int) -> str:
        payload = f"{session_key}\n{entry_id}\n{expires_at}".encode("utf-8")
        return hmac.new(self._secret_bytes, payload, hashlib.sha256).hexdigest()

    def build_signed_download_url(
        self,
        *,
        session_key: str,
        entry_id: str,
        ttl_seconds: Optional[int] = None,
    ) -> tuple[str, int]:
        ttl = self.default_ttl_seconds if ttl_seconds is None else _clamp_ttl_seconds(ttl_seconds)
        expires_at = int(time.time()) + ttl
        encoded_session_key = quote(session_key, safe="")
        signature = self._sign(session_key, entry_id, expires_at)
        path = f"/api/sessions/{encoded_session_key}/attachments/{entry_id}/content"
        return f"{path}?expires_at={expires_at}&sig={signature}", expires_at

    def verify_signature(
        self,
        *,
        session_key: str,
        entry_id: str,
        expires_at_raw: str | None,
        signature: str | None,
    ) -> tuple[bool, str]:
        if not expires_at_raw or not signature:
            return False, "missing_signature"
        try:
            expires_at = int(expires_at_raw)
        except (TypeError, ValueError):
            return False, "invalid_expires_at"

        if int(time.time()) > expires_at:
            return False, "expired"

        expected = self._sign(session_key, entry_id, expires_at)
        if not hmac.compare_digest(expected, signature):
            return False, "invalid_signature"
        return True, "ok"

