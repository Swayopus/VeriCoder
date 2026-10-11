"""Feature tests for task 002 (sales tax). Failing on the baseline repo."""

from api import create_app


def test_tax_added_to_total():
    client = create_app().test_client()
    product = client.post("/products", json={"name": "widget", "price": 50, "stock": 5}).get_json()
    client.post("/cart/alice/items", json={"product_id": product["id"], "quantity": 1})
    order = client.post("/cart/alice/checkout").get_json()
    assert order["subtotal"] == 50.0
    assert order["tax"] == 2.5
    assert order["total"] == 52.5
