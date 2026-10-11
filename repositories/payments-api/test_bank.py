"""Baseline tests for the Payments demo application (must pass before changes)."""

from api import create_app
from models import BankStore


def test_create_and_list_accounts():
    store = BankStore()
    store.create_account("alice", initial_balance=100.0)
    owners = [account.owner for account in store.list_accounts()]
    assert owners == ["alice"]


def test_deposit_increases_balance():
    store = BankStore()
    account = store.create_account("bob")
    store.deposit(account.id, 25.0)
    assert store.get_account(account.id).balance == 25.0


def test_get_missing_account_raises():
    store = BankStore()
    try:
        store.get_account(999)
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for unknown account")


def test_api_create_account_returns_201():
    client = create_app().test_client()
    response = client.post("/accounts", json={"owner": "carol", "initial_balance": 10.0})
    assert response.status_code == 201
    assert response.get_json()["owner"] == "carol"
