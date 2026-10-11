"""Feature tests for task 005 (logout). Failing on the baseline repo."""

from api import create_app


def test_logout_returns_200():
    client = create_app().test_client()
    client.post("/register", json={"username": "alice", "password": "s3cretpass"})
    token = client.post(
        "/login", json={"username": "alice", "password": "s3cretpass"}
    ).get_json()["token"]
    response = client.post("/logout", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
