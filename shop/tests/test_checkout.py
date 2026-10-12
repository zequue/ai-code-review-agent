import pytest

from shop import db
from shop.cart import Cart
from shop.checkout import CheckoutError, checkout


def test_checkout_computes_total_in_cents(conn):
    cart = Cart.from_payload([{"product_id": 1, "quantity": 2}, {"product_id": 4}])
    order = checkout(conn, cart)
    assert order["subtotal_cents"] == 1999 * 2 + 1250
    assert order["total_cents"] == order["subtotal_cents"]


def test_checkout_decrements_stock(conn):
    checkout(conn, Cart.from_payload([{"product_id": 3, "quantity": 4}]))
    assert db.get_product(conn, 3)["stock"] == 6


def test_checkout_rejects_insufficient_stock(conn):
    with pytest.raises(CheckoutError):
        checkout(conn, Cart.from_payload([{"product_id": 3, "quantity": 99}]))


def test_checkout_rejects_empty_cart(conn):
    with pytest.raises(CheckoutError):
        checkout(conn, Cart())
