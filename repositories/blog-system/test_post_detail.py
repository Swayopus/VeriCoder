"""Feature test for task 002 (comment_count). Failing on the baseline repo."""

from api import create_app


def test_post_detail_reports_comment_count():
    client = create_app().test_client()
    post = client.post("/posts", json={"title": "t", "author": "a"}).get_json()
    client.post(f"/posts/{post['id']}/comments", json={"author": "c", "body": "one"})
    client.post(f"/posts/{post['id']}/comments", json={"author": "c", "body": "two"})
    response = client.get(f"/posts/{post['id']}")
    assert response.status_code == 200
    assert response.get_json()["comment_count"] == 2


def test_post_detail_missing_is_404():
    client = create_app().test_client()
    response = client.get("/posts/999")
    assert response.status_code == 404
