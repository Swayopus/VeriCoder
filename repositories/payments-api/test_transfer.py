"""Feature tests for task 001 (transfers). Failing on the baseline repo."""

from api import create_app


def test_transfer_moves_funds():
    client = create_app().test_client()
    src = client.post("/accounts", json={"owner": "alice", "initial_balance": 100.0}).get_json()
    dst = client.post("/accounts", json={"owner": "bob"}).get_json()
    response = client.post(
        "/transfers",
        json={"from": src["id"], "to": dst["id"], "amount": 30.0},
    )
    assert response.status_code == 201
    assert client.get(f"/accounts/{src['id']}").get_json()["balance"] == 70.0
    assert client.get(f"/accounts/{dst['id']}").get_json()["balance"] == 30.0
