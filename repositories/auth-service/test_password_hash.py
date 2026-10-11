"""Feature tests for task 001 (password hashing). Failing on the baseline repo."""

from models import AuthStore


def test_password_is_not_stored_in_plaintext():
    store = AuthStore()
    user = store.register("alice", "hunter2secret")
    assert user.password != "hunter2secret"
    assert len(user.password) >= 32
