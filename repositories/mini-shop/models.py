"""In-memory shop storage for the Mini Shop demo application."""

from __future__ import annotations

from dataclasses import dataclass


class NotFound(KeyError):
    pass


class OutOfStock(Exception):
    pass


@dataclass
class Product:
    id: int
    name: str
    price: float
    stock: int

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "price": self.price, "stock": self.stock}


class ShopStore:
    def __init__(self) -> None:
        self._products: dict[int, Product] = {}
        self._carts: dict[str, list[dict]] = {}
        self._next_product_id = 1

    def list_products(self) -> list[Product]:
        return list(self._products.values())

    def add_product(self, name: str, price: float, stock: int) -> Product:
        product = Product(id=self._next_product_id, name=name, price=float(price), stock=int(stock))
        self._products[product.id] = product
        self._next_product_id += 1
        return product

    def get_product(self, product_id: int) -> Product:
        if product_id not in self._products:
            raise NotFound(product_id)
        return self._products[product_id]

    def add_to_cart(self, user: str, product_id: int, quantity: int = 1) -> list[dict]:
        self.get_product(product_id)
        self._carts.setdefault(user, []).append({"product_id": product_id, "quantity": int(quantity)})
        return self._carts[user]

    def cart_summary(self, user: str) -> dict:
        items = []
        subtotal = 0.0
        for entry in self._carts.get(user, []):
            product = self.get_product(entry["product_id"])
            line_total = product.price * entry["quantity"]
            subtotal += line_total
            items.append(
                {
                    "product_id": product.id,
                    "name": product.name,
                    "quantity": entry["quantity"],
                    "line_total": round(line_total, 2),
                }
            )
        return {"items": items, "subtotal": round(subtotal, 2)}

    def checkout(self, user: str) -> dict:
        summary = self.cart_summary(user)
        for entry in self._carts.get(user, []):
            product = self.get_product(entry["product_id"])
            product.stock -= entry["quantity"]
        self._carts[user] = []
        return {
            "items": summary["items"],
            "subtotal": summary["subtotal"],
            "discount": 0.0,
            "total": summary["subtotal"],
        }
