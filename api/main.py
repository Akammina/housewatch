"""HouseWatch API + live dashboard.

  POST /ingest    receive a bet event (from FairHouse or the attack simulator)
  GET  /stream    Server-Sent Events: new alerts pushed live to the dashboard
  GET  /accounts  current flagged accounts, highest risk first
  GET  /alerts    recent alerts
  GET  /summary   headline counts
  GET  /          the analyst dashboard (static HTML)

Run:  uvicorn api.main:app --reload   (from the housewatch/ directory)
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from housewatch.engine import Engine
from housewatch.events import Bet

app = FastAPI(title="HouseWatch", version="1.0.0")
engine = Engine()

# live SSE subscribers (each is an asyncio queue of alert dicts)
subscribers: set[asyncio.Queue] = set()
STATIC = Path(__file__).resolve().parent.parent / "static"


class BetIn(BaseModel):
    account: str
    game: str = "unknown"
    stake_cents: int
    payout_cents: int = 0
    ts: float
    device: str = ""
    ip: str = ""


@app.post("/ingest")
async def ingest(bet: BetIn) -> dict:
    alerts = engine.ingest(Bet(**bet.model_dump()))
    for alert in alerts:
        for q in list(subscribers):
            q.put_nowait(alert)
    return {"ok": True, "new_alerts": len(alerts)}


@app.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    q: asyncio.Queue = asyncio.Queue()
    subscribers.add(q)

    async def gen():
        try:
            # replay the recent alerts so a freshly-opened dashboard isn't empty
            for alert in engine.alerts[-25:]:
                yield f"data: {json.dumps(alert)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    alert = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(alert)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            subscribers.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/accounts")
def accounts(min_score: float = 40.0) -> list[dict]:
    return [p.to_json() for p in engine.flagged(min_score)]


@app.get("/alerts")
def alerts() -> list[dict]:
    return list(reversed(engine.alerts[-100:]))


@app.get("/summary")
def summary() -> dict:
    return engine.summary()


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(STATIC / "dashboard.html")
