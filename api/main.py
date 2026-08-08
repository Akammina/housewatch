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
import os
import time
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


def broadcast(alerts: list[dict]) -> None:
    for alert in alerts:
        for q in list(subscribers):
            q.put_nowait(alert)


@app.on_event("startup")
async def seed_demo() -> None:
    """On the hosted demo (SEED_DEMO=1), fill the dashboard on boot and keep
    injecting fresh attacks so the live feed actually moves. Off for local dev."""
    if not os.getenv("SEED_DEMO"):
        return
    from simulator.attack import generate, multiplier
    for ev in generate():
        engine.ingest(Bet.from_json(ev))
    asyncio.create_task(_inject_forever(multiplier))


async def _inject_forever(multiplier) -> None:
    import random
    n = 0
    while True:
        await asyncio.sleep(20)
        n += 1
        now = time.time()
        if random.random() < 0.5:   # a fresh bonus-abuse ring
            dev = f"live_ring_{n}"
            for r in range(random.randint(5, 7)):
                for _ in range(4):
                    broadcast(engine.ingest(Bet(f"live_promo_{n}_{r}", "dice", 1000,
                              round(1000 * multiplier("dice")), now, dev, f"88.{n % 250}.0.9")))
        else:                        # a fresh bot
            acc, ts = f"live_bot_{n}", now
            for _ in range(60):
                ts += 0.2
                broadcast(engine.ingest(Bet(acc, "dice", 5000,
                          round(5000 * multiplier("dice")), ts, f"live_botdev_{n}", f"91.{n % 250}.0.7")))


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
    broadcast(alerts)
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
