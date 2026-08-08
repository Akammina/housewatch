"""Red-team harness: generate synthetic traffic (normal players plus attackers)
and post it to HouseWatch's /ingest, so we can prove the detectors actually fire.
This is how you validate a fraud system: inject known-bad activity and check it's
caught. All data here is synthetic.

Actors:
  * ~18 normal players  - human timing, honest results, unique device/IP
  * a 6-account bonus-abuse ring - all sharing one device + IP
  * a betting bot        - metronome timing, high volume
  * a cheater            - impossibly high win rate (simulated exploit)
  * a problem gambler    - chasing losses, escalating stakes

Run (engine must be up):  python -m simulator.attack --url http://localhost:8000
Add --delay 0.02 to watch it land on the dashboard live.
"""
from __future__ import annotations

import argparse
import random
import time

import httpx

from housewatch.games import GAME_STATS

GAMES = list(GAME_STATS)
BASE_TS = 1_700_000_000.0


def multiplier(game: str, cheat: float = 1.0) -> float:
    """Two-outcome model matching each game's mean return and variance: win a
    multiplier m with probability p (else 0), where p*m = RTP. `cheat` > 1 inflates
    the win probability to simulate an exploit."""
    mu, sd = GAME_STATS[game]
    m = (sd * sd + mu * mu) / mu
    p = min(0.99, (mu / m) * cheat)
    return m if random.random() < p else 0.0


def bet(account, game, stake_cents, ts, device, ip, cheat=1.0) -> dict:
    return {
        "account": account, "game": game, "stake_cents": stake_cents,
        "payout_cents": round(stake_cents * multiplier(game, cheat)),
        "ts": ts, "device": device, "ip": ip,
    }


def generate() -> list[dict]:
    events: list[dict] = []

    # normal players: human timing (high variance), honest odds, own device/IP
    for u in range(18):
        acc, dev, ip = f"user_{u:03d}", f"dev_{u:03d}", f"77.10.{u}.{random.randint(2, 250)}"
        ts = BASE_TS + random.uniform(0, 60)
        for _ in range(random.randint(60, 160)):
            ts += random.lognormvariate(1.6, 0.8)  # ~5s median gap, irregular
            events.append(bet(acc, random.choice(GAMES), random.choice([10, 20, 50, 100]) * 100, ts, dev, ip))

    # bonus-abuse ring: 6 accounts, same device + IP, a few bets each
    for r in range(6):
        acc, ts = f"promo_{r}", BASE_TS + random.uniform(0, 120)
        for _ in range(random.randint(4, 9)):
            ts += random.uniform(3, 20)
            events.append(bet(acc, random.choice(GAMES), 1000, ts, "dev_RING", "10.0.0.9"))

    # betting bot: metronome timing, high volume
    ts = BASE_TS
    for _ in range(320):
        ts += 0.2 + random.uniform(-0.01, 0.01)
        events.append(bet("bot_alpha", "dice", 5000, ts, "dev_BOT", "203.0.113.7"))

    # cheater: impossible win rate over enough bets to be unmistakable
    ts = BASE_TS
    for _ in range(700):
        ts += random.uniform(2, 10)
        events.append(bet("ghost_9", "dice", 2000, ts, "dev_GHOST", "198.51.100.4", cheat=1.3))

    # problem gambler: chase losses (raise stake after a loss), stakes escalate
    ts, stake = BASE_TS, 1000
    for _ in range(45):
        ts += random.uniform(4, 15)
        ev = bet("chaser_1", "dice", stake, ts, "dev_CHASE", "45.12.6.33")
        events.append(ev)
        stake = min(500_000, int(stake * 2.2)) if ev["payout_cents"] == 0 else 1000

    events.sort(key=lambda e: e["ts"])
    return events


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--delay", type=float, default=0.0, help="seconds between events (for a live demo)")
    args = ap.parse_args()

    events = generate()
    print(f"posting {len(events)} synthetic events to {args.url}")
    with httpx.Client(base_url=args.url, timeout=10) as c:
        for i, ev in enumerate(events):
            c.post("/ingest", json=ev)
            if args.delay:
                time.sleep(args.delay)
            if i % 250 == 0 and i:
                print(f"  {i}/{len(events)}")
    print("done")


if __name__ == "__main__":
    main()
