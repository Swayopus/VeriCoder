"""Executable task contracts; each check runs outside the candidate process."""

from __future__ import annotations

from verifier.requirement_runner import run_python_check


def _run(repo_dir: str, code: str):
    return run_python_check(repo_dir, code, timeout=60)


def check_blog_pagination(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
for i in range(3):
    client.post("/posts", json={"title": f"p{i}", "author": "a"})
for page, expected in [(1, ["p0", "p1"]), (2, ["p2"]), (3, [])]:
    r = client.get(f"/posts?page={page}&limit=2")
    assert r.status_code == 200, r.status_code
    body = r.get_json()
    assert body["total"] == 3, body
    assert [item["title"] for item in body["items"]] == expected, body
    assert body["page"] == page and body["limit"] == 2, body
""",
    )


def check_cascade_delete(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
first = client.post("/posts", json={"title": "first"}).get_json()
second = client.post("/posts", json={"title": "second"}).get_json()
for post in [first, second]:
    client.post(f"/posts/{post['id']}/comments", json={"body": "keep scoped"})
r = client.delete(f"/posts/{first['id']}")
assert r.status_code in (200, 204), r.status_code
assert client.get(f"/posts/{first['id']}").status_code == 404
assert client.get(f"/posts/{first['id']}/comments").get_json()["items"] == []
assert len(client.get(f"/posts/{second['id']}/comments").get_json()["items"]) == 1
""",
    )


def check_post_comment_count(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
post = client.post("/posts", json={"title": "t", "author": "a"}).get_json()
for body in ["one", "two"]:
    client.post(f"/posts/{post['id']}/comments", json={"body": body})
r = client.get(f"/posts/{post['id']}")
assert r.status_code == 200, r.status_code
assert r.get_json().get("comment_count") == 2, r.get_json()
assert client.get("/posts/99999").status_code == 404
""",
    )


def check_comment_count_scoped(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
first = client.post("/posts", json={"title": "a"}).get_json()
second = client.post("/posts", json={"title": "b"}).get_json()
client.post(f"/posts/{first['id']}/comments", json={"body": "hi"})
body = client.get(f"/posts/{second['id']}").get_json()
assert body.get("comment_count") == 0, body
""",
    )


def check_tags_roundtrip(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
r = client.post("/posts", json={"title": "t", "author": "a", "tags": ["a", "a", "b"]})
assert r.status_code == 201, r.status_code
assert r.get_json().get("tags") == ["a", "b"], r.get_json()
post_id = r.get_json()["id"]
assert client.get(f"/posts/{post_id}").get_json()["tags"] == ["a", "b"]
assert client.get("/posts").get_json()["items"][0]["tags"] == ["a", "b"]
default = client.post("/posts", json={"title": "default"}).get_json()
assert default["tags"] == [], default
""",
    )


def check_tag_filter(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
client.post("/posts", json={"title": "a", "tags": ["x"]})
client.post("/posts", json={"title": "b", "tags": ["y"]})
for tag, expected in [("x", ["a"]), ("y", ["b"]), ("none", [])]:
    r = client.get(f"/posts?tag={tag}")
    assert r.status_code == 200, r.status_code
    body = r.get_json()
    assert [item["title"] for item in body["items"]] == expected, body
    assert body["total"] == len(expected), body
""",
    )


def check_published_default(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
default = client.post("/posts", json={"title": "t"})
assert default.status_code == 201, default.status_code
assert default.get_json().get("published") is False, default.get_json()
explicit = client.post("/posts", json={"title": "u", "published": True}).get_json()
assert explicit.get("published") is True, explicit
assert client.get(f"/posts/{explicit['id']}").get_json()["published"] is True
""",
    )


def check_published_filter(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
client.post("/posts", json={"title": "draft"})
client.post("/posts", json={"title": "live", "published": True})
for value, expected in [("true", ["live"]), ("false", ["draft"])]:
    r = client.get(f"/posts?published={value}")
    assert r.status_code == 200, r.status_code
    body = r.get_json()
    assert [item["title"] for item in body["items"]] == expected, body
    assert body["total"] == len(expected), body
""",
    )


def check_comment_validation(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
post = client.post("/posts", json={"title": "t"}).get_json()
for body in ["", "   ", "\t\n"]:
    r = client.post(f"/posts/{post['id']}/comments", json={"body": body})
    assert r.status_code == 400, (body, r.status_code)
assert client.get(f"/posts/{post['id']}/comments").get_json()["items"] == []
""",
    )


def check_comment_delete(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
post = client.post("/posts", json={"title": "t"}).get_json()
other = client.post("/posts", json={"title": "other"}).get_json()
comment = client.post(f"/posts/{post['id']}/comments", json={"body": "hi"}).get_json()
wrong_parent = client.delete(f"/posts/{other['id']}/comments/{comment['id']}")
assert wrong_parent.status_code == 404, wrong_parent.status_code
assert len(client.get(f"/posts/{post['id']}/comments").get_json()["items"]) == 1
r = client.delete(f"/posts/{post['id']}/comments/{comment['id']}")
assert r.status_code in (200, 204), r.status_code
assert client.get(f"/posts/{post['id']}/comments").get_json()["items"] == []
assert client.delete(f"/posts/{post['id']}/comments/{comment['id']}").status_code == 404
""",
    )
