"""
WebSocket router + Redis subscriber.

The Redis subscriber coroutine runs as a background asyncio task (started
from main.py lifespan).  It listens on the Redis channel and calls
manager.broadcast() for every message, which fans out to all connected
WebSocket clients that pass their filter.
"""

import asyncio
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from metrics import BROADCAST_LATENCY
from pubsub.redis_broker import get_redis_client
from websocket.manager import manager
from config import settings

logger = logging.getLogger(__name__)

ws_router = APIRouter()


@ws_router.websocket("/orders")
async def websocket_orders(
    websocket: WebSocket,
    order_id: Optional[int] = Query(default=None, description="Subscribe to a specific order ID"),
    status: Optional[str] = Query(default=None, description="Subscribe to a specific status value"),
):
    """
    Connect to receive real-time order change events.

    Optional query params:
      ?order_id=<int>   — filter to a single order
      ?status=<string>  — filter to a specific status ('pending'|'shipped'|'delivered')

    On connect, the server sends an acknowledgement frame:
      {"type": "connected", "message": "...", "filters": {...}}

    Change events have this shape:
      {
        "event": "INSERT" | "UPDATE" | "DELETE",
        "table": "orders",
        "timestamp": <unix epoch int>,
        "server_received_at": <float>,
        "data": { "id": 1, "customer_name": "...", "product_name": "...",
                  "status": "...", "updated_at": "..." }
      }
    """
    conn_id = await manager.connect(websocket, order_id=order_id, status=status)
    try:
        await websocket.send_json({
            "type": "connected",
            "conn_id": conn_id,
            "message": "Subscribed to order changes",
            "filters": {"order_id": order_id, "status": status},
        })

        # Keep the connection open; client messages are ignored (read-only feed)
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WebSocket error for conn_id=%s: %s", conn_id, exc)
    finally:
        manager.disconnect(conn_id)


# ─────────────────────────────────────────────────────────────────
#  Redis subscriber — runs as a background asyncio task
# ─────────────────────────────────────────────────────────────────

async def start_redis_subscriber() -> None:
    """
    Subscribe to the Redis channel and broadcast every message to all
    connected WebSocket clients via the ConnectionManager.

    Runs forever; reconnects on transient Redis errors.
    """
    while True:
        try:
            await _subscribe_loop()
        except asyncio.CancelledError:
            logger.info("Redis subscriber cancelled.")
            raise
        except Exception as exc:
            logger.warning("Redis subscriber error (%s), reconnecting in 3 s…", exc)
            await asyncio.sleep(3)


async def _subscribe_loop() -> None:
    redis = get_redis_client()
    pubsub = redis.pubsub()
    await pubsub.subscribe(settings.REDIS_CHANNEL)
    logger.info("Redis subscriber ready on channel '%s'.", settings.REDIS_CHANNEL)

    async for raw_msg in pubsub.listen():
        if raw_msg["type"] != "message":
            continue
        try:
            data: dict = json.loads(raw_msg["data"])

            # Measure broadcast latency from when the DB notification arrived
            # at this server to when we're about to push it to clients.
            server_received_at: float = data.get("server_received_at", time.time())
            latency = time.time() - server_received_at
            BROADCAST_LATENCY.observe(latency)

            await manager.broadcast(data)

        except Exception:
            logger.exception("Error broadcasting Redis message: %s", raw_msg)
