"""Feature test for task 004 (published). Failing on the baseline repo."""

from api import create_app


def test_published_flag_round_trips():
    client = create_app().test_client()
    default = client.post("/posts", json={"title": "t", "author": "a"}).get_json()
    published = client.post(
        "/posts", json={"title": "t", "author": "a", "published": True}
    ).get_json()
    assert default["published"] is False
    assert published["published"] is True
