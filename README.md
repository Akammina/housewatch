# HouseWatch

A real-time fraud and abuse detection engine for betting platforms. It watches
account and betting activity, scores every account for risk, and shows what it
finds (and why) on a live analyst dashboard.

It's built to defend [FairHouse](https://github.com/Akammina/FairHouse-), a
provably-fair casino: FairHouse forwards its bets to HouseWatch, and an attack
simulator injects synthetic fraud so you can watch the engine catch it live.

![Dashboard](docs/dashboard.png)

## What it detects

| Detector | Catches | How it works |
|----------|---------|--------------|
| **Win-rate anomaly** | cheating / bug exploits | Every game's true RTP and return variance were measured in the FairHouse [math lab](https://github.com/Akammina/FairHouse-/tree/main/math-lab). Given how many bets an account has placed, HouseWatch z-scores its realised return against that. Sitting 6+ sigma above expected isn't luck. |
| **Bot timing** | automated play | Humans bet irregularly; bots don't. Flags near-constant inter-bet gaps (machine-regular) or a superhuman sustained bet rate. |
| **Multi-accounting** | bonus-abuse rings | Links accounts that share a device fingerprint or IP (union-find over the graph), then flags any cluster big enough to be a ring rather than a coincidence. |
| **Loss-chasing** | player harm (responsible gambling) | Measures the *rate* of stake increases right after a loss. A chaser does it almost every time; a player with varied stakes doesn't. Tuned to avoid false positives. |

Each account gets a **0-100 risk score** with a severity level and a plain-English
reason for every signal. Explainability is the point: an analyst has to trust why
an account was flagged, not just see a number.

## The signature: catching a cheat with the game's own math

The win-rate detector is the interesting one. Because the math lab measured each
game's expected return and its variance, HouseWatch knows exactly how an honest
player's results should be distributed:

```
expected = sum( stake_i * rtp(game_i) )
variance = sum( (stake_i * return_std(game_i))^2 )     # independent bets
z        = (realised_return - expected) / sqrt(variance)
```

A player 6+ sigma above expected over thousands of bets is exploiting a bug or a
tampered RNG. In the demo, the "cheater" is caught at around 7-9 sigma.

## Architecture

```
FairHouse (betting platform) ──emits bet events──┐
                                                  ▼
Attack simulator ──synthetic fraud──►  POST /ingest
                                                  │
                                          ┌───────▼────────┐
                                          │  risk engine   │  streaming aggregates
                                          │  (detectors +  │  per account (O(1)/event)
                                          │   scoring)     │
                                          └───────┬────────┘
                                                  │ alerts
                                          SSE ────▼────►  live dashboard
```

Services talk over events (an ingest endpoint), not a shared database, so the
platform and the monitor are decoupled. The engine keeps per-account running
aggregates (expected return, variance, inter-bet gaps via Welford) so each event
is scored in O(1) instead of rescanning history.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pytest                                  # detector + engine tests
uvicorn api.main:app --port 8000        # engine + dashboard at http://localhost:8000
python -m simulator.attack              # inject synthetic traffic + attacks
#   add --delay 0.02 to watch alerts land on the dashboard live
```

Open `http://localhost:8000` and watch the ring, bot, cheater, and chaser get
flagged while the 18 normal players stay clear.

### Wiring in the real platform (optional)

Start FairHouse with `HOUSEWATCH_URL=http://localhost:8000` and it forwards every
real bet to `/ingest` (fire-and-forget: if HouseWatch is down, gameplay is
unaffected).

## API

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/ingest` | receive a bet event |
| GET | `/stream` | Server-Sent Events: alerts pushed live |
| GET | `/accounts` | flagged accounts, highest risk first |
| GET | `/alerts` | recent alerts |
| GET | `/summary` | headline counts |
| GET | `/` | the dashboard |

## Layout

```
housewatch/
  housewatch/
    events.py            bet event schema
    games.py             per-game RTP + return std (from the math lab)
    store.py             in-memory state + streaming aggregates
    engine.py            runs detectors, combines signals, raises alerts
    detectors/           win_rate, bot_timing, multi_account, responsible
  api/main.py            FastAPI: /ingest, SSE, dashboard
  simulator/attack.py    synthetic normal players + attackers
  static/dashboard.html  the live analyst console
  tests/                 detector + engine tests
```

## Tech

Python 3 · FastAPI · Server-Sent Events · union-find · online statistics
(Welford, z-scores) · pytest. No heavy ML libraries: the detections are
transparent statistics an analyst can reason about.
