"""Feature test for task 003 (tags). Failing on the baseline repo."""

from api import create_app


def test_create_post_deduplicates_tags():
    client = create_app().test_client()
    response = client.post(
        "/posts", json={"title": "t", "author": "a", "tags": ["a", "a", "b"]}
    )
    assert response.status_code == 201
    assert response.get_json()["tags"] == ["a", "b"]
