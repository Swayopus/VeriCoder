"""Feature tests for task 004 (ledger pagination). Failing on the baseline repo."""

from api import create_app


def test_pagination_returns_total_and_window():
    client = create_app().test_client()
    account = client.post("/accounts", json={"owner": "alice"}).get_json()
    for _ in range(5):
        client.post(f"/accounts/{account['id']}/deposit", json={"amount": 10.0})
    response = client.get(f"/accounts/{account['id']}/transactions?page=2&limit=2")
    assert response.status_code == 200
    body = response.get_json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["page"] == 2
    assert body["limit"] == 2
