"""Flask JSON API for the Todo demo application."""

from __future__ import annotations

from flask import Flask, jsonify, request

from models import TodoNotFound, TodoStore


def create_app(store: TodoStore | None = None) -> Flask:
    app = Flask(__name__)
    store = store or TodoStore()
    app.config["STORE"] = store

    @app.get("/todos")
    def list_todos():
        items = [todo.to_dict() for todo in store.list()]
        return jsonify({"items": items})

    @app.post("/todos")
    def create_todo():
        data = request.get_json(force=True, silent=True) or {}
        title = data.get("title", "")
        if not title:
            return jsonify({"error": "title is required"}), 400
        todo = store.create(title)
        return jsonify(todo.to_dict()), 201

    @app.get("/todos/<int:todo_id>")
    def get_todo(todo_id: int):
        try:
            return jsonify(store.get(todo_id).to_dict())
        except TodoNotFound:
            return jsonify({"error": "not found"}), 404

    @app.put("/todos/<int:todo_id>")
    def update_todo(todo_id: int):
        data = request.get_json(force=True, silent=True) or {}
        try:
            todo = store.update(
                todo_id,
                title=data.get("title"),
                done=data.get("done"),
            )
        except TodoNotFound:
            return jsonify({"error": "not found"}), 404
        return jsonify(todo.to_dict())

    @app.delete("/todos/<int:todo_id>")
    def delete_todo(todo_id: int):
        try:
            store.delete(todo_id)
        except TodoNotFound:
            return jsonify({"error": "not found"}), 404
        return "", 204

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
