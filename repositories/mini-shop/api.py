"""Flask JSON API for the Mini Shop demo application."""

from __future__ import annotations

from flask import Flask, jsonify, request

from models import NotFound, OutOfStock, ShopStore


def create_app(store: ShopStore | None = None) -> Flask:
    app = Flask(__name__)
    store = store or ShopStore()
    app.config["STORE"] = store

    @app.get("/products")
    def list_products():
        return jsonify({"items": [p.to_dict() for p in store.list_products()]})

    @app.post("/products")
    def add_product():
        data = request.get_json(force=True, silent=True) or {}
        if not data.get("name"):
            return jsonify({"error": "name is required"}), 400
        product = store.add_product(data["name"], data.get("price", 0), data.get("stock", 0))
        return jsonify(product.to_dict()), 201

    @app.post("/cart/<user>/items")
    def add_item(user: str):
        data = request.get_json(force=True, silent=True) or {}
        try:
            cart = store.add_to_cart(user, data.get("product_id"), data.get("quantity", 1))
        except NotFound:
            return jsonify({"error": "product not found"}), 404
        return jsonify({"items": len(cart)}), 201

    @app.get("/cart/<user>")
    def get_cart(user: str):
        return jsonify(store.cart_summary(user))

    @app.post("/cart/<user>/checkout")
    def checkout(user: str):
        try:
            order = store.checkout(user)
        except OutOfStock as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify(order), 201

    return app


app = create_app()
