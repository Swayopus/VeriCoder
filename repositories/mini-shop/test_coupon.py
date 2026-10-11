"""Feature tests for task 003 (coupon codes). Failing on the baseline repo."""

from api import create_app


def test_save10_coupon_discount():
    client = create_app().test_client()
    product = client.post("/products", json={"name": "widget", "price": 50, "stock": 5}).get_json()
    client.post("/cart/alice/items", json={"product_id": product["id"], "quantity": 1})
    order = client.post("/cart/alice/checkout", json={"coupon": "SAVE10"}).get_json()
    assert order["subtotal"] == 50.0
    assert order["discount"] == 5.0
    assert order["total"] == 45.0
