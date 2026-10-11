"""Feature tests for task 007 (case-insensitive usernames). Failing on the baseline repo."""

from api import create_app


def test_login_is_case_insensitive():
    client = create_app().test_client()
    client.post("/register", json={"username": "Alice", "password": "s3cretpass"})
    response = client.post("/login", json={"username": "alice", "password": "s3cretpass"})
    assert response.status_code == 200
    assert response.get_json().get("token")
