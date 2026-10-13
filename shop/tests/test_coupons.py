import pytest

from shop.cart import Cart
from shop.checkout import CheckoutError, checkout


def test_coupon_applies_percent_discount_in_cents(conn):
    order = checkout(conn, Cart.from_payload([{"product_id": 3}]), "BIENVENIDA10")
    assert order["subtotal_cents"] == 8999
    assert order["discount_cents"] == 899
    assert order["total_cents"] == 8100


def test_coupon_cannot_be_reused(conn):
    checkout(conn, Cart.from_payload([{"product_id": 1}]), "PROMO25")
    with pytest.raises(CheckoutError, match="already used"):
        checkout(conn, Cart.from_payload([{"product_id": 1}]), "PROMO25")


def test_invalid_coupon_is_rejected(conn):
    with pytest.raises(CheckoutError, match="invalid coupon"):
        checkout(conn, Cart.from_payload([{"product_id": 1}]), "NOEXISTE")


def test_checkout_without_coupon_has_no_discount(conn):
    order = checkout(conn, Cart.from_payload([{"product_id": 1}]))
    assert order["discount_cents"] == 0
    assert order["total_cents"] == 1999
