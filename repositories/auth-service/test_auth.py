"""Baseline tests for the auth-service demo application."""

from api import create_app
from models import AuthStore


def test_register_returns_id_and_username():
    store = AuthStore()
    user = store.register("alice", "s3cretpass")
    assert user.to_dict() == {"id": user.id, "username": "alice"}


def test_register_api_hides_password():
    client = create_app().test_client()
    response = client.post("/register", json={"username": "alice", "password": "s3cretpass"})
    assert response.status_code == 201
    body = response.get_json()
    assert "password" not in body
    assert body["username"] == "alice"


def test_login_returns_token():
    client = create_app().test_client()
    client.post("/register", json={"username": "alice", "password": "s3cretpass"})
    response = client.post("/login", json={"username": "alice", "password": "s3cretpass"})
    assert response.status_code == 200
    assert response.get_json().get("token")


def test_me_returns_current_user():
    client = create_app().test_client()
    client.post("/register", json={"username": "alice", "password": "s3cretpass"})
    token = client.post(
        "/login", json={"username": "alice", "password": "s3cretpass"}
    ).get_json()["token"]
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.get_json()["username"] == "alice"
