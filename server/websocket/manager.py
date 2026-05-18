import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from fastapi import WebSocket

from metrics import ACTIVE_CONNECTIONS, WS_BROADCASTS

logger = logging.getLogger(__name__)


@dataclass
class ClientInfo:
    websocket: WebSocket
    order_id_filter: Optional[int] = None
    status_filter: Optional[str] = None


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: dict[str, ClientInfo] = {}

    async def connect(
        self,
        websocket: WebSocket,
        order_id: Optional[int] = None,
        status: Optional[str] = None,
    ) -> str:
        await websocket.accept()
        conn_id = str(uuid.uuid4())
        self._clients[conn_id] = ClientInfo(
            websocket=websocket,
            order_id_filter=order_id,
            status_filter=status,
        )
        ACTIVE_CONNECTIONS.inc()
        logger.info(
            "WebSocket connected | conn_id=%s | filters=order_id:%s status:%s | total=%d",
            conn_id, order_id, status, len(self._clients),
        )
        return conn_id

    def disconnect(self, conn_id: str) -> None:
        if conn_id in self._clients:
            del self._clients[conn_id]
            ACTIVE_CONNECTIONS.dec()
            logger.info(
                "WebSocket disconnected | conn_id=%s | remaining=%d",
                conn_id, len(self._clients),
            )

    async def broadcast(self, message: dict) -> None:
        """Send message to all connected clients that pass their own filter."""
        dead_connections: list[str] = []

        for conn_id, client in list(self._clients.items()):
            if not self._passes_filter(client, message):
                continue
            try:
                await client.websocket.send_json(message)
                WS_BROADCASTS.inc()
            except Exception as exc:
                logger.warning("Send failed for conn_id=%s (%s) — removing.", conn_id, exc)
                dead_connections.append(conn_id)

        for conn_id in dead_connections:
            self.disconnect(conn_id)

    @staticmethod
    def _passes_filter(client: ClientInfo, message: dict) -> bool:
        data = message.get("data") or {}

        if client.order_id_filter is not None:
            if data.get("id") != client.order_id_filter:
                return False

        if client.status_filter is not None:
            if data.get("status") != client.status_filter:
                return False

        return True

    @property
    def connection_count(self) -> int:
        return len(self._clients)


# Singleton — shared across the application
manager = ConnectionManager()
