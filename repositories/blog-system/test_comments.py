"""Feature test for task 005 (comment delete). Failing on the baseline repo."""

from api import create_app


def test_delete_removes_comment_from_list():
    client = create_app().test_client()
    post = client.post("/posts", json={"title": "t", "author": "a"}).get_json()
    comment = client.post(
        f"/posts/{post['id']}/comments", json={"author": "c", "body": "hello"}
    ).get_json()
    response = client.delete(f"/posts/{post['id']}/comments/{comment['id']}")
    assert response.status_code in (200, 204)
    remaining = client.get(f"/posts/{post['id']}/comments").get_json()["items"]
    assert remaining == []
