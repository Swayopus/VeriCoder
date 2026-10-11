"""Feature tests for task 004 (password strength). Failing on the baseline repo."""

from api import create_app


def test_short_password_is_rejected():
    client = create_app().test_client()
    response = client.post("/register", json={"username": "alice", "password": "abc12"})
    assert response.status_code == 400
