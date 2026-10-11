"""Feature tests for task 007 (currency support). Failing on the baseline repo."""

from api import create_app


def test_same_currency_transfer_works():
    client = create_app().test_client()
    src = client.post(
        "/accounts", json={"owner": "alice", "initial_balance": 100.0, "currency": "USD"}
    ).get_json()
    dst = client.post("/accounts", json={"owner": "bob", "currency": "USD"}).get_json()
    response = client.post(
        "/transfers",
        json={"from": src["id"], "to": dst["id"], "amount": 30.0},
    )
    assert response.status_code == 201
