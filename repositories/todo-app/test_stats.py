"""Feature tests for task 004 (stats endpoint). Failing on the baseline repo."""

from api import create_app


def test_stats_reports_totals():
    client = create_app().test_client()
    first = client.post("/todos", json={"title": "a"}).get_json()
    client.post("/todos", json={"title": "b"})
    client.post("/todos", json={"title": "c"})
    client.put(f"/todos/{first['id']}", json={"done": True})
    response = client.get("/todos/stats")
    assert response.status_code == 200
    body = response.get_json()
    assert body["total"] == 3
    assert body["done"] == 1
