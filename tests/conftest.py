"""
pytest configuration and shared fixtures.

Run the full suite:
    pytest tests/ -v

Run only the fast unit tests (no DB/Redis needed):
    pytest tests/test_connection_manager.py -v

Run the API integration tests (requires a running server):
    pytest tests/test_orders_api.py -v
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
import httpx

# ── Unit test fixtures ─────────────────────────────────────────────

@pytest.fixture
def mock_websocket():
    """A lightweight fake WebSocket for ConnectionManager tests."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


# ── Integration test fixtures ──────────────────────────────────────

@pytest.fixture(scope="session")
def api_base_url():
    """Base URL for the running server. Override via PYTEST_BASE_URL env var."""
    import os
    return os.getenv("PYTEST_BASE_URL", "http://localhost:8000")
