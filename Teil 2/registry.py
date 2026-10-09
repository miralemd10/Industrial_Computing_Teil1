"""Lokale Registry fuer die Dienste des Versand-Systems."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, HttpUrl


app = FastAPI(title="Agent Registry")


class AgentRegistration(BaseModel):
    name: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    url: HttpUrl


agents: dict[str, AgentRegistration] = {}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "registry"}


@app.post("/register")
async def register_agent(agent: AgentRegistration):
    agents[agent.name] = agent
    return {"status": "registered", "agent": agent}


@app.get("/agents")
async def list_agents():
    return {"agents": list(agents.values())}


@app.get("/lookup")
async def lookup_agent(capability: str):
    matches = [
        agent for agent in agents.values()
        if agent.capability == capability
    ]
    if not matches:
        raise HTTPException(404, "Keine passende Faehigkeit registriert.")
    if len(matches) > 1:
        raise HTTPException(409, "Mehrere passende Dienste registriert.")
    return matches[0]