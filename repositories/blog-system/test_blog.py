"""Tests for the Blog demo application (baseline)."""

from api import create_app
from models import BlogStore


def test_create_and_get_post():
    store = BlogStore()
    post = store.create_post("hello", "alice")
    assert store.get_post(post.id).title == "hello"


def test_comments_are_scoped_to_post():
    store = BlogStore()
    first = store.create_post("a", "alice")
    second = store.create_post("b", "bob")
    store.add_comment(first.id, "carol", "nice")
    assert len(store.list_comments(first.id)) == 1
    assert store.list_comments(second.id) == []


def test_api_create_post():
    client = create_app().test_client()
    response = client.post("/posts", json={"title": "t", "author": "a"})
    assert response.status_code == 201
    assert response.get_json()["title"] == "t"
