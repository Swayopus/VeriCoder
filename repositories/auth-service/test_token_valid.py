"""Feature tests for task 003 (token expiry). Failing on the baseline repo."""

import time

from api import create_app
from models import AuthStore


def test_valid_token_authenticates():
    client = create_app().test_client()
    client.post("/register", json={"username": "alice", "password": "s3cretpass"})
    response = client.post("/login", json={"username": "alice", "password": "s3cretpass"})
    token = response.get_json()["token"]
    assert client.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_new_session_expires_in_the_future():
    store = AuthStore()
    user = store.register("bob", "s3cretpass")
    session = store.create_session(user.id, ttl=60)
    assert session.expires_at > time.time()
