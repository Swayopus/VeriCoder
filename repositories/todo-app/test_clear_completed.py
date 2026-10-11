"""Feature tests for task 005 (clear completed). Failing on the baseline repo."""

from api import create_app


def test_clear_completed_removes_finished_todos():
    client = create_app().test_client()
    first = client.post("/todos", json={"title": "a"}).get_json()
    second = client.post("/todos", json={"title": "b"}).get_json()
    client.put(f"/todos/{first['id']}", json={"done": True})
    client.put(f"/todos/{second['id']}", json={"done": True})
    response = client.delete("/todos/completed")
    assert response.status_code == 200
    assert response.get_json()["deleted"] == 2
    assert client.get("/todos").get_json()["items"] == []
