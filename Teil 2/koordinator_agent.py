"""Koordiniert Lager und Versand durch dynamische Registry-Suche."""

import os

import httpx
from fastapi import FastAPI, HTTPException


REGISTRY_URL = os.getenv(
    "REGISTRY_URL", "http://127.0.0.1:8003"
).rstrip("/")

app = FastAPI(title="Koordinator-Agent")


async def find_agent(client: httpx.AsyncClient, capability: str) -> dict:
    response = await client.get(
        f"{REGISTRY_URL}/lookup",
        params={"capability": capability},
    )
    response.raise_for_status()
    return response.json()


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "koordinator"}


@app.post("/shipping-plan")
async def shipping_plan():
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            lager = await find_agent(client, "read_open_orders")
            versand = await find_agent(client, "plan_shipping")

            print(
                f"[Registry] Lager: {lager['url']} | "
                f"Versand: {versand['url']}",
                flush=True,
            )

            orders_response = await client.get(
                lager["url"].rstrip("/") + "/orders"
            )
            orders_response.raise_for_status()
            orders = orders_response.json()

            print("[Lager] Bestellungen erhalten.", flush=True)

            plan_response = await client.post(
                versand["url"].rstrip("/") + "/plan",
                json=orders,
            )
            plan_response.raise_for_status()
            plan = plan_response.json()

            print("[Versand] Versandplan erhalten.", flush=True)

            return {
                "coordinator": "koordinator",
                "selected_agents": {
                    "lager": lager,
                    "versand": versand,
                },
                "plan": plan,
            }

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Zeitlimit beim Aufruf eines Dienstes erreicht.",
        ) from None
    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="Registry oder Fachdienst nicht erfolgreich erreichbar.",
        ) from None