"""Flask JSON API for the Blog demo application."""

from __future__ import annotations

from flask import Flask, jsonify, request

from models import BlogStore, NotFound


def create_app(store: BlogStore | None = None) -> Flask:
    app = Flask(__name__)
    store = store or BlogStore()
    app.config["STORE"] = store

    @app.get("/posts")
    def list_posts():
        items = [post.to_dict() for post in store.list_posts()]
        return jsonify({"items": items, "total": len(items)})

    @app.post("/posts")
    def create_post():
        data = request.get_json(force=True, silent=True) or {}
        if not data.get("title"):
            return jsonify({"error": "title is required"}), 400
        post = store.create_post(data["title"], data.get("author", "anonymous"), data.get("body", ""))
        return jsonify(post.to_dict()), 201

    @app.get("/posts/<int:post_id>")
    def get_post(post_id: int):
        try:
            post = store.get_post(post_id)
        except NotFound:
            return jsonify({"error": "not found"}), 404
        return jsonify(post.to_dict())

    @app.delete("/posts/<int:post_id>")
    def delete_post(post_id: int):
        try:
            store.delete_post(post_id)
        except NotFound:
            return jsonify({"error": "not found"}), 404
        return "", 204

    @app.get("/posts/<int:post_id>/comments")
    def list_comments(post_id: int):
        comments = [comment.to_dict() for comment in store.list_comments(post_id)]
        return jsonify({"items": comments, "total": len(comments)})

    @app.post("/posts/<int:post_id>/comments")
    def add_comment(post_id: int):
        data = request.get_json(force=True, silent=True) or {}
        try:
            comment = store.add_comment(post_id, data.get("author", "anonymous"), data.get("body", ""))
        except NotFound:
            return jsonify({"error": "post not found"}), 404
        return jsonify(comment.to_dict()), 201

    return app


app = create_app()
