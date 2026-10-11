"""Executable task contracts; each check runs outside the candidate process."""

from __future__ import annotations

from verifier.requirement_runner import run_python_check


def _run(repo_dir: str, code: str):
    return run_python_check(repo_dir, code, timeout=60)


def check_password_hashed(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from models import AuthStore
from werkzeug.security import check_password_hash
import base64
import hashlib
import hmac

def verifies(stored, password):
    # Accept common standard encodings, rather than an implementation's
    # helper name or one exact iteration count/salt/digest.
    if stored.startswith(("pbkdf2:", "scrypt:")):
        return check_password_hash(stored, password)
    parts = stored.split("$")
    if len(parts) == 4 and parts[0] in {"pbkdf2_sha256", "pbkdf2_sha512"}:
        algorithm = parts[0].split("_", 1)[1]
        actual = hashlib.pbkdf2_hmac(algorithm, password.encode(), parts[2].encode(), int(parts[1]))
        return hmac.compare_digest(base64.b64encode(actual).decode(), parts[3])
    return False

store = AuthStore()
user = store.register("bob", "s3cretpass")
second = store.register("carol", "s3cretpass")
stored = store.users[user.id].password
assert isinstance(stored, str) and stored != "s3cretpass", "password must be a stored hash"
assert verifies(stored, "s3cretpass"), "stored value is not a verifiable PBKDF2/scrypt hash"
assert not verifies(stored, "wrongpass1"), "hash validates the wrong password"
assert stored != store.users[second.id].password, "same passwords must have different salts"
assert store.authenticate("bob", "s3cretpass") is not None
assert store.authenticate("bob", "wrongpass1") is None
""",
    )


def check_login_after_hash(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
r = client.post("/register", json={"username": "carol", "password": "s3cretpass"})
assert r.status_code == 201, r.status_code
wrong = client.post("/login", json={"username": "carol", "password": "wrongpass1"})
assert wrong.status_code == 401, wrong.status_code
r = client.post("/login", json={"username": "carol", "password": "s3cretpass"})
assert r.status_code == 200 and r.get_json().get("token"), (r.status_code, r.get_json())
""",
    )


def check_register_ok(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
responses = [client.post("/register", json={"username": name, "password": "s3cretpass"}) for name in ["alice", "bob"]]
assert all(response.status_code == 201 for response in responses)
assert responses[0].get_json()["id"] != responses[1].get_json()["id"]
""",
    )


def check_duplicate_username(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
from models import AuthStore
store = AuthStore()
original = store.register("dave", "s3cretpass")
duplicate_allowed = True
try:
    store.register("dave", "s3cretpass")
except Exception:
    duplicate_allowed = False
assert not duplicate_allowed, "store accepted a duplicate username"
assert len(store.users) == 1 and store.users[original.id].username == "dave"
client = create_app().test_client()
client.post("/register", json={"username": "erin", "password": "s3cretpass"})
r = client.post("/register", json={"username": "erin", "password": "s3cretpass"})
assert r.status_code == 409, r.status_code
assert client.post("/register", json={"username": "another", "password": "s3cretpass"}).status_code == 201
""",
    )


def check_token_valid(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
client.post("/register", json={"username": "alice", "password": "s3cretpass"})
r = client.post("/login", json={"username": "alice", "password": "s3cretpass"})
assert r.status_code == 200, r.status_code
token = r.get_json()["token"]
me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
assert me.status_code == 200 and me.get_json()["username"] == "alice"
""",
    )


def check_token_expired(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
from models import AuthStore
import time
store = AuthStore()
user = store.register("carol", "s3cretpass")
before = time.time()
session = store.create_session(user.id, ttl=60)
assert session.expires_at > before, session.expires_at
session.expires_at = before - 1.0
client = create_app(store).test_client()
r = client.get("/me", headers={"Authorization": f"Bearer {session.token}"})
assert r.status_code == 401, r.status_code
""",
    )


def check_password_length(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
r = client.post("/register", json={"username": "alice", "password": "abc12"})
assert r.status_code == 400, r.status_code
valid = client.post("/register", json={"username": "bob", "password": "abcdefg1"})
assert valid.status_code == 201, valid.status_code
""",
    )


def check_password_needs_digit(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
r = client.post("/register", json={"username": "alice", "password": "abcdefgh"})
assert r.status_code == 400, r.status_code
""",
    )


def check_logout_ok(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
client.post("/register", json={"username": "alice", "password": "s3cretpass"})
token = client.post("/login", json={"username": "alice", "password": "s3cretpass"}).get_json()["token"]
r = client.post("/logout", headers={"Authorization": f"Bearer {token}"})
assert r.status_code == 200, r.status_code
""",
    )


def check_logout_invalidates(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
for username in ["alice", "bob"]:
    client.post("/register", json={"username": username, "password": "s3cretpass"})
tokens = [client.post("/login", json={"username": name, "password": "s3cretpass"}).get_json()["token"] for name in ["alice", "alice", "bob"]]
client.post("/logout", headers={"Authorization": f"Bearer {tokens[0]}"})
assert client.get("/me", headers={"Authorization": f"Bearer {tokens[0]}"}).status_code == 401
for token in tokens[1:]:
    assert client.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
""",
    )


def check_login_failure(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
client.post("/register", json={"username": "alice", "password": "s3cretpass"})
r = client.post("/login", json={"username": "alice", "password": "wrongpass1"})
assert r.status_code == 401, r.status_code
""",
    )


def check_rate_limit(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
for username in ["alice", "bob"]:
    client.post("/register", json={"username": username, "password": "s3cretpass"})
def login(username, password):
    return client.post("/login", json={"username": username, "password": password})
codes = [login("alice", "wrongpass1").status_code for _ in range(4)]
assert codes == [401, 401, 401, 429], codes
assert login("bob", "wrongpass1").status_code == 401, "limits must be scoped per username"
correct = login("alice", "s3cretpass")
assert correct.status_code == 200 and correct.get_json().get("token"), correct.status_code
reset_codes = [login("alice", "wrongpass1").status_code for _ in range(4)]
assert reset_codes == [401, 401, 401, 429], reset_codes
""",
    )


def check_case_insensitive_login(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
registered = client.post("/register", json={"username": "Alice", "password": "s3cretpass"}).get_json()
r = client.post("/login", json={"username": "alice", "password": "s3cretpass"})
assert r.status_code == 200 and r.get_json().get("token"), (r.status_code, r.get_json())
me = client.get("/me", headers={"Authorization": f"Bearer {r.get_json()['token']}"})
assert me.get_json()["id"] == registered["id"]
assert me.get_json()["username"] == "Alice", "retain the registered display casing"
""",
    )


def check_case_insensitive_unique(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
client.post("/register", json={"username": "Alice", "password": "s3cretpass"})
r = client.post("/register", json={"username": "alice", "password": "s3cretpass"})
assert r.status_code == 409, r.status_code
assert client.post("/register", json={"username": "Bob", "password": "s3cretpass"}).status_code == 201
""",
    )
