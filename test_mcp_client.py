"""Kleiner MCP-Testclient ohne KI-Zugang; schreibt einen Audit-Testeintrag."""

import argparse
import asyncio
from datetime import datetime, timedelta
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

            for quantity, percent in ((9, 0), (10, 5), (49, 5), (50, 10),
                                      (99, 10), (100, 15)):
                discount = await call_tool(session, "calculate_bulk_discount", {
                    "quantity": quantity, "unit_price_cents": 100,
                })
                amount_before = quantity * 100
                discount_amount = quantity * percent
                assert discount == {
                    "quantity": quantity,
                    "discount_percent": percent,
                    "amount_before_discount_cents": amount_before,
                    "discount_amount_cents": discount_amount,
                    "final_amount_cents": amount_before - discount_amount,
                }
                print(f"Rabatt: {quantity} Paar -> {percent} %, Endbetrag {discount['final_amount_cents']} Cent.")

            rounded = await call_tool(session, "calculate_bulk_discount", {
                "quantity": 10, "unit_price_cents": 1,
            })
            assert rounded["discount_amount_cents"] == 1
            assert rounded["final_amount_cents"] == 9
            free = await call_tool(session, "calculate_bulk_discount", {
                "quantity": 10, "unit_price_cents": 0,
            })
            assert free["final_amount_cents"] == 0

            for arguments in (
                {"quantity": 0, "unit_price_cents": 100},
                {"quantity": -1, "unit_price_cents": 100},
                {"quantity": 1, "unit_price_cents": -1},
                {"quantity": 1.5, "unit_price_cents": 100},
                {"quantity": 1, "unit_price_cents": 1.5},
                {"quantity": True, "unit_price_cents": 100},
            ):
                result = await session.call_tool("calculate_bulk_discount", arguments)
                assert result.isError, f"Ungueltige Eingaben akzeptiert: {arguments}"
            for description in ("", " \n\t "):
                result = await session.call_tool("append_audit_event", {
                    "description": description,
                })
                assert result.isError, "Leere Ereignisbeschreibung akzeptiert"
            print("Validierung: ungueltige Eingaben abgewiesen; halber Cent aufgerundet, Preis 0 erlaubt.")

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
