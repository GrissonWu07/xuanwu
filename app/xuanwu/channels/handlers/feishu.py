# -*- coding: utf-8 -*-
"""Feishu (Lark) channel handler with multiprocessing for SDK isolation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import multiprocessing
import queue
import re
import secrets
import threading
import time
from typing import Any, Callable, Dict, Optional

import aiohttp

from ..handler import ChannelHandler
from ..models import (
    ChannelMode,
    ChannelValidationResult,
    ConnectionStatus,
    InboundMessage,
    OutboundMessage,
    SendResult,
)

logger = logging.getLogger(__name__)
_AT_TAG_PATTERN = re.compile(r"<at\b[^>]*>", re.IGNORECASE)


def _extract_text_and_mention(content: Any) -> tuple[str, bool]:
    """Extract plain text and whether content contains mention markers."""
    has_mention = False
    text = ""

    if isinstance(content, str):
        text = content
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                parsed_text = parsed.get("text")
                if isinstance(parsed_text, str) and parsed_text:
                    text = parsed_text
                mentions = parsed.get("mentions") or parsed.get("at_users")
                has_mention = bool(mentions)
        except Exception:
            pass
    elif isinstance(content, dict):
        parsed_text = content.get("text")
        text = parsed_text if isinstance(parsed_text, str) else str(content)
        mentions = content.get("mentions") or content.get("at_users")
        has_mention = bool(mentions)
    else:
        text = str(content)

    if not has_mention and isinstance(text, str):
        has_mention = bool(_AT_TAG_PATTERN.search(text))

    return text, has_mention


def _run_feishu_sdk_process(
    app_id: str,
    app_secret: str,
    message_queue: multiprocessing.Queue,
    control_queue: multiprocessing.Queue,
):
    """
    Run Feishu SDK in a separate process to avoid event loop conflicts.
    
    Args:
        app_id: Feishu app ID
        app_secret: Feishu app secret
        message_queue: Queue to send received messages to main process
        control_queue: Queue to receive control commands from main process
    """
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
    
    # Flag to track if connection signal has been sent
    connection_signaled = False
    
    def handle_message(data: P2ImMessageReceiveV1):
        """Handle received message and send to queue."""
        try:
            message = data.event.message
            sender = data.event.sender
            
            # Parse content
            text, has_mention = _extract_text_and_mention(message.content)
            
            # Send to queue as dict
            msg_data = {
                "message_id": message.message_id,
                "sender_id": sender.sender_id.open_id,
                "chat_id": message.chat_id,
                "chat_type": message.chat_type,
                "content": text,
                "content_type": message.message_type,
                "create_time": message.create_time,
                "tenant_key": sender.tenant_key,
                "has_mention": has_mention,
            }
            message_queue.put(msg_data)
            print(f"[Feishu SDK Process] Message received: {text[:50]}...")
            
        except Exception as e:
            print(f"[Feishu SDK Process] Error handling message: {e}")
    
    def send_connected_signal():
        """Send connected signal after delay if process is still running."""
        nonlocal connection_signaled
        if not connection_signaled:
            connection_signaled = True
            print("[Feishu SDK Process] Connection established, sending signal", flush=True)
            try:
                control_queue.put({"type": "connected"}, timeout=5)
            except Exception as exc:
                print(f"[Feishu SDK Process] Failed to put connected signal: {exc}", flush=True)
    
    try:
        print(f"[Feishu SDK Process] Starting with app_id: {app_id}", flush=True)
        
        # Create event handler
        event_handler = lark.EventDispatcherHandler.builder(
            "", ""
        ).register_p2_im_message_receive_v1(
            handle_message
        ).build()
        
        # Create WebSocket client
        client = lark.ws.Client(
            app_id,
            app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )
        
        # Use timer to send connected signal after delay
        # If client.start() throws exception before timer fires, the signal won't be sent
        timer = threading.Timer(3.0, send_connected_signal)
        timer.daemon = True
        timer.start()
        
        # Start the client (blocking)
        print("[Feishu SDK Process] Connecting...", flush=True)
        client.start()
        
    except Exception as e:
        print(f"[Feishu SDK Process] Error: {e}", flush=True)
        if not connection_signaled:
            try:
                control_queue.put({"type": "error", "error": str(e)}, timeout=5)
            except Exception:
                pass


class FeishuHandler(ChannelHandler):
    """Feishu channel handler using multiprocessing for SDK isolation."""
    
    channel_type = "feishu"
    channel_name = "Feishu"
    channel_icon = "feishu"
    channel_mode = ChannelMode.BIDIRECTIONAL
    supports_long_connection = True
    supports_webhook = True
    
    # Feishu API endpoints
    FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
    AUTH_URL = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._process: Optional[multiprocessing.Process] = None
        self._message_queue: Optional[multiprocessing.Queue] = None
        self._control_queue: Optional[multiprocessing.Queue] = None
        self._message_callback: Optional[Callable[[InboundMessage], None]] = None
        self._listener_thread: Optional[threading.Thread] = None
        self._running = False
    
    async def setup(self, connection_config: Dict[str, Any]) -> bool:
        """Initialize handler with configuration."""
        try:
            self.config.update(connection_config)
            connection_mode = self.config.get("connection_mode", "longconnection")
            if connection_mode == "webhook":
                if not self.config.get("webhook_url"):
                    logger.error("Feishu webhook_url is required for webhook mode")
                    return False
                return True

            if not self.config.get("app_id"):
                logger.error("Feishu app_id is required")
                return False
            if not self.config.get("app_secret"):
                logger.error("Feishu app_secret is required")
                return False

            return True
        except Exception as e:
            logger.error(f"Feishu setup failed: {e}")
            return False
    
    def set_message_callback(self, callback: Callable[[InboundMessage], None]) -> None:
        """Set callback for incoming messages."""
        self._message_callback = callback
    
    async def start(self, context: Any) -> bool:
        """Start handler."""
        try:
            self._status = ConnectionStatus.CONNECTING
            logger.info("Feishu handler starting...")
            return True
        except Exception as e:
            logger.error(f"Feishu start failed: {e}")
            self._status = ConnectionStatus.ERROR
            return False
    
    async def _verify_credentials(self) -> bool:
        """Verify Feishu credentials by getting tenant_access_token.
        
        This validates the app_id/app_secret before starting the SDK subprocess.
        Returns True if credentials are valid, False otherwise.
        """
        app_id = self.config.get("app_id")
        app_secret = self.config.get("app_secret")
        
        if not app_id or not app_secret:
            logger.error("[Feishu] Missing app_id or app_secret")
            return False
        
        try:
            url = f"{self.FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
            payload = {"app_id": app_id, "app_secret": app_secret}
            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()
                    if data.get("code") == 0 and data.get("tenant_access_token"):
                        logger.info("[Feishu] Credentials verified successfully")
                        return True
                    else:
                        logger.error(f"[Feishu] Credential verification failed: {data.get('msg', 'unknown error')}")
                        return False
        except Exception as e:
            logger.error(f"[Feishu] Credential verification error: {e}")
            return False

    async def _cleanup_connect_failure(self) -> None:
        """Cleanup resources after connect failure."""
        self._running = False
        if self._process and self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=5)
        self._process = None
        self._message_queue = None
        self._control_queue = None

    async def connect(self) -> bool:
        """Establish connection using multiprocessing."""
        try:
            connection_mode = self.config.get("connection_mode", "longconnection")
            if connection_mode == "webhook":
                logger.info("Feishu webhook mode enabled (no SDK long connection needed)")
                self._status = ConnectionStatus.CONNECTED
                return True

            app_id = self.config.get("app_id")
            app_secret = self.config.get("app_secret")
            
            # Pre-verify credentials before starting SDK subprocess
            if not await self._verify_credentials():
                self._status = ConnectionStatus.ERROR
                return False
            
            print(f"[Feishu] Connecting with app_id: {app_id}")
            
            # Create queues for IPC
            self._message_queue = multiprocessing.Queue()
            self._control_queue = multiprocessing.Queue()
            
            # Start SDK process
            self._process = multiprocessing.Process(
                target=_run_feishu_sdk_process,
                args=(app_id, app_secret, self._message_queue, self._control_queue),
                daemon=True,
            )
            self._process.start()
            print(f"[Feishu] SDK process started (PID: {self._process.pid})")
            
            # Start message listener thread
            self._running = True
            self._listener_thread = threading.Thread(
                target=self._listen_for_messages,
                daemon=True,
            )
            self._listener_thread.start()
            print("[Feishu] Message listener started")
            
            # Wait for connection result from subprocess via control_queue
            # Timeout: 20 seconds (subprocess sends signal after 3 seconds if successful)
            connection_timeout = 20.0
            start_time = time.time()
            
            while time.time() - start_time < connection_timeout:
                # Check if process died
                if not self._process.is_alive():
                    logger.error("Feishu SDK process died unexpectedly")
                    self._status = ConnectionStatus.ERROR
                    await self._cleanup_connect_failure()
                    return False
                
                # Try to get message from control queue (non-blocking)
                try:
                    msg = self._control_queue.get_nowait()
                    if msg.get("type") == "connected":
                        self._status = ConnectionStatus.CONNECTED
                        logger.info("Feishu connected via multiprocessing")
                        return True
                    elif msg.get("type") == "error":
                        error = msg.get("error", "Unknown error")
                        logger.error(f"Feishu connection failed: {error}")
                        self._status = ConnectionStatus.ERROR
                        await self._cleanup_connect_failure()
                        return False
                except queue.Empty:
                    # Fallback for Windows/IPC edge cases: if process is still alive
                    # after 10 seconds, treat connection as established.
                    elapsed = time.time() - start_time
                    if elapsed > 10.0 and self._process.is_alive():
                        logger.info("Feishu process alive after 10s, assuming connected (Queue fallback)")
                        self._status = ConnectionStatus.CONNECTED
                        return True
                    await asyncio.sleep(0.5)
                    continue
            
            # Timeout reached
            logger.error("Feishu connection timeout")
            self._status = ConnectionStatus.ERROR
            await self._cleanup_connect_failure()
            return False
                
        except Exception as e:
            logger.error(f"Feishu connect failed: {e}")
            self._status = ConnectionStatus.ERROR
            await self._cleanup_connect_failure()
            return False
    
    def _listen_for_messages(self):
        """Listen for messages from SDK process."""
        while self._running:
            try:
                # Non-blocking check with timeout
                try:
                    msg_data = self._message_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # Convert to InboundMessage
                inbound = InboundMessage(
                    message_id=msg_data["message_id"],
                    sender_id=msg_data["sender_id"],
                    sender_name="",
                    chat_id=msg_data["chat_id"],
                    channel_type=self.channel_type,
                    content=msg_data["content"],
                    content_type=msg_data["content_type"],
                    thread_id=None,
                    metadata={
                        "chat_type": msg_data["chat_type"],
                        "create_time": msg_data["create_time"],
                        "tenant_key": msg_data["tenant_key"],
                        "has_mention": msg_data.get("has_mention", False),
                    },
                )
                
                logger.info(f"Feishu message received: {inbound.message_id}")
                
                # Call callback
                if self._message_callback:
                    self._message_callback(inbound)
                else:
                    logger.warning("No message callback set for Feishu handler")
                    
            except Exception as e:
                logger.error(f"Error in message listener: {e}")
    
    async def disconnect(self) -> bool:
        """Disconnect and cleanup."""
        try:
            self._running = False
            
            if self._process and self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=5)
                print("[Feishu] SDK process terminated")
            
            self._process = None
            self._message_queue = None
            self._control_queue = None
            self._status = ConnectionStatus.DISCONNECTED
            logger.info("Feishu disconnected")
            return True
        except Exception as e:
            logger.error(f"Feishu disconnect failed: {e}")
            return False
    
    async def stop(self) -> bool:
        """Stop handler."""
        await self.disconnect()
        return True
    
    async def send_message(self, outbound: OutboundMessage) -> SendResult:
        """Send message to Feishu."""
        try:
            # Check if using Webhook mode
            webhook_url = self.config.get("webhook_url")
            if webhook_url:
                return await self._send_via_webhook(outbound, webhook_url)
            
            # Long connection mode - use API
            if not await self._refresh_access_token():
                return SendResult(success=False, error="Failed to get access token")
            
            url = f"{self.FEISHU_API_BASE}/im/v1/messages?receive_id_type=chat_id"
            
            payload = {
                "receive_id": outbound.chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": outbound.content}),
            }
            
            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            }
            
            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.post(url, json=payload, headers=headers) as response:

                    data = await response.json()
                    if data.get("code") == 0:
                        logger.info(f"Feishu message sent to {outbound.chat_id}")
                        return SendResult(
                            success=True,
                            message_id=data.get("data", {}).get("message_id")
                        )
                    else:
                        return SendResult(
                            success=False,
                            error=f"Feishu API error: {data.get('msg')}"
                        )
                        
        except Exception as e:
            logger.error(f"Failed to send Feishu message: {e}")
            return SendResult(success=False, error=str(e))
    
    async def _send_via_webhook(self, outbound: OutboundMessage, webhook_url: str) -> SendResult:
        """Send message via Webhook (custom bot)."""
        try:
            payload = {
                "msg_type": "text",
                "content": {"text": outbound.content}
            }
            
            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.post(webhook_url, json=payload) as response:

                    if response.status == 200:
                        data = await response.json()
                        if data.get("code") == 0 or data.get("StatusCode") == 0:
                            logger.info("Feishu webhook message sent")
                            return SendResult(success=True)
                        else:
                            return SendResult(
                                success=False,
                                error=f"Feishu webhook error: {data.get('msg', data.get('StatusMessage'))}"
                            )
                    else:
                        return SendResult(success=False, error=f"HTTP {response.status}")
        except Exception as e:
            logger.error(f"Failed to send Feishu webhook message: {e}")
            return SendResult(success=False, error=str(e))
    
    async def _refresh_access_token(self) -> bool:
        """Refresh Feishu access token."""
        try:
            # Check if token still valid
            if self._access_token and time.time() < self._token_expires_at - 60:
                return True
            
            payload = {
                "app_id": self.config.get("app_id"),
                "app_secret": self.config.get("app_secret"),
            }
            
            async with aiohttp.ClientSession(trust_env=True) as session:
                async with session.post(self.AUTH_URL, json=payload) as response:

                    data = await response.json()
                    if data.get("code") == 0:
                        self._access_token = data.get("tenant_access_token")
                        expire = data.get("expire", 7200)
                        self._token_expires_at = time.time() + expire
                        return True
            
            return False
        except Exception as e:
            logger.error(f"Failed to refresh Feishu access token: {e}")
            return False

    def _verify_webhook_security(
        self,
        *,
        headers: Dict[str, Any],
        payload: Dict[str, Any],
        raw_body: str,
    ) -> bool:
        """Verify Feishu webhook token/signature when configured."""
        verification_token = self.config.get("verification_token")
        if verification_token:
            incoming_token = payload.get("token")
            if incoming_token and not secrets.compare_digest(
                str(incoming_token), str(verification_token)
            ):
                logger.error("Feishu webhook verification token mismatch")
                return False

        encrypt_key = self.config.get("encrypt_key")
        if not encrypt_key:
            return True

        header_map = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        timestamp = header_map.get("x-lark-request-timestamp")
        nonce = header_map.get("x-lark-request-nonce")
        signature = header_map.get("x-lark-signature")
        if not (timestamp and nonce and signature):
            logger.error("Feishu webhook signature headers missing")
            return False

        digest = hashlib.sha256(
            (timestamp + nonce + str(encrypt_key)).encode("utf-8") + raw_body.encode("utf-8")
        ).hexdigest()
        if not secrets.compare_digest(digest, signature):
            logger.error("Feishu webhook signature verification failed")
            return False
        return True

    async def verify_webhook_request(self, request: Any) -> bool:
        """Verify raw Feishu webhook request before challenge/event processing."""
        if not isinstance(request, dict):
            return False
        body = request.get("body")
        if not isinstance(body, dict):
            return False
        headers = request.get("headers") if isinstance(request.get("headers"), dict) else {}
        raw_body = request.get("raw_body")
        if not isinstance(raw_body, str):
            raw_body = json.dumps(body, separators=(",", ":"))
        return self._verify_webhook_security(headers=headers, payload=body, raw_body=raw_body)
    
    async def handle_inbound(self, request: Any) -> Optional[InboundMessage]:
        """Handle incoming message (for webhook fallback)."""
        try:
            if isinstance(request, str):
                data = json.loads(request)
            else:
                data = request

            headers: Dict[str, Any] = {}
            raw_body = ""
            if isinstance(data, dict) and "body" in data:
                if isinstance(data.get("headers"), dict):
                    headers = data.get("headers")
                if isinstance(data.get("raw_body"), str):
                    raw_body = data.get("raw_body")
                body = data.get("body")
                if isinstance(body, str):
                    try:
                        body = json.loads(body)
                    except Exception:
                        body = {}
                if isinstance(body, dict):
                    data = body

            if not isinstance(data, dict):
                return None
            if not raw_body:
                raw_body = json.dumps(data, separators=(",", ":"))

            if not self._verify_webhook_security(headers=headers, payload=data, raw_body=raw_body):
                return None

            if "challenge" in data:
                return None

            event_type = data.get("header", {}).get("event_type", "")
            if event_type != "im.message.receive_v1":
                return None
            
            event_data = data.get("event", {})
            message = event_data.get("message", {})
            sender = event_data.get("sender", {})
            
            text, has_mention = _extract_text_and_mention(message.get("content", ""))
            
            return InboundMessage(
                message_id=message.get("message_id", ""),
                sender_id=sender.get("sender_id", {}).get("open_id", ""),
                sender_name="",
                chat_id=message.get("chat_id", ""),
                channel_type=self.channel_type,
                content=text,
                content_type="text",
                thread_id=None,
                metadata={
                    "chat_type": message.get("chat_type"),
                    "create_time": message.get("create_time"),
                    "has_mention": has_mention,
                },
            )
        except Exception as e:
            logger.error(f"Failed to handle Feishu inbound: {e}")
            return None
    
    async def validate_config(self, config: Dict[str, Any]) -> ChannelValidationResult:
        """Validate configuration."""
        errors = []
        
        if not isinstance(config, dict):
            errors.append("Config must be a dictionary")
            return ChannelValidationResult(valid=False, errors=errors)
        
        connection_mode = config.get("connection_mode", "longconnection")
        
        if connection_mode == "longconnection":
            if not config.get("app_id"):
                errors.append("app_id is required for Long Connection mode")
            if not config.get("app_secret"):
                errors.append("app_secret is required for Long Connection mode")
        elif connection_mode == "webhook":
            if not config.get("webhook_url"):
                errors.append("webhook_url is required for Webhook mode")
            token = config.get("verification_token")
            if token is not None and not str(token).strip():
                errors.append("verification_token must not be empty when provided")
            encrypt_key = config.get("encrypt_key")
            if encrypt_key is not None and not str(encrypt_key).strip():
                errors.append("encrypt_key must not be empty when provided")
        
        return ChannelValidationResult(valid=len(errors) == 0, errors=errors)
    
    def describe_schema(self) -> Dict[str, Any]:
        """Return configuration schema."""
        return {
            "type": "object",
            "title": "Feishu",
            "description": "Feishu bot configuration",
            "properties": {
                "connection_mode": {
                    "type": "string",
                    "title": "Connection Mode",
                    "description": "Select connection mode",
                    "enum": ["longconnection", "webhook"],
                    "enumLabels": {
                        "longconnection": "Long Connection (Enterprise App)",
                        "webhook": "Webhook (Custom Bot)"
                    },
                    "default": "longconnection",
                },
                "app_id": {
                    "type": "string",
                    "title": "App ID",
                    "description": "Feishu application App ID",
                    "placeholder": "cli_xxxxxxxxxx",
                    "showWhen": {"connection_mode": "longconnection"},
                },
                "app_secret": {
                    "type": "string",
                    "title": "App Secret",
                    "description": "Feishu application App Secret",
                    "placeholder": "Your app secret",
                    "showWhen": {"connection_mode": "longconnection"},
                },
                "webhook_url": {
                    "type": "string",
                    "title": "Webhook URL",
                    "description": "Custom bot Webhook address",
                    "placeholder": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
                    "showWhen": {"connection_mode": "webhook"},
                },
                "verification_token": {
                    "type": "string",
                    "title": "Verification Token",
                    "description": "Optional token to validate inbound webhook callbacks",
                    "placeholder": "Verification token configured on Feishu platform",
                    "showWhen": {"connection_mode": "webhook"},
                },
                "encrypt_key": {
                    "type": "string",
                    "title": "Encrypt Key",
                    "description": "Optional encrypt key for X-Lark-Signature verification",
                    "placeholder": "Encrypt key configured on Feishu platform",
                    "showWhen": {"connection_mode": "webhook"},
                },
                "require_at_mention_in_group": {
                    "type": "boolean",
                    "title": "Require @ Mention In Group",
                    "description": "Only process group messages when the bot is @mentioned",
                    "default": False,
                },
            },
            "required_by_mode": {
                "longconnection": ["app_id", "app_secret"],
                "webhook": ["webhook_url"]
            },
        }
