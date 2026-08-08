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


GAMES = ["dice", "coinflip", "limbo", "wheel", "roulette", "keno", "slots"]


def _reseed() -> None:
    """Start the demo fresh (also used to keep the hosted instance bounded)."""
    global engine
    from simulator.attack import generate
    engine = Engine()
    for ev in generate():
        engine.ingest(Bet.from_json(ev))


@app.on_event("startup")
async def seed_demo() -> None:
    """On the hosted demo (SEED_DEMO=1), fill the dashboard on boot and keep a
    realistic stream going: mostly honest players, the occasional attack. Off for
    local dev."""
    if not os.getenv("SEED_DEMO"):
        return
    _reseed()
    from simulator.attack import multiplier
    asyncio.create_task(_inject_forever(multiplier))


async def _inject_forever(multiplier) -> None:
    import random
    n = 0
    while True:
        await asyncio.sleep(12)
        n += 1
        now = time.time()
        # steady stream of honest players, so the flagged share stays realistic
        for k in range(random.randint(3, 6)):
            acc, dev, ip = f"live_user_{n}_{k}", f"lu_{n}_{k}", f"70.{n % 250}.{k}.{random.randint(2, 250)}"
            ts = now - random.uniform(0, 40)
            for _ in range(random.randint(30, 90)):
                ts += random.lognormvariate(1.6, 0.8)
                g = random.choice(GAMES)
                stake = random.choice([10, 20, 50, 100]) * 100
                engine.ingest(Bet(acc, g, stake, round(stake * multiplier(g)), ts, dev, ip))
        # every so often, an actual attack, so the alert feed shows a fresh catch
        if random.random() < 0.55:
            if random.random() < 0.5:   # bonus-abuse ring
                dev = f"live_ring_{n}"
                for r in range(random.randint(5, 7)):
                    for _ in range(4):
                        broadcast(engine.ingest(Bet(f"live_promo_{n}_{r}", "dice", 1000,
                                  round(1000 * multiplier("dice")), now, dev, f"88.{n % 250}.0.9")))
            else:                        # a bot (varied game/stake, so separate bots don't look like one ring)
                acc, ts = f"live_bot_{n}", now
                g, stake = random.choice(GAMES), random.choice([10, 20, 50, 100, 200]) * 100
                for _ in range(70):
                    ts += 0.2
                    broadcast(engine.ingest(Bet(acc, g, stake,
                              round(stake * multiplier(g)), ts, f"live_botdev_{n}", f"91.{n % 250}.0.7")))
        if len(engine.store.accounts) > 400:  # keep memory + the dashboard bounded
            _reseed()


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
