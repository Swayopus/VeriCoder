"""Feature tests for task 005 (restock). Failing on the baseline repo."""

from api import create_app


def test_restock_increases_stock():
    client = create_app().test_client()
    product = client.post("/products", json={"name": "widget", "price": 10, "stock": 2}).get_json()
    response = client.post(f"/products/{product['id']}/restock", json={"quantity": 3})
    assert response.status_code == 200
    assert response.get_json()["stock"] == 5
