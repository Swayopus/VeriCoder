"""Tests for the Todo demo application (baseline)."""

from api import create_app
from models import TodoStore


def test_create_and_list():
    store = TodoStore()
    store.create("write report")
    titles = [todo.title for todo in store.list()]
    assert titles == ["write report"]


def test_update_persists_done():
    store = TodoStore()
    todo = store.create("a")
    store.update(todo.id, done=True)
    assert store.get(todo.id).done is True


def test_delete_removes_todo():
    store = TodoStore()
    todo = store.create("temporary")
    store.delete(todo.id)
    assert store.list() == []


def test_api_create_returns_201():
    client = create_app().test_client()
    response = client.post("/todos", json={"title": "legacy"})
    assert response.status_code == 201
    assert response.get_json()["title"] == "legacy"


def test_api_create_rejects_empty_title():
    client = create_app().test_client()
    response = client.post("/todos", json={"title": ""})
    assert response.status_code == 400
