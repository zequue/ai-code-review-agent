import sqlite3

from shop import db
from shop.cart import Cart


class CheckoutError(ValueError):
    pass


def subtotal_cents(conn: sqlite3.Connection, cart: Cart) -> int:
    total = 0
    for product_id, quantity in cart.items.items():
        product = db.get_product(conn, product_id)
        if product is None:
            raise CheckoutError(f"product {product_id} not found")
        if product["stock"] < quantity:
            raise CheckoutError(f"not enough stock for {product['name']}")
        total += product["price_cents"] * quantity
    return total


def apply_coupon(conn: sqlite3.Connection, code: str, subtotal: int) -> int:
    coupon = conn.execute("SELECT * FROM coupons WHERE code = ?", (code,)).fetchone()
    if coupon is None:
        raise CheckoutError("invalid coupon")
    price = subtotal / 100
    discounted = price - price * coupon["percent_off"] / 100
    return int(discounted * 100)


def checkout(conn: sqlite3.Connection, cart: Cart, coupon_code: str | None = None) -> dict:
    if cart.is_empty():
        raise CheckoutError("cart is empty")

    subtotal = subtotal_cents(conn, cart)
    total = apply_coupon(conn, coupon_code, subtotal) if coupon_code else subtotal

    for product_id, quantity in cart.items.items():
        conn.execute(
            "UPDATE products SET stock = stock - ? WHERE id = ?", (quantity, product_id)
        )
    cur = conn.execute(
        "INSERT INTO orders (subtotal_cents, total_cents) VALUES (?, ?)", (subtotal, total)
    )
    conn.commit()

    return {
        "order_id": cur.lastrowid,
        "subtotal_cents": subtotal,
        "discount_cents": subtotal - total,
        "total_cents": total,
    }
