"""Feature tests for task 003 (filtering). Failing on the baseline repo.

Update validation is intentionally NOT unit-tested here: it is only asserted by
the executable requirement checks, which is exactly the gap VeriCoder catches.
"""

from api import create_app


def test_filter_by_done():
    client = create_app().test_client()
    first = client.post("/todos", json={"title": "a"}).get_json()
    client.post("/todos", json={"title": "b"})
    client.put(f"/todos/{first['id']}", json={"done": True})
    done = client.get("/todos?done=true").get_json()["items"]
    assert [item["title"] for item in done] == ["a"]
    pending = client.get("/todos?done=false").get_json()["items"]
    assert [item["title"] for item in pending] == ["b"]
