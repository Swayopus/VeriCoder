"""Executable task contracts; each check runs outside the candidate process."""

from __future__ import annotations

from verifier.requirement_runner import run_python_check


def _run(repo_dir: str, code: str):
    return run_python_check(repo_dir, code, timeout=60)


def check_discount(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
p = client.post("/products", json={"name": "gadget", "price": 100, "stock": 5}).get_json()
client.post("/cart/alice/items", json={"product_id": p["id"], "quantity": 1})
r = client.post("/cart/alice/checkout")
assert r.status_code == 201, r.status_code
order = r.get_json()
assert order["subtotal"] == 100.0 and order["discount"] == 10.0 and order["total"] == 90.0, order
products = client.get("/products").get_json()["items"]
assert products[0]["stock"] == 4, products
assert client.get("/cart/alice").get_json()["items"] == []
""",
    )


def check_no_discount_below_threshold(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
p = client.post("/products", json={"name": "cheap", "price": 50, "stock": 5}).get_json()
client.post("/cart/bob/items", json={"product_id": p["id"], "quantity": 1})
order = client.post("/cart/bob/checkout").get_json()
assert order["discount"] == 0.0 and order["total"] == 50.0, order
""",
    )


def check_stock_guard(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
enough = client.post("/products", json={"name": "enough", "price": 10, "stock": 5}).get_json()
rare = client.post("/products", json={"name": "rare", "price": 10, "stock": 1}).get_json()
client.post("/cart/carol/items", json={"product_id": enough["id"], "quantity": 1})
client.post("/cart/carol/items", json={"product_id": rare["id"], "quantity": 3})
before_stock = client.get("/products").get_json()
before_cart = client.get("/cart/carol").get_json()
r = client.post("/cart/carol/checkout")
assert r.status_code == 409, r.status_code
assert client.get("/products").get_json() == before_stock
assert client.get("/cart/carol").get_json() == before_cart
for _ in range(2):
    client.post("/cart/duplicate/items", json={"product_id": rare["id"], "quantity": 1})
duplicate_cart = client.get("/cart/duplicate").get_json()
r = client.post("/cart/duplicate/checkout")
assert r.status_code == 409, r.status_code
assert client.get("/products").get_json() == before_stock
assert client.get("/cart/duplicate").get_json() == duplicate_cart
""",
    )


def check_tax(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
p = client.post("/products", json={"name": "widget", "price": 50, "stock": 5}).get_json()
client.post("/cart/alice/items", json={"product_id": p["id"], "quantity": 1})
order = client.post("/cart/alice/checkout").get_json()
assert order["subtotal"] == 50.0 and order["tax"] == 2.5 and order["total"] == 52.5, order
""",
    )


def check_tax_rounding(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
p = client.post("/products", json={"name": "odd", "price": 33.33, "stock": 5}).get_json()
client.post("/cart/alice/items", json={"product_id": p["id"], "quantity": 1})
order = client.post("/cart/alice/checkout").get_json()
assert order["subtotal"] == 33.33 and order["tax"] == 1.67 and order["total"] == 35.0, order
""",
    )


def check_coupon_applied(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
p = client.post("/products", json={"name": "widget", "price": 50, "stock": 5}).get_json()
client.post("/cart/alice/items", json={"product_id": p["id"], "quantity": 1})
order = client.post("/cart/alice/checkout", json={"coupon": "SAVE10"}).get_json()
assert order["subtotal"] == 50.0 and order["discount"] == 5.0 and order["total"] == 45.0, order
""",
    )


def check_unknown_coupon_ignored(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
p = client.post("/products", json={"name": "widget", "price": 50, "stock": 5}).get_json()
for user, payload in [("alice", {"coupon": "NOPE"}), ("bob", {})]:
    client.post(f"/cart/{user}/items", json={"product_id": p["id"], "quantity": 1})
    order = client.post(f"/cart/{user}/checkout", json=payload).get_json()
    assert order["subtotal"] == 50.0 and order["discount"] == 0.0 and order["total"] == 50.0, order
""",
    )


def check_free_shipping(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
for user, price, fee in [("big", 60, 0.0), ("small", 20, 5.0)]:
    p = client.post("/products", json={"name": user, "price": price, "stock": 5}).get_json()
    client.post(f"/cart/{user}/items", json={"product_id": p["id"], "quantity": 1})
    order = client.post(f"/cart/{user}/checkout").get_json()
    assert order["subtotal"] == price and order["shipping"] == fee and order["total"] == price + fee, order
""",
    )


def check_shipping_threshold(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
p = client.post("/products", json={"name": "exact", "price": 50, "stock": 5}).get_json()
client.post("/cart/alice/items", json={"product_id": p["id"], "quantity": 1})
order = client.post("/cart/alice/checkout").get_json()
assert order["subtotal"] == 50.0 and order["shipping"] == 0.0 and order["total"] == 50.0, order
""",
    )


def check_restock(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
p = client.post("/products", json={"name": "widget", "price": 10, "stock": 2}).get_json()
r = client.post(f"/products/{p['id']}/restock", json={"quantity": 3})
assert r.status_code == 200, r.status_code
assert r.get_json()["stock"] == 5, r.get_json()
assert client.get("/products").get_json()["items"][0]["stock"] == 5
""",
    )


def check_restock_validation(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
p = client.post("/products", json={"name": "widget", "price": 10, "stock": 2}).get_json()
for value in [0, -2, "three", None, True, 1.5]:
    r = client.post(f"/products/{p['id']}/restock", json={"quantity": value})
    assert r.status_code == 400, (value, r.status_code)
    assert client.get("/products").get_json()["items"][0]["stock"] == 2
""",
    )
