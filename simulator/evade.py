"""Red-team harness: try to fool HouseWatch.

For each detector we run an "obvious" attack (should be caught) and a "smart"
evasion (a real attacker's counter-move), then report which slipped through. The
last section shows defense in depth: cheating spread across accounts evades the
per-account detectors but still trips the platform-level game-integrity monitor.

Runs the engine directly, no server needed:  python -m simulator.evade
"""
from __future__ import annotations

import random

from housewatch.engine import Engine
from housewatch.events import Bet
from .attack import multiplier

random.seed(7)

human = lambda: random.lognormvariate(1.4, 0.8)           # irregular, ~4s median
fast_regular = lambda: 0.2 + random.uniform(-0.01, 0.01)  # 200ms metronome


def feed(eng, account, game, n, *, cheat=1.0, gap_fn=human, device, ip, stake=2000, t0=1_700_000_000.0):
    ts = t0
    for _ in range(n):
        ts += gap_fn()
        eng.ingest(Bet(account, game, stake, round(stake * multiplier(game, cheat)), ts, device, ip))


def acct_verdict(eng, account):
    p = eng.profiles.get(account)
    if p and p.score >= 60:
        top = max(p.signals, key=lambda s: s.score)
        return f"CAUGHT   {p.score:>5.0f} [{p.level:<8}] {top.reason[:66]}"
    return f"EVADED   {(p.score if p else 0):>5.0f} (below alert threshold)"


def line(label, result):
    print(f"  {label:<36} {result}")


def main():
    eng = Engine()

    print("\nWIN-RATE ANOMALY")
    feed(eng, "cheat_obvious", "dice", 700, cheat=1.3, device="d1", ip="1.1.1.1")
    line("obvious cheat (dice, +30%)", acct_verdict(eng, "cheat_obvious"))
    feed(eng, "cheat_stealth", "dice", 700, cheat=1.04, device="d2", ip="1.1.1.2")
    line("stealth cheat (dice, +4%)", acct_verdict(eng, "cheat_stealth"))
    feed(eng, "cheat_slots", "slots", 700, cheat=1.3, device="d3", ip="1.1.1.3")
    line("cheat on slots (high variance)", acct_verdict(eng, "cheat_slots"))

    print("\nBOT TIMING")
    feed(eng, "bot_obvious", "dice", 320, gap_fn=fast_regular, device="d4", ip="2.2.2.1")
    line("obvious bot (200ms metronome)", acct_verdict(eng, "bot_obvious"))
    feed(eng, "bot_jitter", "dice", 320, device="d5", ip="2.2.2.2")
    line("smart bot (human-like jitter)", acct_verdict(eng, "bot_jitter"))

    print("\nMULTI-ACCOUNTING")
    for r in range(6):
        feed(eng, f"ring_obvious_{r}", "dice", 6, device="RING", ip="3.3.3.3")
    line("obvious ring (shared device/IP)", acct_verdict(eng, "ring_obvious_0"))
    for r in range(6):
        feed(eng, f"ring_spoof_{r}", "dice", 6, device=f"uniq_{r}", ip=f"4.4.4.{r}")
    line("distributed ring (rotated fp/IP)", acct_verdict(eng, "ring_spoof_0"))

    # A slots exploit farmed across 30 fresh accounts, ~150 bets each. No single
    # account is a statistical outlier, but the game's overall RTP is wrecked.
    print("\nDEFENSE IN DEPTH  (distributed slots exploit, 30 accounts)")
    for a in range(30):
        feed(eng, f"exploit_{a}", "slots", 150, cheat=1.5, device=f"x_{a}", ip=f"5.5.{a}.9")
    line("per-account view", acct_verdict(eng, "exploit_0"))
    integrity = [x for x in eng.alerts if x["category"] == "integrity" and x["account"] == "game:slots"]
    if integrity:
        line("platform monitor", f"CAUGHT   {integrity[0]['score']:>5.0f} [{integrity[0]['level']}] {integrity[0]['reason'][:66]}")
    else:
        line("platform monitor", "EVADED   (game-integrity monitor did not fire)")
    print()


if __name__ == "__main__":
    main()
