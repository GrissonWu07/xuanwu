# -*- coding: utf-8 -*-
"""Channel webhook routes for receiving messages from external platforms."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.xuanwu.channels.registry import ChannelRegistry
from app.xuanwu.channels.manager import ChannelManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/channel-hooks", tags=["channel-hooks"])

_channel_manager: Optional[ChannelManager] = None


def set_channel_manager(manager: Optional[ChannelManager]) -> None:
    """Set channel manager instance."""
    global _channel_manager
    _channel_manager = manager


def get_channel_manager() -> Optional[ChannelManager]:
    """Get channel manager instance if initialized."""
    return _channel_manager


@router.post("/{channel_type}/{connection_id}")
async def receive_channel_webhook(
    channel_type: str,
    connection_id: str,
    request: Request
) -> JSONResponse:
    """Receive webhook from external channel platform.
    
    Args:
        channel_type: Channel type (e.g., feishu, slack)
        connection_id: Connection identifier
        request: FastAPI request object
        
    Returns:
        JSON response
    """
    try:
        handler_class = ChannelRegistry.get(channel_type)
        if not handler_class:
            logger.error(f"Channel type not found: {channel_type}")
            raise HTTPException(status_code=404, detail=f"Channel type not found: {channel_type}")

        # Parse request body
        body = await request.body()
        content_type = request.headers.get("content-type", "")

        if "application/json" in content_type:
            try:
                data = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON payload")
        else:
            data = {"body": body.decode("utf-8")}

        # Add request metadata
        request_data = {
            "headers": dict(request.headers),
            "query_params": dict(request.query_params),
            "body": data,
            "raw_body": body.decode("utf-8", errors="ignore"),
        }

        # Some platforms (including Feishu) send challenge in POST body.
        if isinstance(data, dict) and "challenge" in data:
            manager = get_channel_manager()
            if manager is not None and channel_type == "feishu":
                verified = await manager.verify_webhook_request(
                    channel_type,
                    connection_id,
                    request_data,
                )
                if not verified:
                    raise HTTPException(status_code=401, detail="Webhook signature verification failed")
            return JSONResponse(content={"challenge": data["challenge"]})

        manager = get_channel_manager()
        if manager is not None:
            inbound = await manager.route_inbound_message(channel_type, connection_id, request_data)
        else:
            # Backward-compatible fallback for isolated tests.
            handler = ChannelRegistry.get_instance(connection_id)
            if not handler:
                logger.warning(f"Handler instance not found for: {connection_id}")
                raise HTTPException(status_code=404, detail=f"Connection not found: {connection_id}")
            inbound = await handler.handle_inbound(request_data)

        if not inbound:
            logger.warning(f"Failed to parse inbound message from {channel_type}")
            raise HTTPException(status_code=400, detail="Invalid message format")

        return JSONResponse(content={"status": "ok", "message_id": inbound.message_id})
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to handle channel webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{channel_type}/{connection_id}")
async def verify_channel_webhook(
    channel_type: str,
    connection_id: str,
    request: Request
) -> JSONResponse:
    """Verify webhook endpoint (for platforms that require verification).
    
    Args:
        channel_type: Channel type
        connection_id: Connection identifier
        request: FastAPI request object
        
    Returns:
        JSON response
    """
    try:
        # Some platforms (like Feishu) require challenge verification
        params = dict(request.query_params)
        
        if "challenge" in params:
            # Return challenge for verification
            return JSONResponse(content={"challenge": params["challenge"]})
        
        return JSONResponse(content={"status": "ok"})
        
    except Exception as e:
        logger.error(f"Failed to verify webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))
