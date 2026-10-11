"""Feature tests for task 001 (basket discount). Failing on the baseline repo."""

from api import create_app


def test_discount_applied_at_threshold():
    client = create_app().test_client()
    product = client.post("/products", json={"name": "gadget", "price": 100, "stock": 5}).get_json()
    client.post("/cart/alice/items", json={"product_id": product["id"], "quantity": 1})
    order = client.post("/cart/alice/checkout").get_json()
    assert order["subtotal"] == 100.0
    assert order["discount"] == 10.0
    assert order["total"] == 90.0
