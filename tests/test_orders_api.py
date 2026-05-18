import pytest
import httpx


# ── Shared fixture ─────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client(api_base_url):
    """Synchronous httpx client for the duration of this test module."""
    with httpx.Client(base_url=api_base_url, timeout=10) as c:
        yield c


def create_test_order(client, customer="Test Customer", product="Test Product", status="pending"):
    """Helper: create an order and return the response JSON."""
    r = client.post("/api/orders/", json={
        "customer_name": customer,
        "product_name": product,
        "status": status,
    })
    r.raise_for_status()
    return r.json()


def cleanup(client, order_id):
    """Best-effort cleanup — ignore 404 if already deleted."""
    client.delete(f"/api/orders/{order_id}")


# ── Health check ───────────────────────────────────────────────────

def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"


# ── CREATE ─────────────────────────────────────────────────────────

def test_create_order_returns_201(client):
    r = client.post("/api/orders/", json={
        "customer_name": "Ananya Nair",
        "product_name": "USB-C Hub",
        "status": "pending",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["customer_name"] == "Ananya Nair"
    assert body["status"] == "pending"
    assert "id" in body
    cleanup(client, body["id"])


def test_create_order_default_status_is_pending(client):
    r = client.post("/api/orders/", json={
        "customer_name": "Rahul Gupta",
        "product_name": "Webcam 4K",
        # status omitted — should default to 'pending'
    })
    assert r.status_code == 201
    assert r.json()["status"] == "pending"
    cleanup(client, r.json()["id"])


def test_create_order_with_valid_status(client):
    for status in ["pending", "shipped", "delivered"]:
        r = client.post("/api/orders/", json={
            "customer_name": "Test",
            "product_name": "Item",
            "status": status,
        })
        assert r.status_code == 201, f"Failed for status={status}"
        cleanup(client, r.json()["id"])


def test_create_order_rejects_invalid_status(client):
    r = client.post("/api/orders/", json={
        "customer_name": "Test",
        "product_name": "Item",
        "status": "flying",  # not a valid status
    })
    assert r.status_code == 422


# ── READ ───────────────────────────────────────────────────────────

def test_list_orders_returns_200(client):
    r = client.get("/api/orders/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_order_by_id(client):
    order = create_test_order(client)
    r = client.get(f"/api/orders/{order['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == order["id"]
    cleanup(client, order["id"])


def test_get_nonexistent_order_returns_404(client):
    r = client.get("/api/orders/999999999")
    assert r.status_code == 404


# ── UPDATE ─────────────────────────────────────────────────────────

def test_patch_order_status(client):
    order = create_test_order(client)
    r = client.patch(f"/api/orders/{order['id']}", json={"status": "shipped"})
    assert r.status_code == 200
    assert r.json()["status"] == "shipped"
    cleanup(client, order["id"])


def test_patch_order_customer_name(client):
    order = create_test_order(client, customer="Old Name")
    r = client.patch(f"/api/orders/{order['id']}", json={"customer_name": "New Name"})
    assert r.status_code == 200
    assert r.json()["customer_name"] == "New Name"
    cleanup(client, order["id"])


def test_patch_with_no_fields_returns_400(client):
    order = create_test_order(client)
    r = client.patch(f"/api/orders/{order['id']}", json={})
    assert r.status_code == 400
    cleanup(client, order["id"])


def test_patch_nonexistent_order_returns_404(client):
    r = client.patch("/api/orders/999999999", json={"status": "shipped"})
    assert r.status_code == 404


def test_patch_invalid_status_returns_422(client):
    order = create_test_order(client)
    r = client.patch(f"/api/orders/{order['id']}", json={"status": "lost_in_transit"})
    assert r.status_code == 422
    cleanup(client, order["id"])


# ── DELETE ─────────────────────────────────────────────────────────

def test_delete_order_returns_204(client):
    order = create_test_order(client)
    r = client.delete(f"/api/orders/{order['id']}")
    assert r.status_code == 204


def test_delete_makes_order_unfetchable(client):
    order = create_test_order(client)
    client.delete(f"/api/orders/{order['id']}")
    r = client.get(f"/api/orders/{order['id']}")
    assert r.status_code == 404


def test_delete_nonexistent_order_returns_404(client):
    r = client.delete("/api/orders/999999999")
    assert r.status_code == 404
