"""Versandplanung ohne Aenderung der Datenbank."""

from collections import defaultdict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(title="Versand-Agent")


class Position(BaseModel):
    product_id: int = Field(strict=True, gt=0)
    name: str
    color: str
    size: str
    quantity: int = Field(strict=True, gt=0)
    physical_stock: int = Field(strict=True, ge=0)


class Bestellung(BaseModel):
    order_id: int = Field(strict=True, gt=0)
    created_at: str
    items: list[Position] = Field(min_length=1)


class PlanAnfrage(BaseModel):
    open_orders: list[Bestellung]


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "versand"}


@app.post("/plan")
async def create_plan(request: PlanAnfrage):
    remaining = {}
    products = {}
    seen_orders = set()

    for order in request.open_orders:
        if order.order_id in seen_orders:
            raise HTTPException(422, "Doppelte Bestell-ID.")
        seen_orders.add(order.order_id)

        for item in order.items:
            pid = item.product_id
            if pid in remaining and remaining[pid] != item.physical_stock:
                raise HTTPException(422, "Widerspruechliche Produktbestaende.")
            remaining[pid] = item.physical_stock
            products[pid] = {
                "product_id": pid,
                "name": item.name,
                "color": item.color,
                "size": item.size,
            }

    results = []
    orders = sorted(
        request.open_orders,
        key=lambda order: (order.created_at, order.order_id),
    )

    for order in orders:
        required = defaultdict(int)
        for item in order.items:
            required[item.product_id] += item.quantity

        shortages = []
        for pid, quantity in required.items():
            available = remaining[pid]
            if quantity > available:
                shortages.append({
                    **products[pid],
                    "required_quantity": quantity,
                    "available_quantity": available,
                    "missing_quantity": quantity - available,
                })

        if not shortages:
            for pid, quantity in required.items():
                remaining[pid] -= quantity

        results.append({
            "order_id": order.order_id,
            "created_at": order.created_at,
            "status": "zurueckgestellt" if shortages else "versandbereit",
            "shortages": shortages,
        })

    return {
        "simulation": True,
        "orders": results,
        "remaining_plan_stock": [
            {"product_id": pid, "quantity": remaining[pid]}
            for pid in sorted(remaining)
        ],
    }