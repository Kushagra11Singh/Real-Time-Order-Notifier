"""
DB Listener — the part that makes everything else work.

A single dedicated asyncpg connection (NOT from the pool) issues LISTEN
on the PostgreSQL channel.  Every NOTIFY fired by the trigger calls
`_on_notify`, which immediately publishes the payload to Redis.

Why a dedicated connection and not a pooled one?
LISTEN state is per-connection.  A pooled connection that carries a LISTEN
registration can silently receive notifications during unrelated queries —
messy to debug and easy to miss in testing. Dedicated is just cleaner.
"""

import asyncio
import json
import logging
import time

import asyncpg

from config import settings
from metrics import DB_NOTIFICATIONS_RECEIVED, REDIS_PUBLISHES
from pubsub.redis_broker import get_redis_client

logger = logging.getLogger(__name__)


async def start_db_listener() -> None:
    """Blocking coroutine — run as an asyncio background task."""
    while True:
        try:
            await _listen_loop()
        except (asyncpg.PostgresConnectionStatusError, OSError) as exc:
            # Transient connection failure — back off and retry
            logger.warning("DB listener lost connection (%s), reconnecting in 5 s…", exc)
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("DB listener cancelled.")
            raise


async def _listen_loop() -> None:
    conn: asyncpg.Connection = await asyncpg.connect(dsn=settings.DATABASE_URL)
    logger.info("DB listener connected, registering LISTEN on '%s'…", settings.PG_NOTIFY_CHANNEL)

    await conn.add_listener(settings.PG_NOTIFY_CHANNEL, _on_notify)
    logger.info("Listening for order changes.")

    try:
        while True:
            # keepalive — cloud proxies/firewalls kill idle connections after ~60s
            await asyncio.sleep(settings.PG_KEEPALIVE_INTERVAL)
            await conn.execute("SELECT 1")
    except asyncio.CancelledError:
        raise
    finally:
        await conn.remove_listener(settings.PG_NOTIFY_CHANNEL, _on_notify)
        await conn.close()


def _on_notify(
    connection: asyncpg.Connection,
    pid: int,
    channel: str,
    payload: str,
) -> None:
    """
    Called synchronously by asyncpg whenever a NOTIFY arrives.
    We schedule an async publish coroutine on the running event loop
    so we don't block the notification callback.
    """
    try:
        data = json.loads(payload)
        event_type = data.get("event", "UNKNOWN")
        DB_NOTIFICATIONS_RECEIVED.labels(event_type=event_type).inc()
        logger.info(
            "NOTIFY received | event=%s | order_id=%s",
            event_type,
            data.get("data", {}).get("id"),
        )
        # Inject the server-side receive timestamp so clients can measure
        # end-to-end latency if they wish.
        data["server_received_at"] = time.time()

        loop = asyncio.get_event_loop()
        loop.create_task(_publish_to_redis(data))
    except Exception:
        logger.exception("Error processing NOTIFY payload: %s", payload)


async def _publish_to_redis(data: dict) -> None:
    redis = get_redis_client()
    await redis.publish(settings.REDIS_CHANNEL, json.dumps(data))
    REDIS_PUBLISHES.inc()
