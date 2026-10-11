"""Feature tests for task 002 (transaction ledger). Failing on the baseline repo."""

from api import create_app


def test_deposit_records_ledger_entry():
    client = create_app().test_client()
    account = client.post("/accounts", json={"owner": "alice"}).get_json()
    client.post(f"/accounts/{account['id']}/deposit", json={"amount": 50.0})
    response = client.get(f"/accounts/{account['id']}/transactions")
    assert response.status_code == 200
    body = response.get_json()
    assert body["total"] == 1
    entry = body["items"][0]
    assert entry["amount"] == 50.0
    assert entry["balance_after"] == 50.0
