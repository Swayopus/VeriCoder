"""Feature tests for task 001 (due_date). Failing on the baseline repo."""

from api import create_app
from models import TodoStore


def test_create_todo_with_due_date():
    store = TodoStore()
    todo = store.create("pay bill", due_date="2026-01-01")
    assert getattr(todo, "due_date", None) == "2026-01-01"


def test_old_api_without_due_date():
    client = create_app().test_client()
    response = client.post("/todos", json={"title": "legacy"})
    assert response.status_code == 201
    assert response.get_json().get("due_date") is None
