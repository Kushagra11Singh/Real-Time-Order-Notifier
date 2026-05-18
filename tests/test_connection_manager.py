import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from websocket.manager import ConnectionManager, ClientInfo


# ── Helpers ────────────────────────────────────────────────────────

def make_client(order_id=None, status=None):
    """Build a ClientInfo with a mock WebSocket."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    return ClientInfo(websocket=ws, order_id_filter=order_id, status_filter=status)


def order_event(order_id=1, status="pending", event="INSERT"):
    return {
        "event": event,
        "table": "orders",
        "data": {"id": order_id, "status": status},
    }


# ── _passes_filter unit tests ──────────────────────────────────────

class TestPassesFilter:
    def test_no_filters_accepts_all_events(self):
        client = make_client()
        assert ConnectionManager._passes_filter(client, order_event(order_id=1, status="pending"))
        assert ConnectionManager._passes_filter(client, order_event(order_id=99, status="delivered"))

    def test_order_id_filter_passes_matching_id(self):
        client = make_client(order_id=5)
        assert ConnectionManager._passes_filter(client, order_event(order_id=5))

    def test_order_id_filter_blocks_other_ids(self):
        client = make_client(order_id=5)
        assert not ConnectionManager._passes_filter(client, order_event(order_id=6))
        assert not ConnectionManager._passes_filter(client, order_event(order_id=1))

    def test_status_filter_passes_matching_status(self):
        client = make_client(status="shipped")
        assert ConnectionManager._passes_filter(client, order_event(status="shipped"))

    def test_status_filter_blocks_other_statuses(self):
        client = make_client(status="shipped")
        assert not ConnectionManager._passes_filter(client, order_event(status="pending"))
        assert not ConnectionManager._passes_filter(client, order_event(status="delivered"))

    def test_combined_filters_both_must_match(self):
        client = make_client(order_id=3, status="delivered")
        # Both match → passes
        assert ConnectionManager._passes_filter(client, order_event(order_id=3, status="delivered"))
        # Only order_id matches → blocked
        assert not ConnectionManager._passes_filter(client, order_event(order_id=3, status="pending"))
        # Only status matches → blocked
        assert not ConnectionManager._passes_filter(client, order_event(order_id=7, status="delivered"))

    def test_missing_data_key_blocks_filtered_client(self):
        """If the event has no 'data' field, filtered clients should not receive it."""
        client = make_client(order_id=1)
        assert not ConnectionManager._passes_filter(client, {"event": "INSERT"})

    def test_missing_data_key_passes_unfiltered_client(self):
        """An unfiltered client should still receive events even without a data field."""
        client = make_client()
        assert ConnectionManager._passes_filter(client, {"event": "INSERT"})

    def test_delete_event_passes_order_id_filter(self):
        """DELETE events carry the old row — filter should still work."""
        client = make_client(order_id=10)
        assert ConnectionManager._passes_filter(client, order_event(order_id=10, event="DELETE"))
        assert not ConnectionManager._passes_filter(client, order_event(order_id=11, event="DELETE"))


# ── ConnectionManager lifecycle tests ─────────────────────────────

@pytest.mark.asyncio
async def test_connect_increments_client_count():
    mgr = ConnectionManager()
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    assert mgr.connection_count == 0
    conn_id = await mgr.connect(ws)
    assert mgr.connection_count == 1
    assert isinstance(conn_id, str) and len(conn_id) == 36  # UUID format


@pytest.mark.asyncio
async def test_disconnect_decrements_client_count():
    mgr = ConnectionManager()
    ws = MagicMock()
    ws.accept = AsyncMock()
    conn_id = await mgr.connect(ws)
    assert mgr.connection_count == 1
    mgr.disconnect(conn_id)
    assert mgr.connection_count == 0


@pytest.mark.asyncio
async def test_disconnect_unknown_id_is_safe():
    mgr = ConnectionManager()
    # Should not raise even with a garbage ID
    mgr.disconnect("not-a-real-id")


@pytest.mark.asyncio
async def test_broadcast_delivers_to_matching_client():
    mgr = ConnectionManager()
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    await mgr.connect(ws, order_id=7)

    event = order_event(order_id=7, status="shipped")
    await mgr.broadcast(event)
    ws.send_json.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_broadcast_does_not_deliver_to_filtered_out_client():
    mgr = ConnectionManager()
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    await mgr.connect(ws, order_id=99)

    await mgr.broadcast(order_event(order_id=1))
    ws.send_json.assert_not_called()
