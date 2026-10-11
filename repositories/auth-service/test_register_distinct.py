"""Feature tests for task 002 (duplicate usernames). Failing on the baseline repo."""

from api import create_app


def test_two_distinct_usernames_are_accepted():
    client = create_app().test_client()
    first = client.post("/register", json={"username": "alice", "password": "s3cretpass"})
    second = client.post("/register", json={"username": "bob", "password": "s3cretpass"})
    assert first.status_code == 201
    assert second.status_code == 201


def test_duplicate_username_is_rejected():
    client = create_app().test_client()
    client.post("/register", json={"username": "alice", "password": "s3cretpass"})
    response = client.post("/register", json={"username": "alice", "password": "s3cretpass"})
    assert response.status_code == 409
