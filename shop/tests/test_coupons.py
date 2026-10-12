from shop.cart import Cart
from shop.checkout import checkout


def test_coupon_applies_percent_discount(conn):
    order = checkout(conn, Cart.from_payload([{"product_id": 4}]), "BIENVENIDA10")
    assert order["subtotal_cents"] == 1250
    assert order["total_cents"] == 1125


def test_checkout_without_coupon_has_no_discount(conn):
    order = checkout(conn, Cart.from_payload([{"product_id": 1}]))
    assert order["discount_cents"] == 0
    assert order["total_cents"] == 1999
