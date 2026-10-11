"""Tests for the Mini Shop demo application (baseline)."""

from api import create_app
from models import ShopStore


def test_add_product_and_list():
    store = ShopStore()
    store.add_product("widget", 10, 5)
    assert [p.name for p in store.list_products()] == ["widget"]


def test_cart_subtotal():
    store = ShopStore()
    product = store.add_product("widget", 10, 5)
    store.add_to_cart("alice", product.id, 2)
    assert store.cart_summary("alice")["subtotal"] == 20.0


def test_checkout_clears_cart():
    store = ShopStore()
    product = store.add_product("widget", 10, 5)
    store.add_to_cart("alice", product.id, 1)
    store.checkout("alice")
    assert store.cart_summary("alice")["items"] == []
