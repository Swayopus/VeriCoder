"""Feature tests for task 006 (login rate limiting). Failing on the baseline repo."""

from api import create_app
from models import AuthStore


def test_single_wrong_password_is_unauthorized():
    client = create_app().test_client()
    client.post("/register", json={"username": "alice", "password": "s3cretpass"})
    response = client.post("/login", json={"username": "alice", "password": "wrongpass1"})
    assert response.status_code == 401


def test_failed_login_is_recorded():
    store = AuthStore()
    store.register("bob", "s3cretpass")
    store.authenticate("bob", "wrongpass1")
    assert store.login_failures.get("bob") == 1
