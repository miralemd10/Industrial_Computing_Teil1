"""SQLite-Lagerdatenbank fuer einen Socken-Onlineshop initialisieren."""

from contextlib import closing
from pathlib import Path
import sqlite3


DATABASE_PATH = Path(__file__).resolve().parent / "data" / "lager.db"

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL CHECK (length(trim(name)) > 0),
        color TEXT NOT NULL CHECK (length(trim(color)) > 0),
        size TEXT NOT NULL CHECK (length(trim(size)) > 0),
        unit_price_cents INTEGER NOT NULL
            CHECK (typeof(unit_price_cents) = 'integer' AND unit_price_cents >= 0),
        stock_quantity INTEGER NOT NULL
            CHECK (typeof(stock_quantity) = 'integer' AND stock_quantity >= 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY,
        status TEXT NOT NULL CHECK (status IN ('offen', 'versendet')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY,
        order_id INTEGER NOT NULL REFERENCES orders(id),
        product_id INTEGER NOT NULL REFERENCES products(id),
        quantity INTEGER NOT NULL
            CHECK (typeof(quantity) = 'integer' AND quantity > 0)
    )
    """,
)

# Aktueller physischer Bestand in Paaren: offene Bestellungen sind enthalten,
# bereits versendete Paare sind nicht mehr im Lager. Die Initialisierung
# zieht deshalb keine Bestellmengen von diesen Bestandswerten ab.
PRODUCTS = (
    (1, "Baumwollsocken", "schwarz", "39-42", 599, 5),
    (2, "Baumwollsocken", "weiss", "43-46", 599, 4),
    (3, "Sportsocken", "blau", "39-42", 899, 3),
    (4, "Wollsocken", "grau", "43-46", 1299, 2),
)
ORDERS = (
    (1, "offen", "2026-10-01 09:00:00"),
    (2, "offen", "2026-10-01 10:00:00"),
    (3, "offen", "2026-10-01 11:00:00"),
    (4, "versendet", "2026-09-30 09:00:00"),
    (5, "versendet", "2026-09-30 10:00:00"),
)
ORDER_ITEMS = (
    # Offene Bestellung 1
    (1, 1, 1, 3),
    (2, 1, 3, 1),

    # Offene Bestellung 2
    (3, 2, 2, 3),

    # Offene Bestellung 3
    (4, 3, 4, 2),
    (5, 3, 1, 4),

    # Bereits versendete Bestellungen
    (6, 4, 1, 2),
    (7, 4, 2, 1),
    (8, 5, 3, 2),
    (9, 5, 4, 1),
)

def init_database() -> Path:
    """Tabellen erstellen und fehlende Beispieldatensaetze ergaenzen."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(DATABASE_PATH)) as connection:
        # SQLite verlangt diese Einstellung fuer jede neue Verbindung.
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            for statement in SCHEMA:
                connection.execute(statement)

            # Feste Beispiel-IDs verhindern Duplikate. Vorhandene Datensaetze
            # werden weder ersetzt noch aktualisiert (auch keine Bestaende).
            connection.executemany(
                """INSERT INTO products
                   (id, name, color, size, unit_price_cents, stock_quantity)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO NOTHING""",
                PRODUCTS,
            )
            connection.executemany(
                """INSERT INTO orders (id, status, created_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(id) DO NOTHING""",
                ORDERS,
            )
            connection.executemany(
                """INSERT INTO order_items (id, order_id, product_id, quantity)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(id) DO NOTHING""",
                ORDER_ITEMS,
            )

        product_count = connection.execute(
            "SELECT COUNT(*) FROM products"
        ).fetchone()[0]
        open_order_count = connection.execute(
            "SELECT COUNT(*) FROM orders WHERE status = 'offen'"
        ).fetchone()[0]

    print(f"Datenbank: {DATABASE_PATH}")
    print(f"Produkte: {product_count}")
    print(f"Offene Bestellungen: {open_order_count}")
    return DATABASE_PATH


if __name__ == "__main__":
    init_database()
