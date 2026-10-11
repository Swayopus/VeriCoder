"""Feature tests for task 006 (priority field). Failing on the baseline repo."""

from api import create_app


def test_create_todo_with_priority():
    client = create_app().test_client()
    response = client.post("/todos", json={"title": "a", "priority": "high"})
    assert response.status_code == 201
    assert response.get_json()["priority"] == "high"
