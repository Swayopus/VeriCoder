"""Feature tests for task 004 (shipping fee). Failing on the baseline repo."""

from api import create_app


def test_shipping_free_above_threshold_and_flat_below():
    client = create_app().test_client()

    big = client.post("/products", json={"name": "big", "price": 60, "stock": 5}).get_json()
    client.post("/cart/alice/items", json={"product_id": big["id"], "quantity": 1})
    free = client.post("/cart/alice/checkout").get_json()
    assert free["subtotal"] == 60.0
    assert free["shipping"] == 0.0
    assert free["total"] == 60.0

    small = client.post("/products", json={"name": "small", "price": 20, "stock": 5}).get_json()
    client.post("/cart/bob/items", json={"product_id": small["id"], "quantity": 1})
    paid = client.post("/cart/bob/checkout").get_json()
    assert paid["subtotal"] == 20.0
    assert paid["shipping"] == 5.0
    assert paid["total"] == 25.0
