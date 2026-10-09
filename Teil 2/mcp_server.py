"""MCP-Tools fuer den Lager-Assistenten, erreichbar ueber stdio."""

from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import json
from pathlib import Path
import sqlite3
from typing import Annotated
import httpx

from mcp.server.fastmcp import FastMCP
from pydantic import BeforeValidator, Field


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "data" / "lager.db"
AUDIT_PATH = BASE_DIR / "logs" / "audit.jsonl"

mcp = FastMCP("Versand-Assistent")


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


def validate_euro_price(value: object) -> Decimal:
    """Prueft einen Europreis und wandelt ihn ohne Float-Rechnung in Decimal um."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError("Der Europreis muss eine Zahl mit hoechstens zwei Nachkommastellen sein.")
    try:
        price = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Der Europreis ist keine gueltige Dezimalzahl.") from error
    if not price.is_finite():
        raise ValueError("Der Europreis muss endlich sein; NaN und Infinity sind ungueltig.")
    if price < 0:
        raise ValueError("Der Europreis darf nicht negativ sein.")
    if price.as_tuple().exponent < -2:
        raise ValueError("Der Europreis darf hoechstens zwei Nachkommastellen haben.")
    return price


@mcp.tool()
def calculate_bulk_discount(
    quantity: Annotated[
        int, Field(strict=True, gt=0, description="Positive ganze Anzahl Paar Socken")
    ],
    unit_price_euros: Annotated[
        Decimal,
        BeforeValidator(validate_euro_price),
        Field(description="Nicht negativer Euro-Stueckpreis, z. B. 12.50; hoechstens zwei Nachkommastellen"),
    ],
) -> dict[str, int | str]:
    """Berechnet Mengenrabatt fuer die gesamte Menge, ohne Daten zu veraendern.

    quantity ist eine positive ganze Anzahl. unit_price_euros ist ein nicht
    negativer Europreis mit hoechstens zwei Nachkommastellen. Unter 10 Paar:
    0 %, ab 10: 5 %, ab 50: 10 %, ab 100: 15 %. Der Rabatt gilt fuer die
    gesamte Menge. Gibt quantity, discount_percent sowie
    amount_before_discount_euros, discount_amount_euros und final_amount_euros
    als Dezimalstrings mit genau zwei Nachkommastellen zurueck. Der Rabatt
    wird mit ROUND_HALF_UP auf Cent gerundet. Preise duerfen auch als
    Dezimalstring uebergeben werden, damit alle Stellen exakt erhalten bleiben.
    """
    unit_price_euros = validate_euro_price(unit_price_euros)
    if quantity >= 100:
        discount_percent = 15
    elif quantity >= 50:
        discount_percent = 10
    elif quantity >= 10:
        discount_percent = 5
    else:
        discount_percent = 0

    with localcontext() as context:
        context.prec = max(
            28, len(unit_price_euros.as_tuple().digits) + len(str(quantity)) + 10
        )
        unit_price_cents = int(unit_price_euros * Decimal(100))
        amount_before_cents = quantity * unit_price_cents
        discount_cents = (Decimal(amount_before_cents) * Decimal(discount_percent) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        discount_cents = int(discount_cents)
        final_amount_cents = amount_before_cents - discount_cents

    return {
        "quantity": quantity,
        "discount_percent": discount_percent,
        "amount_before_discount_euros": f"{amount_before_cents // 100}.{amount_before_cents % 100:02d}",
        "discount_amount_euros": f"{discount_cents // 100}.{discount_cents % 100:02d}",
        "final_amount_euros": f"{final_amount_cents // 100}.{final_amount_cents % 100:02d}",
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

@mcp.tool()
def get_open_orders() -> dict[str, object]:
    """Liest offene Bestellungen mit Positionen, aelteste zuerst.

    Sortierung nach created_at, bei gleichem Zeitpunkt nach Bestell-ID.
    Mengen sind Paar Socken. physical_stock ist der aktuelle physische
    Produktbestand, kein pro Bestellung reservierter Bestand.
    Dieses Tool veraendert keine Daten.
    """
    database_uri = DATABASE_PATH.as_uri() + "?mode=ro"

    with closing(sqlite3.connect(database_uri, uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")

        orders = connection.execute(
            """
            SELECT id AS order_id, created_at
            FROM orders
            WHERE status = 'offen'
            ORDER BY created_at, id
            """
        ).fetchall()

        result = []
        for order in orders:
            items = connection.execute(
                """
                SELECT i.product_id, p.name, p.color, p.size,
                       i.quantity,
                       p.stock_quantity AS physical_stock
                FROM order_items AS i
                JOIN products AS p ON p.id = i.product_id
                WHERE i.order_id = ?
                ORDER BY i.id
                """,
                (order["order_id"],),
            ).fetchall()

            result.append({
                "order_id": order["order_id"],
                "created_at": order["created_at"],
                "items": [dict(item) for item in items],
            })

    return {"open_orders": result}

@mcp.tool()
async def get_shipping_plan() -> dict[str, object]:
    """Erstellt einen simulierten Versandplan ueber den Koordinator.

    Der Koordinator findet Lager und Versand dynamisch in der Registry.
    Nur vollstaendige Bestellungen werden eingeplant, aelteste zuerst.
    Zurueckgestellte Bestellungen enthalten konkrete Fehlpositionen.
    Veraendert weder Datenbank noch Audit-Log.
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "http://127.0.0.1:8000/shipping-plan"
        )
        response.raise_for_status()
        return response.json()

if __name__ == "__main__":
    mcp.run(transport="stdio")
