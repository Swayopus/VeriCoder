"""Feature tests for task 006 (account statement). Failing on the baseline repo."""

from api import create_app


def test_statement_reports_inflow_and_outflow():
    client = create_app().test_client()
    src = client.post("/accounts", json={"owner": "alice", "initial_balance": 100.0}).get_json()
    dst = client.post("/accounts", json={"owner": "bob"}).get_json()
    client.post(f"/accounts/{src['id']}/deposit", json={"amount": 100.0})
    client.post("/transfers", json={"from": src["id"], "to": dst["id"], "amount": 40.0})
    response = client.get(f"/accounts/{src['id']}/statement")
    assert response.status_code == 200
    body = response.get_json()
    assert body["inflow"] == 100.0
    assert body["outflow"] == 40.0
