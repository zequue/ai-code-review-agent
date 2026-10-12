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


def checkout(conn: sqlite3.Connection, cart: Cart) -> dict:
    if cart.is_empty():
        raise CheckoutError("cart is empty")

    subtotal = subtotal_cents(conn, cart)
    total = subtotal

    for product_id, quantity in cart.items.items():
        conn.execute(
            "UPDATE products SET stock = stock - ? WHERE id = ?", (quantity, product_id)
        )
    cur = conn.execute(
        "INSERT INTO orders (subtotal_cents, total_cents) VALUES (?, ?)", (subtotal, total)
    )
    conn.commit()

    return {"order_id": cur.lastrowid, "subtotal_cents": subtotal, "total_cents": total}
