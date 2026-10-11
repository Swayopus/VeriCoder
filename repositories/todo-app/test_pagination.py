"""Feature tests for task 002 (pagination). Failing on the baseline repo."""

from api import create_app


def test_pagination_returns_total_and_window():
    client = create_app().test_client()
    for i in range(5):
        client.post("/todos", json={"title": f"t{i}"})
    response = client.get("/todos?page=2&limit=2")
    assert response.status_code == 200
    body = response.get_json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["page"] == 2
    assert body["limit"] == 2


def test_list_without_pagination_params():
    client = create_app().test_client()
    client.post("/todos", json={"title": "a"})
    response = client.get("/todos")
    assert response.status_code == 200
    assert len(response.get_json()["items"]) == 1
