"""Flask JSON API for the auth-service demo application."""

from __future__ import annotations

from flask import Flask, jsonify, request

from models import AuthStore


def _token_from_header() -> str:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    return ""


def create_app(store: AuthStore | None = None) -> Flask:
    app = Flask(__name__)
    store = store or AuthStore()
    app.config["STORE"] = store

    @app.post("/register")
    def register_user():
        data = request.get_json(force=True, silent=True) or {}
        username = data.get("username", "")
        password = data.get("password", "")
        if not username or not password:
            return jsonify({"error": "username and password are required"}), 400
        user = store.register(username, password)
        return jsonify(user.to_dict()), 201

    @app.post("/login")
    def login_user():
        data = request.get_json(force=True, silent=True) or {}
        username = data.get("username", "")
        password = data.get("password", "")
        user = store.authenticate(username, password)
        if user is None:
            return jsonify({"error": "invalid credentials"}), 401
        session = store.create_session(user.id)
        return jsonify({"token": session.token})

    @app.get("/me")
    def me():
        token = _token_from_header()
        user_id = store.get_session(token)
        if user_id is None or user_id not in store.users:
            return jsonify({"error": "unauthorized"}), 401
        return jsonify(store.users[user_id].to_dict())

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
