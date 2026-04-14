# -*- coding: utf-8 -*-
"""Tests for Feishu channel handler."""

from __future__ import annotations

import json
import hashlib
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, Any

from app.xuanwu.channels.handlers.feishu import FeishuHandler
from app.xuanwu.channels.models import (
    ChannelMode,
    ConnectionStatus,
    InboundMessage,
    OutboundMessage,
    SendResult,
)


class TestFeishuHandler:
    """Tests for FeishuHandler class."""

    def test_handler_class_attributes(self):
        """Test handler class has correct attributes."""
        assert FeishuHandler.channel_type == "feishu"
        assert FeishuHandler.channel_name == "Feishu"
        assert FeishuHandler.channel_mode == ChannelMode.BIDIRECTIONAL
        assert FeishuHandler.supports_long_connection is True
        assert FeishuHandler.supports_webhook is True

    def test_handler_init(self):
        """Test handler initialization."""
        handler = FeishuHandler()
        assert handler.config == {}
        assert handler._status == ConnectionStatus.DISCONNECTED
        assert handler._access_token is None

    @pytest.mark.asyncio
    async def test_setup_with_valid_config(self):
        """Test setup with valid app_id and app_secret."""
        handler = FeishuHandler()
        config = {
            "app_id": "test_app_id",
            "app_secret": "test_app_secret",
        }
        result = await handler.setup(config)
        assert result is True
        assert handler.config["app_id"] == "test_app_id"
        assert handler.config["app_secret"] == "test_app_secret"

    @pytest.mark.asyncio
    async def test_setup_missing_app_id(self):
        """Test setup fails when app_id is missing."""
        handler = FeishuHandler()
        config = {
            "app_secret": "test_app_secret",
        }
        result = await handler.setup(config)
        assert result is False

    @pytest.mark.asyncio
    async def test_setup_missing_app_secret(self):
        """Test setup fails when app_secret is missing."""
        handler = FeishuHandler()
        config = {
            "app_id": "test_app_id",
        }
        result = await handler.setup(config)
        assert result is False

    @pytest.mark.asyncio
    async def test_setup_webhook_mode_without_app_credentials(self):
        """Webhook mode should not require app_id/app_secret."""
        handler = FeishuHandler()
        config = {
            "connection_mode": "webhook",
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
        }
        result = await handler.setup(config)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_config_valid(self):
        """Test config validation with valid config."""
        handler = FeishuHandler()
        config = {
            "app_id": "test_app_id",
            "app_secret": "test_app_secret",
        }
        result = await handler.validate_config(config)
        assert result.valid is True
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_validate_config_missing_app_id(self):
        """Test config validation fails when app_id missing."""
        handler = FeishuHandler()
        config = {
            "app_secret": "test_app_secret",
        }
        result = await handler.validate_config(config)
        assert result.valid is False
        assert any("app_id" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_validate_config_missing_app_secret(self):
        """Test config validation fails when app_secret missing."""
        handler = FeishuHandler()
        config = {
            "app_id": "test_app_id",
        }
        result = await handler.validate_config(config)
        assert result.valid is False
        assert any("app_secret" in e for e in result.errors)

    @pytest.mark.asyncio
    async def test_validate_config_empty(self):
        """Test config validation fails with empty config."""
        handler = FeishuHandler()
        config = {}
        result = await handler.validate_config(config)
        assert result.valid is False
        assert len(result.errors) >= 2

    def test_describe_schema(self):
        """Test schema description returns valid structure."""
        handler = FeishuHandler()
        schema = handler.describe_schema()
        
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "connection_mode" in schema["properties"]
        assert "app_id" in schema["properties"]
        assert "app_secret" in schema["properties"]
        assert "webhook_url" in schema["properties"]
        assert "required_by_mode" in schema

    @pytest.mark.asyncio
    async def test_start_sets_connecting_status(self):
        """Test start method sets status to CONNECTING."""
        handler = FeishuHandler()
        result = await handler.start(None)
        
        assert result is True
        assert handler._status == ConnectionStatus.CONNECTING

    @pytest.mark.asyncio
    async def test_stop_disconnects(self):
        """Test stop method disconnects handler."""
        handler = FeishuHandler()
        handler._running = True
        result = await handler.stop()
        
        assert result is True
        assert handler._status == ConnectionStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_handle_inbound_text_message(self):
        """Test handling inbound text message."""
        handler = FeishuHandler()
        request = {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "message": {
                    "message_id": "msg_123",
                    "chat_id": "chat_456",
                    "chat_type": "p2p",
                    "content": json.dumps({"text": "Hello Feishu"}),
                    "create_time": "1234567890",
                },
                "sender": {
                    "sender_id": {"open_id": "user_789"},
                }
            }
        }
        
        message = await handler.handle_inbound(request)
        
        assert message is not None
        assert message.message_id == "msg_123"
        assert message.content == "Hello Feishu"
        assert message.sender_id == "user_789"
        assert message.chat_id == "chat_456"

    @pytest.mark.asyncio
    async def test_handle_inbound_json_string(self):
        """Test handling inbound message from JSON string."""
        handler = FeishuHandler()
        request = json.dumps({
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "message": {
                    "message_id": "msg_abc",
                    "chat_id": "chat_def",
                    "content": json.dumps({"text": "Hello from JSON"}),
                },
                "sender": {
                    "sender_id": {"open_id": "user_xyz"},
                }
            }
        })
        
        message = await handler.handle_inbound(request)
        
        assert message is not None
        assert message.content == "Hello from JSON"

    @pytest.mark.asyncio
    async def test_handle_inbound_wrapped_request_data(self):
        """Test handling inbound message from channel_hooks wrapped payload."""
        handler = FeishuHandler()
        request = {
            "headers": {"content-type": "application/json"},
            "query_params": {},
            "body": {
                "header": {"event_type": "im.message.receive_v1"},
                "event": {
                    "message": {
                        "message_id": "msg_wrapped",
                        "chat_id": "chat_wrapped",
                        "chat_type": "p2p",
                        "content": json.dumps({"text": "Wrapped payload"}),
                    },
                    "sender": {
                        "sender_id": {"open_id": "user_wrapped"},
                    },
                },
            },
        }

        message = await handler.handle_inbound(request)

        assert message is not None
        assert message.message_id == "msg_wrapped"
        assert message.content == "Wrapped payload"

    @pytest.mark.asyncio
    async def test_handle_inbound_webhook_verification_token_mismatch(self):
        """Webhook inbound should be rejected when verification token mismatches."""
        handler = FeishuHandler({"verification_token": "expected-token"})
        payload = {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "message": {
                    "message_id": "msg_wrapped",
                    "chat_id": "chat_wrapped",
                    "chat_type": "p2p",
                    "content": json.dumps({"text": "Wrapped payload"}),
                },
                "sender": {
                    "sender_id": {"open_id": "user_wrapped"},
                },
            },
            "token": "wrong-token",
        }
        request = {
            "headers": {"content-type": "application/json"},
            "query_params": {},
            "raw_body": json.dumps(payload),
            "body": payload,
        }
        message = await handler.handle_inbound(request)
        assert message is None

    @pytest.mark.asyncio
    async def test_handle_inbound_webhook_signature_valid(self):
        """Webhook inbound should pass when signature is valid."""
        encrypt_key = "encrypt-key"
        handler = FeishuHandler({"encrypt_key": encrypt_key})
        payload = {
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "message": {
                    "message_id": "msg_sig",
                    "chat_id": "chat_sig",
                    "chat_type": "p2p",
                    "content": json.dumps({"text": "Signed payload"}),
                },
                "sender": {
                    "sender_id": {"open_id": "user_sig"},
                },
            },
        }
        raw_body = json.dumps(payload, separators=(",", ":"))
        timestamp = "1710000000"
        nonce = "nonce123"
        signature = hashlib.sha256(
            (timestamp + nonce + encrypt_key).encode("utf-8") + raw_body.encode("utf-8")
        ).hexdigest()
        request = {
            "headers": {
                "content-type": "application/json",
                "x-lark-request-timestamp": timestamp,
                "x-lark-request-nonce": nonce,
                "x-lark-signature": signature,
            },
            "query_params": {},
            "raw_body": raw_body,
            "body": payload,
        }
        message = await handler.handle_inbound(request)
        assert message is not None
        assert message.message_id == "msg_sig"

    @pytest.mark.asyncio
    async def test_connect_webhook_mode_marks_connected_without_sdk(self):
        """Webhook mode should not start SDK process and should connect immediately."""
        handler = FeishuHandler(
            {
                "connection_mode": "webhook",
                "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
            }
        )
        result = await handler.connect()
        assert result is True
        assert handler.get_status() == ConnectionStatus.CONNECTED

    @pytest.mark.asyncio
    async def test_handle_inbound_wrong_event_type(self):
        """Test handling inbound with wrong event type returns None."""
        handler = FeishuHandler()
        request = {
            "header": {"event_type": "some.other.event"},
            "event": {}
        }
        
        message = await handler.handle_inbound(request)
        
        assert message is None

    @pytest.mark.asyncio
    async def test_send_message_success(self):
        """Test sending message successfully."""
        handler = FeishuHandler({"app_id": "test_id", "app_secret": "test_secret"})
        handler._access_token = "test_token"
        handler._token_expires_at = 9999999999
        
        outbound = OutboundMessage(
            chat_id="chat_123",
            content="Test message",
            content_type="text",
        )
        
        with patch("app.xuanwu.channels.handlers.feishu.aiohttp") as mock_aiohttp:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={
                "code": 0,
                "data": {"message_id": "sent_msg_id"}
            })
            
            mock_post_cm = AsyncMock()
            mock_post_cm.__aenter__.return_value = mock_response
            mock_post_cm.__aexit__.return_value = None
            
            mock_session = MagicMock()
            mock_session.post.return_value = mock_post_cm
            
            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__.return_value = mock_session
            mock_session_cm.__aexit__.return_value = None
            
            mock_aiohttp.ClientSession.return_value = mock_session_cm
            
            result = await handler.send_message(outbound)
            
            assert result.success is True
            assert result.message_id == "sent_msg_id"

    @pytest.mark.asyncio
    async def test_send_message_api_error(self):
        """Test sending message handles API error."""
        handler = FeishuHandler({"app_id": "test_id", "app_secret": "test_secret"})
        handler._access_token = "test_token"
        handler._token_expires_at = 9999999999
        
        outbound = OutboundMessage(
            chat_id="chat_123",
            content="Test message",
            content_type="text",
        )
        
        with patch("app.xuanwu.channels.handlers.feishu.aiohttp") as mock_aiohttp:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={
                "code": 99999,
                "msg": "API Error"
            })
            
            mock_post_cm = AsyncMock()
            mock_post_cm.__aenter__.return_value = mock_response
            mock_post_cm.__aexit__.return_value = None
            
            mock_session = MagicMock()
            mock_session.post.return_value = mock_post_cm
            
            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__.return_value = mock_session
            mock_session_cm.__aexit__.return_value = None
            
            mock_aiohttp.ClientSession.return_value = mock_session_cm
            
            result = await handler.send_message(outbound)
            
            assert result.success is False
            assert "API Error" in result.error


class TestFeishuHandlerMessageCallback:
    """Tests for Feishu handler message callback functionality."""

    def test_set_message_callback(self):
        """Test setting message callback."""
        handler = FeishuHandler()
        callback = MagicMock()
        
        handler.set_message_callback(callback)
        
        assert handler._message_callback == callback


class TestFeishuConnectionMode:
    """Tests for Feishu connection_mode feature."""

    def test_schema_has_connection_mode(self):
        """Test schema includes connection_mode field."""
        handler = FeishuHandler()
        schema = handler.describe_schema()
        
        assert "connection_mode" in schema["properties"]
        cm = schema["properties"]["connection_mode"]
        assert cm["type"] == "string"
        assert cm["enum"] == ["longconnection", "webhook"]
        assert cm["default"] == "longconnection"
        assert "enumLabels" in cm

    def test_schema_has_required_by_mode(self):
        """Test schema includes required_by_mode."""
        handler = FeishuHandler()
        schema = handler.describe_schema()
        
        assert "required_by_mode" in schema
        rbm = schema["required_by_mode"]
        assert "longconnection" in rbm
        assert "webhook" in rbm
        assert "app_id" in rbm["longconnection"]
        assert "app_secret" in rbm["longconnection"]
        assert "webhook_url" in rbm["webhook"]

    def test_schema_fields_have_show_when(self):
        """Test fields have showWhen conditions."""
        handler = FeishuHandler()
        schema = handler.describe_schema()
        props = schema["properties"]
        
        # Long connection mode fields
        assert props["app_id"]["showWhen"] == {"connection_mode": "longconnection"}
        assert props["app_secret"]["showWhen"] == {"connection_mode": "longconnection"}
        
        # Webhook mode fields
        assert props["webhook_url"]["showWhen"] == {"connection_mode": "webhook"}

    @pytest.mark.asyncio
    async def test_validate_config_longconnection_mode(self):
        """Test validation for long connection mode."""
        handler = FeishuHandler()
        
        # Valid long connection config
        result = await handler.validate_config({
            "connection_mode": "longconnection",
            "app_id": "cli_test",
            "app_secret": "test_secret"
        })
        assert result.valid is True
        
        # Invalid long connection config (missing app_secret)
        result = await handler.validate_config({
            "connection_mode": "longconnection",
            "app_id": "cli_test"
        })
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_validate_config_webhook_mode(self):
        """Test validation for webhook mode."""
        handler = FeishuHandler()
        
        # Valid webhook config
        result = await handler.validate_config({
            "connection_mode": "webhook",
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
        })
        assert result.valid is True
        
        # Invalid webhook config (missing webhook_url)
        result = await handler.validate_config({
            "connection_mode": "webhook"
        })
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_send_via_webhook(self):
        """Test sending message via webhook."""
        handler = FeishuHandler()
        handler.config = {
            "connection_mode": "webhook",
            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
        }
        
        outbound = OutboundMessage(
            chat_id="test_chat",
            content="Hello via webhook",
            content_type="text",
        )
        
        with patch("app.xuanwu.channels.handlers.feishu.aiohttp") as mock_aiohttp:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"code": 0})
            
            mock_post_cm = AsyncMock()
            mock_post_cm.__aenter__.return_value = mock_response
            mock_post_cm.__aexit__.return_value = None
            
            mock_session = MagicMock()
            mock_session.post.return_value = mock_post_cm
            
            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__.return_value = mock_session
            mock_session_cm.__aexit__.return_value = None
            
            mock_aiohttp.ClientSession.return_value = mock_session_cm
            
            result = await handler.send_message(outbound)
            
            assert result.success is True
            # Verify webhook URL was called
            mock_session.post.assert_called_once()
            call_args = mock_session.post.call_args
            assert "webhook_url" in handler.config
