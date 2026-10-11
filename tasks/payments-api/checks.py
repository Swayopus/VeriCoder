"""Executable task contracts; each check runs outside the candidate process."""

from __future__ import annotations

from verifier.requirement_runner import run_python_check


def _run(repo_dir: str, code: str):
    return run_python_check(repo_dir, code, timeout=60)


def check_transfer(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
src = client.post("/accounts", json={"owner": "a", "initial_balance": 100.0}).get_json()
dst = client.post("/accounts", json={"owner": "b"}).get_json()
r = client.post("/transfers", json={"from": src["id"], "to": dst["id"], "amount": 30.0})
assert r.status_code == 201, r.status_code
assert client.get(f"/accounts/{src['id']}").get_json()["balance"] == 70.0
assert client.get(f"/accounts/{dst['id']}").get_json()["balance"] == 30.0
before = client.get("/accounts").get_json()
for source, target in [(9999, dst["id"]), (src["id"], 9999)]:
    r = client.post("/transfers", json={"from": source, "to": target, "amount": 5.0})
    assert r.status_code == 404, r.status_code
    assert client.get("/accounts").get_json() == before
""",
    )


def check_insufficient_funds(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
src = client.post("/accounts", json={"owner": "a", "initial_balance": 50.0}).get_json()
dst = client.post("/accounts", json={"owner": "b"}).get_json()
before = client.get("/accounts").get_json()
r = client.post("/transfers", json={"from": src["id"], "to": dst["id"], "amount": 100.0})
assert r.status_code == 409, r.status_code
assert client.get("/accounts").get_json() == before
""",
    )


def check_ledger(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
src = client.post("/accounts", json={"owner": "a", "initial_balance": 100.0}).get_json()
dst = client.post("/accounts", json={"owner": "b"}).get_json()
client.post(f"/accounts/{src['id']}/deposit", json={"amount": 50.0})
moved = client.post("/transfers", json={"from": src["id"], "to": dst["id"], "amount": 30.0})
assert moved.status_code == 201, moved.status_code
for account, amounts, balances in [
    (src, [50.0, 30.0], [150.0, 120.0]),
    (dst, [30.0], [30.0]),
]:
    response = client.get(f"/accounts/{account['id']}/transactions")
    assert response.status_code == 200, response.status_code
    body = response.get_json()
    assert body["total"] == len(amounts), body
    items = body["items"]
    assert [abs(item["amount"]) for item in items] == amounts, items
    assert [item["balance_after"] for item in items] == balances, items
    assert all(item["account_id"] == account["id"] for item in items), items
""",
    )


def check_ledger_balance_after(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
account = client.post("/accounts", json={"owner": "a", "initial_balance": 20.0}).get_json()
for amount in [50.0, 30.0]:
    client.post(f"/accounts/{account['id']}/deposit", json={"amount": amount})
body = client.get(f"/accounts/{account['id']}/transactions").get_json()
assert body["total"] == 2, body
assert [entry["amount"] for entry in body["items"]] == [50.0, 30.0], body
assert [entry["balance_after"] for entry in body["items"]] == [70.0, 100.0], body
""",
    )


def check_idempotency(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
src = client.post("/accounts", json={"owner": "a", "initial_balance": 100.0}).get_json()
dst = client.post("/accounts", json={"owner": "b"}).get_json()
payload = {"from": src["id"], "to": dst["id"], "amount": 30.0}
headers = {"Idempotency-Key": "key-1"}
first = client.post("/transfers", json=payload, headers=headers)
second = client.post("/transfers", json=payload, headers=headers)
assert first.status_code == second.status_code == 201
assert second.get_json() == first.get_json(), (first.get_json(), second.get_json())
assert client.get(f"/accounts/{src['id']}").get_json()["balance"] == 70.0
assert client.get(f"/accounts/{dst['id']}").get_json()["balance"] == 30.0
client.post("/transfers", json={**payload, "amount": 10.0}, headers={"Idempotency-Key": "later"})
replay = client.post("/transfers", json=payload, headers=headers)
assert replay.get_json() == first.get_json(), "replay must return the original snapshot"
assert client.get(f"/accounts/{src['id']}").get_json()["balance"] == 60.0
""",
    )


def check_distinct_keys(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
src = client.post("/accounts", json={"owner": "a", "initial_balance": 100.0}).get_json()
dst = client.post("/accounts", json={"owner": "b"}).get_json()
for key, amount in [("k-a", 30.0), ("k-b", 20.0)]:
    r = client.post("/transfers", json={"from": src["id"], "to": dst["id"], "amount": amount}, headers={"Idempotency-Key": key})
    assert r.status_code == 201, r.status_code
assert client.get(f"/accounts/{src['id']}").get_json()["balance"] == 50.0
assert client.get(f"/accounts/{dst['id']}").get_json()["balance"] == 50.0
""",
    )


def check_ledger_pagination(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
account = client.post("/accounts", json={"owner": "a"}).get_json()
for amount in [10.0, 20.0, 30.0, 40.0, 50.0]:
    client.post(f"/accounts/{account['id']}/deposit", json={"amount": amount})
for page, expected in [(1, [10.0, 20.0]), (2, [30.0, 40.0]), (3, [50.0]), (4, [])]:
    r = client.get(f"/accounts/{account['id']}/transactions?page={page}&limit=2")
    assert r.status_code == 200, r.status_code
    body = r.get_json()
    assert body["total"] == 5, body
    assert [entry["amount"] for entry in body["items"]] == expected, body
    assert body["page"] == page and body["limit"] == 2, body
assert len(client.get(f"/accounts/{account['id']}/transactions").get_json()["items"]) == 5
""",
    )


def check_ledger_pagination_invalid(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
account = client.post("/accounts", json={"owner": "a"}).get_json()
for _ in range(5):
    client.post(f"/accounts/{account['id']}/deposit", json={"amount": 10.0})
r = client.get(f"/accounts/{account['id']}/transactions?page=abc&limit=xyz")
assert r.status_code == 200, r.status_code
body = r.get_json()
assert len(body["items"]) == 5 and body["total"] == 5, body
assert body["page"] == 1 and body["limit"] == 10, body
""",
    )


def check_negative_amount(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
src = client.post("/accounts", json={"owner": "a", "initial_balance": 100.0}).get_json()
dst = client.post("/accounts", json={"owner": "b", "initial_balance": 20.0}).get_json()
before = client.get("/accounts").get_json()
deposit = client.post(f"/accounts/{src['id']}/deposit", json={"amount": -5.0})
assert deposit.status_code == 400, deposit.status_code
assert client.get("/accounts").get_json() == before
transfer = client.post("/transfers", json={"from": src["id"], "to": dst["id"], "amount": -5.0})
assert transfer.status_code == 400, transfer.status_code
assert client.get("/accounts").get_json() == before
""",
    )


def check_zero_amount(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
src = client.post("/accounts", json={"owner": "a", "initial_balance": 100.0}).get_json()
dst = client.post("/accounts", json={"owner": "b", "initial_balance": 20.0}).get_json()
before = client.get("/accounts").get_json()
deposit = client.post(f"/accounts/{src['id']}/deposit", json={"amount": 0})
assert deposit.status_code == 400, deposit.status_code
assert client.get("/accounts").get_json() == before
transfer = client.post("/transfers", json={"from": src["id"], "to": dst["id"], "amount": 0})
assert transfer.status_code == 400, transfer.status_code
assert client.get("/accounts").get_json() == before
""",
    )


def check_nonnumeric_amount(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
src = client.post("/accounts", json={"owner": "a", "initial_balance": 100.0}).get_json()
dst = client.post("/accounts", json={"owner": "b", "initial_balance": 20.0}).get_json()
before = client.get("/accounts").get_json()
for amount in ["bad", "5", None, True, [], {}]:
    r = client.post(f"/accounts/{src['id']}/deposit", json={"amount": amount})
    assert r.status_code == 400, (amount, r.status_code)
    assert client.get("/accounts").get_json() == before
    r = client.post("/transfers", json={"from": src["id"], "to": dst["id"], "amount": amount})
    assert r.status_code == 400, (amount, r.status_code)
    assert client.get("/accounts").get_json() == before
""",
    )


def check_positive_amount(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
src = client.post("/accounts", json={"owner": "a", "initial_balance": 100.0}).get_json()
dst = client.post("/accounts", json={"owner": "b"}).get_json()
deposited = client.post(f"/accounts/{src['id']}/deposit", json={"amount": 5.0})
assert deposited.status_code == 200, deposited.status_code
moved = client.post("/transfers", json={"from": src["id"], "to": dst["id"], "amount": 30.0})
assert moved.status_code == 201, moved.status_code
assert client.get(f"/accounts/{src['id']}").get_json()["balance"] == 75.0
assert client.get(f"/accounts/{dst['id']}").get_json()["balance"] == 30.0
""",
    )


def check_statement_flows(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
src = client.post("/accounts", json={"owner": "a", "initial_balance": 100.0}).get_json()
dst = client.post("/accounts", json={"owner": "b"}).get_json()
client.post(f"/accounts/{src['id']}/deposit", json={"amount": 100.0})
client.post("/transfers", json={"from": src["id"], "to": dst["id"], "amount": 40.0})
for account, inflow, outflow in [(src, 100.0, 40.0), (dst, 40.0, 0.0)]:
    r = client.get(f"/accounts/{account['id']}/statement")
    assert r.status_code == 200, r.status_code
    body = r.get_json()
    assert body["inflow"] == inflow and body["outflow"] == outflow, body
""",
    )


def check_statement_net(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
src = client.post("/accounts", json={"owner": "a", "initial_balance": 100.0}).get_json()
dst = client.post("/accounts", json={"owner": "b"}).get_json()
client.post(f"/accounts/{src['id']}/deposit", json={"amount": 100.0})
client.post("/transfers", json={"from": src["id"], "to": dst["id"], "amount": 40.0})
body = client.get(f"/accounts/{src['id']}/statement").get_json()
assert body["net"] == 60.0, body
assert client.get(f"/accounts/{dst['id']}/statement").get_json()["net"] == 40.0
""",
    )


def check_statement_count(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
src = client.post("/accounts", json={"owner": "a", "initial_balance": 100.0}).get_json()
dst = client.post("/accounts", json={"owner": "b"}).get_json()
empty = client.post("/accounts", json={"owner": "c"}).get_json()
client.post(f"/accounts/{src['id']}/deposit", json={"amount": 100.0})
client.post("/transfers", json={"from": src["id"], "to": dst["id"], "amount": 40.0})
for account, count in [(src, 2), (dst, 1), (empty, 0)]:
    r = client.get(f"/accounts/{account['id']}/statement")
    assert r.status_code == 200 and r.get_json()["count"] == count, (r.status_code, r.get_json())
""",
    )


def check_currency_match(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
for currency in ["USD", "EUR"]:
    src = client.post("/accounts", json={"owner": "a", "initial_balance": 100.0, "currency": currency}).get_json()
    dst = client.post("/accounts", json={"owner": "b", "currency": currency}).get_json()
    assert src["currency"] == dst["currency"] == currency
    r = client.post("/transfers", json={"from": src["id"], "to": dst["id"], "amount": 30.0})
    assert r.status_code == 201, r.status_code
    assert client.get(f"/accounts/{src['id']}").get_json()["balance"] == 70.0
    assert client.get(f"/accounts/{dst['id']}").get_json()["balance"] == 30.0
""",
    )


def check_currency_mismatch(repo_dir: str):
    return _run(
        repo_dir,
        r"""
from api import create_app
client = create_app().test_client()
src = client.post("/accounts", json={"owner": "a", "initial_balance": 100.0, "currency": "USD"}).get_json()
dst = client.post("/accounts", json={"owner": "b", "currency": "EUR"}).get_json()
before = client.get("/accounts").get_json()
r = client.post("/transfers", json={"from": src["id"], "to": dst["id"], "amount": 30.0})
assert r.status_code == 400, r.status_code
assert client.get("/accounts").get_json() == before
""",
    )
