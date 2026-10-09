"""Lager-Dienst: offene Bestellungen ueber MCP lesen."""

import json
from pathlib import Path
import sys

from fastapi import FastAPI, HTTPException
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Lager-Agent")


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "lager"}


@app.get("/orders")
async def get_orders():
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(BASE_DIR / "mcp_server.py")],
        cwd=str(BASE_DIR),
    )

    try:
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "get_open_orders", arguments={}
                )

                if result.isError:
                    raise RuntimeError("MCP-Tool meldet einen Fehler.")

                for content in result.content:
                    if content.type == "text":
                        data = json.loads(content.text)
                        if not isinstance(data.get("open_orders"), list):
                            raise RuntimeError("Unerwartete MCP-Antwort.")
                        return data

                raise RuntimeError("Keine Bestelldaten erhalten.")

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Bestelldaten konnten nicht ueber MCP gelesen werden.",
        ) from None