"""Feature test for task 001 (pagination). Failing on the baseline repo."""

from api import create_app


def test_pagination_returns_total_and_window():
    client = create_app().test_client()
    for i in range(3):
        client.post("/posts", json={"title": f"p{i}", "author": "a"})
    response = client.get("/posts?page=1&limit=2")
    assert response.status_code == 200
    body = response.get_json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["page"] == 1
    assert body["limit"] == 2
