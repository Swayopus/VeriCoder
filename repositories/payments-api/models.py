"""In-memory bank storage for the Payments demo application."""

from __future__ import annotations

from dataclasses import dataclass


class NotFound(KeyError):
    pass


@dataclass
class Account:
    id: int
    owner: str
    balance: float = 0.0
    currency: str = "USD"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "owner": self.owner,
            "balance": self.balance,
            "currency": self.currency,
        }


@dataclass
class Transaction:
    id: int
    account_id: int
    kind: str
    amount: float
    balance_after: float

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "kind": self.kind,
            "amount": self.amount,
            "balance_after": self.balance_after,
        }


class BankStore:
    def __init__(self) -> None:
        self._accounts: dict[int, Account] = {}
        self._transactions: dict[int, Transaction] = {}
        self._next_account_id = 1
        self._next_transaction_id = 1

    def create_account(
        self,
        owner: str,
        initial_balance: float = 0.0,
        currency: str = "USD",
    ) -> Account:
        account = Account(
            id=self._next_account_id,
            owner=owner,
            balance=initial_balance,
            currency=currency,
        )
        self._accounts[account.id] = account
        self._next_account_id += 1
        return account

    def get_account(self, account_id: int) -> Account:
        if account_id not in self._accounts:
            raise NotFound(account_id)
        return self._accounts[account_id]

    def list_accounts(self) -> list[Account]:
        return list(self._accounts.values())

    def deposit(self, account_id: int, amount: float) -> Account:
        account = self.get_account(account_id)
        account.balance += amount
        return account

    def list_transactions(self, account_id: int) -> list[Transaction]:
        self.get_account(account_id)
        return [t for t in self._transactions.values() if t.account_id == account_id]
