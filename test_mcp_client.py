"""Kleiner MCP-Testclient ohne KI-Zugang; schreibt einen Audit-Testeintrag."""

import argparse
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


BASE_DIR = Path(__file__).resolve().parent


async def call_tool(
    session: ClientSession, name: str, arguments: dict[str, object]
) -> dict[str, object]:
    result = await session.call_tool(name, arguments)
    assert not result.isError, f"{name}: {result.content}"
    assert result.structuredContent is not None, f"{name}: Ergebnis fehlt"
    return result.structuredContent


def expected_discount(quantity: int, price_euros: object, percent: int) -> dict[str, object]:
    amount = Decimal(str(price_euros)) * quantity
    discount = (amount * Decimal(percent) / Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    final = amount - discount
    return {
        "quantity": quantity,
        "discount_percent": percent,
        "amount_before_discount_euros": f"{amount:.2f}",
        "discount_amount_euros": f"{discount:.2f}",
        "final_amount_euros": f"{final:.2f}",
    }


async def main(read_only: bool = False) -> None:
    database_path = BASE_DIR / "data" / "lager.db"
    audit_path = BASE_DIR / "logs" / "audit.jsonl"
    database_before = database_path.read_bytes()
    audit_before = audit_path.read_bytes() if audit_path.exists() else b""
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(BASE_DIR / "mcp_server.py")],
        # Prueft auch die Unabhaengigkeit vom Arbeitsverzeichnis.
        cwd=tempfile.gettempdir(),
    )

    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            assert {tool.name for tool in tools} == {
                "get_inventory_and_orders",
                "calculate_bulk_discount",
                "append_audit_event",
            }
            assert len(tools) == 3
            assert all(tool.description for tool in tools)
            print("Tool-Erkennung: genau drei Tools mit Beschreibungen.")

            discount_tool = next(tool for tool in tools if tool.name == "calculate_bulk_discount")
            assert discount_tool.inputSchema["required"] == ["quantity", "unit_price_euros"]
            assert set(discount_tool.inputSchema["properties"]) == {"quantity", "unit_price_euros"}

            inventory = await call_tool(session, "get_inventory_and_orders", {})
            assert inventory["open_order_count"] == 3
            assert inventory["shipped_order_count"] == 2
            assert inventory["total_order_count"] == 5
            assert (inventory["open_order_count"] + inventory["shipped_order_count"]
                    == inventory["total_order_count"])
            products = inventory["products"]
            assert len(products) == 4
            expected_quantities = {1: (30, 3, 27), 2: (25, 3, 22),
                                   3: (35, 1, 34), 4: (20, 2, 18)}
            for product in products:
                assert (product["physical_stock"], product["open_order_quantity"],
                        product["free_stock"]) == expected_quantities[product["product_id"]]
                assert all(product[field] for field in ("name", "color", "size"))
            print("Lager: 4 Produkte, 3 offene, 2 versendete, 5 Bestellungen insgesamt; Mengen und freie Bestaende korrekt.")

            cases = (
                (5, 3.21, 0), (25, 3.21, 5), (75, 3.21, 10), (125, 3.21, 15),
                (9, 1.00, 0), (10, 1.00, 5), (11, 1.00, 5),
                (49, 1.00, 5), (50, 1.00, 10), (51, 1.00, 10),
                (99, 1.00, 10), (100, 1.00, 15), (101, 1.00, 15),
            )
            for quantity, price, percent in cases:
                result = await call_tool(session, "calculate_bulk_discount", {
                    "quantity": quantity, "unit_price_euros": price,
                })
                assert result == expected_discount(quantity, price, percent)

            example = await call_tool(session, "calculate_bulk_discount", {
                "quantity": 10, "unit_price_euros": 12.50,
            })
            assert example == {
                "quantity": 10, "discount_percent": 5,
                "amount_before_discount_euros": "125.00",
                "discount_amount_euros": "6.25", "final_amount_euros": "118.75",
            }
            half_cent = await call_tool(session, "calculate_bulk_discount", {
                "quantity": 10, "unit_price_euros": 0.01,
            })
            assert half_cent == {
                "quantity": 10, "discount_percent": 5,
                "amount_before_discount_euros": "0.10",
                "discount_amount_euros": "0.01", "final_amount_euros": "0.09",
            }
            string_price = await call_tool(session, "calculate_bulk_discount", {
                "quantity": 10, "unit_price_euros": "12.50",
            })
            assert string_price == example
            free = await call_tool(session, "calculate_bulk_discount", {
                "quantity": 10, "unit_price_euros": 0,
            })
            assert free == expected_discount(10, 0, 5)
            print("Europreise: Staffelgrenzen, Beispiel 12.50, Rundung bei 0.01 und Preis 0 bestanden.")

            invalid_inputs = (
                {"quantity": 0, "unit_price_euros": 1.00},
                {"quantity": -1, "unit_price_euros": 1.00},
                {"quantity": 10, "unit_price_euros": -1.00},
                {"quantity": 10, "unit_price_euros": True},
                {"quantity": 10, "unit_price_euros": False},
                {"quantity": 10, "unit_price_euros": 1.001},
                {"quantity": 10, "unit_price_euros": "12.500"},
                {"quantity": 10, "unit_price_euros": float("nan")},
                {"quantity": 10, "unit_price_euros": float("inf")},
                {"quantity": 10, "unit_price_euros": float("-inf")},
                {"quantity": 10, "unit_price_euros": None},
                {"quantity": 10, "unit_price_euros": "ungueltig"},
                {"quantity": 1.5, "unit_price_euros": 1.00},
                {"quantity": True, "unit_price_euros": 1.00},
                {"unit_price_euros": 1.00},
                {"quantity": 10},
                {},
            )
            for arguments in invalid_inputs:
                result = await session.call_tool("calculate_bulk_discount", arguments)
                assert result.isError, f"Ungueltige Eingaben akzeptiert: {arguments}"
                if arguments.get("unit_price_euros") == 1.001:
                    error_text = " ".join(
                        item.text for item in result.content if item.type == "text"
                    )
                    assert "hoechstens zwei Nachkommastellen" in error_text
            for description in ("", " \n\t "):
                result = await session.call_tool("append_audit_event", {
                    "description": description,
                })
                assert result.isError, "Leere Ereignisbeschreibung akzeptiert"
            print(f"Validierung: {len(invalid_inputs)} ungueltige Eingaben abgewiesen.")

            if read_only:
                print("Audit-Schreibtest uebersprungen (--read-only).")
            else:
                description = "MCP-Test: Lager und Rabatt erfolgreich geprueft.\nOhne KI-Zugang."
                confirmation = await call_tool(session, "append_audit_event", {
                    "description": description,
                })
                assert confirmation["status"] == "ok"
                audit_after = audit_path.read_bytes()
                assert audit_after.startswith(audit_before)
                added_lines = audit_after[len(audit_before):].decode("utf-8").splitlines()
                assert len(added_lines) == 1
                event = json.loads(added_lines[0])
                assert event == {"timestamp": confirmation["timestamp"],
                                 "description": description}
                assert datetime.fromisoformat(event["timestamp"]).utcoffset() == timedelta(0)
                print("Audit: genau eine JSON-Zeile mit UTC-Zeitstempel angehaengt.")

    assert database_path.read_bytes() == database_before
    if read_only:
        audit_after = audit_path.read_bytes() if audit_path.exists() else b""
        assert audit_after == audit_before
    print("Alle MCP-Tests erfolgreich; Lagerdatenbank unveraendert.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--read-only", action="store_true",
                        help="prueft MCP-Tools, ohne einen Audit-Eintrag zu schreiben")
    asyncio.run(main(read_only=parser.parse_args().read_only))
