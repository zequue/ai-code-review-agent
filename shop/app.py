import os

from flask import Flask, g, jsonify, request

from shop import db
from shop.cart import Cart, CartError
from shop.checkout import CheckoutError, checkout


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path or os.environ.get("SHOP_DB", "shop.db")

    def get_conn():
        if "conn" not in g:
            g.conn = db.connect(app.config["DB_PATH"])
        return g.conn

    @app.teardown_appcontext
    def close_conn(_exc):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    with app.app_context():
        db.init_db(get_conn())

    @app.get("/products")
    def products():
        return jsonify(db.list_products(get_conn()))

    @app.get("/products/<int:product_id>")
    def product_detail(product_id: int):
        product = db.get_product(get_conn(), product_id)
        if product is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(product)

    @app.post("/checkout")
    def do_checkout():
        payload = request.get_json(silent=True) or {}
        try:
            cart = Cart.from_payload(payload.get("items", []))
            order = checkout(get_conn(), cart)
        except (CartError, CheckoutError, KeyError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(order), 201

    return app


if __name__ == "__main__":
    create_app().run(port=5000)
