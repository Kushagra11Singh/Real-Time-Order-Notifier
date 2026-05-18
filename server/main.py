import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from prometheus_client import make_asgi_app

from config import settings
from db.connection import create_db_pool, close_db_pool
from db.listener import start_db_listener
from pubsub.redis_broker import get_redis, close_redis
from websocket.router import ws_router, start_redis_subscriber
from api.orders import orders_router

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

_background_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────
    await create_db_pool()
    await get_redis()

    _background_tasks.append(asyncio.create_task(start_db_listener(), name="db-listener"))
    _background_tasks.append(asyncio.create_task(start_redis_subscriber(), name="redis-subscriber"))

    logger.info("Service started — listening for DB changes.")
    yield

    # ── Shutdown ──────────────────────────────────────────────────
    for task in _background_tasks:
        task.cancel()
    await asyncio.gather(*_background_tasks, return_exceptions=True)

    await close_db_pool()
    await close_redis()
    logger.info("Service stopped cleanly.")


app = FastAPI(
    title="Realtime Order Notifier",
    description=(
        "CDC pipeline: PostgreSQL LISTEN/NOTIFY → Redis Pub/Sub → WebSockets. "
        "Any INSERT, UPDATE, or DELETE on the orders table is pushed to all "
        "connected clients within milliseconds — zero polling at any layer."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request ID middleware ──────────────────────────────────────────
# Reads X-Request-ID from the incoming request (so callers can correlate
# their logs with ours) or mints a new UUID if one wasn't provided.
# The ID is echoed back in the response header and stored on request.state
# so handlers can include it in their audit log entries.
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ── Routers ────────────────────────────────────────────────────────
app.include_router(orders_router, prefix="/api/orders", tags=["Orders"])
app.include_router(ws_router, prefix="/ws", tags=["WebSocket"])

# ── Prometheus metrics scrape endpoint ────────────────────────────
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# ── Health probe (used by Docker / load balancer) ─────────────────
@app.get("/health", tags=["Infra"])
async def health():
    return {"status": "ok", "version": "1.0.0"}


# ── Serve the demo browser client ─────────────────────────────────
CLIENT_DIR = os.path.join(os.path.dirname(__file__), "..", "client")

@app.get("/", include_in_schema=False)
async def serve_client():
    return FileResponse(os.path.join(CLIENT_DIR, "index.html"))
