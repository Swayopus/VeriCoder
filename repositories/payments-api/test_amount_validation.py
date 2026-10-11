"""Feature tests for task 005 (amount validation). Failing on the baseline repo."""

from api import create_app


def test_negative_deposit_is_rejected():
    client = create_app().test_client()
    account = client.post("/accounts", json={"owner": "alice", "initial_balance": 100.0}).get_json()
    response = client.post(f"/accounts/{account['id']}/deposit", json={"amount": -5.0})
    assert response.status_code == 400
    assert client.get(f"/accounts/{account['id']}").get_json()["balance"] == 100.0
