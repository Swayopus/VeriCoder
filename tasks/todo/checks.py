"""Executable task contracts; each check runs outside the candidate process."""

from __future__ import annotations

from verifier.requirement_runner import run_python_check


def _run(repo_dir: str, code: str):
    return run_python_check(repo_dir, code, timeout=60)


def check_due_date_in_response(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
r = client.post("/todos", json={"title": "t", "due_date": "2026-01-01"})
assert r.status_code == 201, r.status_code
body = r.get_json()
assert body.get("due_date") == "2026-01-01", body
todo_id = body["id"]
assert client.get(f"/todos/{todo_id}").get_json()["due_date"] == "2026-01-01"
assert client.get("/todos").get_json()["items"][0]["due_date"] == "2026-01-01"
updated = client.put(f"/todos/{todo_id}", json={"due_date": "2026-02-02"})
assert updated.status_code == 200, updated.status_code
assert updated.get_json()["due_date"] == "2026-02-02", updated.get_json()
assert client.get(f"/todos/{todo_id}").get_json()["due_date"] == "2026-02-02"
""",
    )


def check_old_api_compatible(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
r = client.post("/todos", json={"title": "legacy"})
assert r.status_code == 201, r.status_code
body = r.get_json()
assert body["title"] == "legacy" and body["done"] is False, body
assert body.get("due_date") is None, body
changed = client.put(f"/todos/{body['id']}", json={"done": True})
assert changed.status_code == 200 and changed.get_json()["done"] is True
""",
    )


def check_pagination(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
for i in range(5):
    client.post("/todos", json={"title": f"t{i}"})
for page, expected in [(1, ["t0", "t1"]), (2, ["t2", "t3"]), (3, ["t4"]), (4, [])]:
    r = client.get(f"/todos?page={page}&limit=2")
    assert r.status_code == 200, r.status_code
    body = r.get_json()
    assert body["total"] == 5, body
    assert [item["title"] for item in body["items"]] == expected, body
    assert body["page"] == page and body["limit"] == 2, body
""",
    )


def check_pagination_invalid_params(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
for i in range(3):
    client.post("/todos", json={"title": f"t{i}"})
r = client.get("/todos?page=abc&limit=xyz")
assert r.status_code == 200, r.status_code
body = r.get_json()
assert [item["title"] for item in body["items"]] == ["t0", "t1", "t2"], body
assert body["total"] == 3 and body["page"] == 1 and body["limit"] == 10, body
""",
    )


def check_list_backward_compatible(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
for title in ["a", "b"]:
    client.post("/todos", json={"title": title})
r = client.get("/todos")
assert r.status_code == 200, r.status_code
assert [item["title"] for item in r.get_json()["items"]] == ["a", "b"], r.get_json()
""",
    )


def check_filter_by_done(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
a = client.post("/todos", json={"title": "a"}).get_json()
client.post("/todos", json={"title": "b"})
client.put(f"/todos/{a['id']}", json={"done": True})
for value, expected in [("true", ["a"]), ("false", ["b"])]:
    r = client.get(f"/todos?done={value}")
    assert r.status_code == 200, r.status_code
    assert [item["title"] for item in r.get_json()["items"]] == expected, r.get_json()
assert len(client.get("/todos").get_json()["items"]) == 2
""",
    )


def check_update_validation(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
created = client.post("/todos", json={"title": "a"}).get_json()
r = client.put(f"/todos/{created['id']}", json={"title": ""})
assert r.status_code == 400, r.status_code
assert client.get(f"/todos/{created['id']}").get_json()["title"] == "a"
""",
    )


def check_stats_counts(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
first = client.post("/todos", json={"title": "a"}).get_json()
for title in ["b", "c"]:
    client.post("/todos", json={"title": title})
client.put(f"/todos/{first['id']}", json={"done": True})
response = client.get("/todos/stats")
assert response.status_code == 200, response.status_code
assert response.get_json() == {"total": 3, "done": 1, "pending": 2}, response.get_json()
""",
    )


def check_stats_empty(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
response = client.get("/todos/stats")
assert response.status_code == 200, response.status_code
assert response.get_json() == {"total": 0, "done": 0, "pending": 0}, response.get_json()
""",
    )


def check_clear_completed(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
for title in ["a", "b"]:
    todo = client.post("/todos", json={"title": title}).get_json()
    client.put(f"/todos/{todo['id']}", json={"done": True})
r = client.delete("/todos/completed")
assert r.status_code == 200 and r.get_json()["deleted"] == 2, (r.status_code, r.get_json())
assert client.get("/todos").get_json()["items"] == []
repeated = client.delete("/todos/completed")
assert repeated.status_code == 200 and repeated.get_json()["deleted"] == 0
""",
    )


def check_only_completed_removed(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
first = client.post("/todos", json={"title": "done-one"}).get_json()
pending = client.post("/todos", json={"title": "pending-one"}).get_json()
client.put(f"/todos/{first['id']}", json={"done": True})
r = client.delete("/todos/completed")
assert r.status_code == 200 and r.get_json()["deleted"] == 1, (r.status_code, r.get_json())
items = client.get("/todos").get_json()["items"]
assert [item["id"] for item in items] == [pending["id"]], items
""",
    )


def check_priority_roundtrip(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
r = client.post("/todos", json={"title": "a", "priority": "high"})
assert r.status_code == 201 and r.get_json()["priority"] == "high", (r.status_code, r.get_json())
todo_id = r.get_json()["id"]
assert client.get(f"/todos/{todo_id}").get_json()["priority"] == "high"
assert client.get("/todos").get_json()["items"][0]["priority"] == "high"
default = client.post("/todos", json={"title": "b"}).get_json()
assert default["priority"] == "medium", default
changed = client.put(f"/todos/{todo_id}", json={"priority": "low"})
assert changed.status_code == 200 and changed.get_json()["priority"] == "low"
assert client.get(f"/todos/{todo_id}").get_json()["priority"] == "low"
""",
    )


def check_priority_validation(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
for value in ["urgent", "", None]:
    r = client.post("/todos", json={"title": "a", "priority": value})
    assert r.status_code == 400, (value, r.status_code)
todo = client.post("/todos", json={"title": "b", "priority": "high"}).get_json()
r = client.put(f"/todos/{todo['id']}", json={"priority": "urgent"})
assert r.status_code == 400, r.status_code
assert client.get(f"/todos/{todo['id']}").get_json()["priority"] == "high"
""",
    )
