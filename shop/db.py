import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price_cents INTEGER NOT NULL,
    stock INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subtotal_cents INTEGER NOT NULL,
    total_cents INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

SEED_PRODUCTS = [
    ("Remera básica", "ropa", 1999, 50),
    ("Buzo con capucha", "ropa", 4599, 20),
    ("Zapatillas urbanas", "calzado", 8999, 10),
    ("Gorra", "accesorios", 1250, 35),
    ("Mochila", "accesorios", 3499, 15),
]


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    if count == 0:
        conn.executemany(
            "INSERT INTO products (name, category, price_cents, stock) VALUES (?, ?, ?, ?)",
            SEED_PRODUCTS,
        )
    conn.commit()


def list_products(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM products ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def get_product(conn: sqlite3.Connection, product_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return dict(row) if row else None
