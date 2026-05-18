
"""
simulate.py — Seeds the database and simulates a realistic order lifecycle.

Run this while the server is up to watch the browser client light up.

Usage:
    python scripts/simulate.py                      # default: localhost:8000
    python scripts/simulate.py --host localhost --port 8000
    python scripts/simulate.py --seed-only          # just insert orders, no updates

What it does:
  1. Creates a batch of realistic-looking orders.
  2. Advances each order through pending → shipped → delivered over time.
  3. Occasionally deletes a cancelled order.
  4. Loops indefinitely so you can keep the demo running.
"""

import argparse
import asyncio
import random
import time

import httpx

CUSTOMERS = [
    "Priya Sharma", "Arjun Patel", "Neha Verma", "Rahul Gupta",
    "Ananya Nair", "Vikram Singh", "Deepika Joshi", "Karan Mehta",
    "Sunita Reddy", "Aditya Kumar",
]

PRODUCTS = [
    "Mechanical Keyboard", "Noise-Cancelling Headphones", "USB-C Hub",
    "Portable SSD 1TB", "Webcam 4K", "Standing Desk Mat",
    "Monitor Arm", "RGB Mouse Pad", "Laptop Stand", "Smart Bulb Pack",
]

LIFECYCLE = ["pending", "shipped", "delivered"]


async def create_order(client: httpx.AsyncClient, base_url: str) -> dict | None:
    customer = random.choice(CUSTOMERS)
    product  = random.choice(PRODUCTS)
    try:
        r = await client.post(
            f"{base_url}/api/orders/",
            json={"customer_name": customer, "product_name": product, "status": "pending"},
            timeout=5,
        )
        r.raise_for_status()
        order = r.json()
        print(f"  [CREATE]  #{order['id']:>4}  {customer:<20}  {product}")
        return order
    except Exception as e:
        print(f"  [ERROR]   create_order failed: {e}")
        return None


async def advance_order(client: httpx.AsyncClient, base_url: str, order: dict) -> None:
    """Walk the order through its full lifecycle with realistic delays."""
    for status in ["shipped", "delivered"]:
        await asyncio.sleep(random.uniform(3, 7))
        try:
            r = await client.patch(
                f"{base_url}/api/orders/{order['id']}",
                json={"status": status},
                timeout=5,
            )
            r.raise_for_status()
            print(f"  [UPDATE]  #{order['id']:>4}  status → {status}")
        except Exception as e:
            print(f"  [ERROR]   advance_order #{order['id']} failed: {e}")
            return


async def delete_order(client: httpx.AsyncClient, base_url: str, order_id: int) -> None:
    try:
        r = await client.delete(f"{base_url}/api/orders/{order_id}", timeout=5)
        r.raise_for_status()
        print(f"  [DELETE]  #{order_id:>4}  (cancelled)")
    except Exception as e:
        print(f"  [ERROR]   delete_order #{order_id} failed: {e}")


async def run(base_url: str, seed_only: bool) -> None:
    print(f"\nConnecting to {base_url} …\n")
    async with httpx.AsyncClient() as client:
        # Wait for server to be ready
        for attempt in range(10):
            try:
                r = await client.get(f"{base_url}/health", timeout=3)
                if r.status_code == 200:
                    print("Server is up.\n")
                    break
            except Exception:
                pass
            print(f"  Waiting for server… (attempt {attempt + 1}/10)")
            await asyncio.sleep(2)
        else:
            print("Could not reach server. Is it running?")
            return

        round_num = 0
        while True:
            round_num += 1
            print(f"\n── Round {round_num} ──────────────────────────────────────────")

            # Create a small batch of orders
            batch_size = random.randint(2, 4)
            orders = []
            for _ in range(batch_size):
                order = await create_order(client, base_url)
                if order:
                    orders.append(order)
                await asyncio.sleep(random.uniform(0.5, 1.5))

            if seed_only:
                print("\n--seed-only flag set, exiting after first batch.")
                return

            # Advance all orders in the batch concurrently
            tasks = [advance_order(client, base_url, o) for o in orders]

            # Occasionally cancel (delete) one order mid-lifecycle
            if orders and random.random() < 0.25:
                cancel_target = random.choice(orders)
                orders_to_advance = [o for o in orders if o["id"] != cancel_target["id"]]
                tasks = [advance_order(client, base_url, o) for o in orders_to_advance]
                await asyncio.sleep(random.uniform(1, 3))
                await delete_order(client, base_url, cancel_target["id"])

            await asyncio.gather(*tasks)
            pause = random.uniform(5, 10)
            print(f"\n  Sleeping {pause:.0f}s before next round…")
            await asyncio.sleep(pause)


def main():
    parser = argparse.ArgumentParser(description="Order simulation script")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", default="8000")
    parser.add_argument("--seed-only", action="store_true")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    try:
        asyncio.run(run(base_url, args.seed_only))
    except KeyboardInterrupt:
        print("\nSimulation stopped.")


if __name__ == "__main__":
    main()
