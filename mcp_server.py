"""MCP-Tools fuer den Lager-Assistenten, erreichbar ueber stdio."""

from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
import json
from pathlib import Path
import sqlite3
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "data" / "lager.db"
AUDIT_PATH = BASE_DIR / "logs" / "audit.jsonl"

mcp = FastMCP("Lager-Assistent")


@mcp.tool()
def get_inventory_and_orders() -> dict[str, object]:
    """Liest Lager und Bestellungen direkt aus orders, ohne Daten zu veraendern.

    open_order_count, shipped_order_count und total_order_count zaehlen
    Bestellungen direkt aus orders mit Status 'offen' und 'versendet'.
    products enthaelt product_id, name, color, size, physical_stock,
    open_order_quantity und free_stock fuer jedes Produkt.
    Mengen sind Paar Socken. Offene Bestellmengen sind im physischen Bestand
    enthalten; versendete Bestellungen werden nicht abgezogen.
    free_stock = physical_stock - open_order_quantity. Negative Werte zeigen
    einen Fehlbestand und bleiben sichtbar. Voraussetzung: init_db.py ausfuehren.
    """
    database_uri = DATABASE_PATH.as_uri() + "?mode=ro"
    with closing(sqlite3.connect(database_uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        # Beide Abfragen lesen denselben Stand der Datenbank.
        connection.execute("BEGIN")
        order_counts = connection.execute(
            """
            SELECT COUNT(*) AS total_order_count,
                   COALESCE(SUM(status = 'offen'), 0) AS open_order_count,
                   COALESCE(SUM(status = 'versendet'), 0) AS shipped_order_count
            FROM orders
            """
        ).fetchone()
        rows = connection.execute(
            """
            WITH open_quantities AS (
                SELECT i.product_id, SUM(i.quantity) AS quantity
                FROM order_items AS i
                JOIN orders AS o ON o.id = i.order_id
                WHERE o.status = 'offen'
                GROUP BY i.product_id
            )
            SELECT p.id AS product_id, p.name, p.color, p.size,
                   p.stock_quantity AS physical_stock,
                   COALESCE(q.quantity, 0) AS open_order_quantity,
                   p.stock_quantity - COALESCE(q.quantity, 0) AS free_stock
            FROM products AS p
            LEFT JOIN open_quantities AS q ON q.product_id = p.id
            ORDER BY p.id
            """
        ).fetchall()

    return {
        "open_order_count": order_counts["open_order_count"],
        "shipped_order_count": order_counts["shipped_order_count"],
        "total_order_count": order_counts["total_order_count"],
        "products": [dict(row) for row in rows],
    }


@mcp.tool()
def calculate_bulk_discount(
    quantity: Annotated[
        int, Field(strict=True, gt=0, description="Positive ganze Anzahl Paar Socken")
    ],
    unit_price_cents: Annotated[
        int, Field(strict=True, ge=0, description="Nicht negativer Stueckpreis in Cent")
    ],
) -> dict[str, int]:
    """Berechnet Mengenrabatt fuer die gesamte Menge, ohne Daten zu veraendern.

    quantity und unit_price_cents muessen ganzzahlig sein, quantity > 0 und
    unit_price_cents >= 0. Unter 10 Paar: 0 %, ab 10: 5 %, ab 50: 10 %,
    ab 100: 15 %. Gibt quantity, discount_percent, amount_before_discount_cents,
    discount_amount_cents und final_amount_cents zurueck.
    Alle Geldbetraege sind ganze Cent. Der Rabatt wird mit Decimal berechnet
    und mit ROUND_HALF_UP auf ganze Cent gerundet.
    """
    if quantity >= 100:
        discount_percent = 15
    elif quantity >= 50:
        discount_percent = 10
    elif quantity >= 10:
        discount_percent = 5
    else:
        discount_percent = 0

    with localcontext() as context:
        context.prec = len(str(quantity)) + len(str(unit_price_cents)) + 10
        amount_before = Decimal(quantity) * Decimal(unit_price_cents)
        discount = (amount_before * Decimal(discount_percent) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        final_amount = amount_before - discount

    return {
        "quantity": quantity,
        "discount_percent": discount_percent,
        "amount_before_discount_cents": int(amount_before),
        "discount_amount_cents": int(discount),
        "final_amount_cents": int(final_amount),
    }


@mcp.tool()
def append_audit_event(description: str) -> dict[str, str]:
    """Haengt ein Ereignis an die fest vorgegebene Datei logs/audit.jsonl an.

    description muss Text sein und mindestens ein Nicht-Leerzeichen enthalten.
    Schreibt genau eine JSON-Zeile mit timestamp (UTC) und description.
    Bestehende Eintraege bleiben erhalten; jeder Aufruf fuegt einen Eintrag hinzu.
    Ein frei waehlbarer Dateipfad ist nicht erlaubt. Gibt status='ok' und den
    UTC-Zeitstempel als Bestaetigung zurueck.
    """
    if not description.strip():
        raise ValueError("Die Ereignisbeschreibung darf nicht leer sein.")

    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    event = {"timestamp": timestamp, "description": description}
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open("a", encoding="utf-8") as audit_file:
        audit_file.write(json.dumps(event, ensure_ascii=False) + "\n")

    return {"status": "ok", "timestamp": timestamp}


if __name__ == "__main__":
    mcp.run(transport="stdio")
