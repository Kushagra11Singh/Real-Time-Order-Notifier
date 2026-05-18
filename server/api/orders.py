
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from db.connection import get_pool

logger = logging.getLogger(__name__)

# Separate logger for audit events — makes it easy to route to a different
# handler (file, external SIEM, etc.) without touching the app logger config.
audit_logger = logging.getLogger("audit")

orders_router = APIRouter()

VALID_STATUSES = {"pending", "shipped", "delivered"}


# ── Helpers ────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit(event: str, order_id: int, request_id: str, extra: dict | None = None) -> None:
    """Emit a structured audit log entry.

    Format is kept as a flat dict for easy parsing by log aggregators.
    Example output:
        AUDIT | ORDER_CREATED | order_id=12 | request_id=abc-123 | status=pending
    """
    parts = [f"order_id={order_id}", f"request_id={request_id}"]
    if extra:
        parts.extend(f"{k}={v}" for k, v in extra.items())
    audit_logger.info("AUDIT | %s | %s | timestamp=%s", event, " | ".join(parts), _now_iso())


# ── Pydantic models ────────────────────────────────────────────────

class OrderCreate(BaseModel):
    customer_name: str
    product_name: str
    status: str = "pending"

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}")
        return v


class OrderUpdate(BaseModel):
    customer_name: Optional[str] = None
    product_name: Optional[str] = None
    status: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}")
        return v


# ── Endpoints ──────────────────────────────────────────────────────

@orders_router.get("/")
async def list_orders():
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, customer_name, product_name, status, updated_at FROM orders ORDER BY id DESC"
        )
    return [dict(row) for row in rows]


@orders_router.get("/{order_id}")
async def get_order(order_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, customer_name, product_name, status, updated_at FROM orders WHERE id = $1",
            order_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    return dict(row)


@orders_router.post("/", status_code=201)
async def create_order(payload: OrderCreate, request: Request):
    request_id = getattr(request.state, "request_id", "—")
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO orders (customer_name, product_name, status, updated_at)
            VALUES ($1, $2, $3, NOW())
            RETURNING id, customer_name, product_name, status, updated_at
            """,
            payload.customer_name,
            payload.product_name,
            payload.status,
        )
    logger.info("Order created: id=%d customer=%s", row["id"], payload.customer_name)
    _audit(
        "ORDER_CREATED",
        row["id"],
        request_id,
        {"customer": payload.customer_name, "product": payload.product_name, "status": payload.status},
    )
    return dict(row)


@orders_router.patch("/{order_id}")
async def update_order(order_id: int, payload: OrderUpdate, request: Request):
    request_id = getattr(request.state, "request_id", "—")
    pool = get_pool()

    # Build the SET clause dynamically from provided fields only
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clauses = []
    values = []
    for i, (key, value) in enumerate(updates.items(), start=1):
        set_clauses.append(f"{key} = ${i}")
        values.append(value)

    # Always bump updated_at
    set_clauses.append(f"updated_at = NOW()")
    values.append(order_id)

    query = f"""
        UPDATE orders
        SET {', '.join(set_clauses)}
        WHERE id = ${len(values)}
        RETURNING id, customer_name, product_name, status, updated_at
    """

    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *values)

    if not row:
        raise HTTPException(status_code=404, detail="Order not found")

    logger.info("Order updated: id=%d status=%s", row["id"], row["status"])
    _audit("ORDER_UPDATED", order_id, request_id, dict(updates))
    return dict(row)


@orders_router.delete("/{order_id}", status_code=204)
async def delete_order(order_id: int, request: Request):
    request_id = getattr(request.state, "request_id", "—")
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM orders WHERE id = $1", order_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Order not found")
    logger.info("Order deleted: id=%d", order_id)
    _audit("ORDER_DELETED", order_id, request_id)
