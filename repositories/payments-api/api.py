"""Flask JSON API for the Payments demo application."""

from __future__ import annotations

from flask import Flask, jsonify, request

from models import BankStore, NotFound


def create_app(store: BankStore | None = None) -> Flask:
    app = Flask(__name__)
    store = store or BankStore()
    app.config["STORE"] = store

    @app.get("/accounts")
    def list_accounts():
        return jsonify({"items": [account.to_dict() for account in store.list_accounts()]})

    @app.post("/accounts")
    def create_account():
        data = request.get_json(force=True, silent=True) or {}
        owner = data.get("owner", "")
        initial_balance = data.get("initial_balance", 0.0)
        account = store.create_account(owner, initial_balance=initial_balance)
        return jsonify(account.to_dict()), 201

    @app.get("/accounts/<int:account_id>")
    def get_account(account_id: int):
        try:
            return jsonify(store.get_account(account_id).to_dict())
        except NotFound:
            return jsonify({"error": "not found"}), 404

    @app.post("/accounts/<int:account_id>/deposit")
    def deposit(account_id: int):
        data = request.get_json(force=True, silent=True) or {}
        amount = data.get("amount", 0.0)
        try:
            account = store.deposit(account_id, amount)
        except NotFound:
            return jsonify({"error": "not found"}), 404
        return jsonify(account.to_dict())

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
