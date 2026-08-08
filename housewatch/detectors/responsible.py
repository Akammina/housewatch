"""Responsible-gambling / player-harm signals.

Not fraud: this protects the player, which regulators require. The marker we look
for is loss-chasing (the Martingale pattern): raising the stake right after a loss,
again and again.

The trick is not to flag normal players who just vary their stakes. A player who
picks random stakes will, by chance, sometimes raise after a loss. A chaser does it
*almost every time*. So we don't count raw occurrences, we measure the rate: of all
the bets that followed a loss, what share raised the stake sharply? A high rate over
enough losses is the real signal.
"""
from __future__ import annotations

from ..models import Signal
from ..store import AccountState

MIN_AFTER_LOSS = 8   # need enough post-loss bets to judge
RAISE = 1.8          # "raised the stake" = at least 1.8x the previous
RATE_FLAG = 0.8      # raised after ~all losses, not just sometimes


def detect(acc: AccountState) -> Signal | None:
    bets = sorted(acc.bets, key=lambda b: b.ts)
    after_loss = 0
    chased = 0
    for prev, cur in zip(bets, bets[1:]):
        if not prev.won:
            after_loss += 1
            if cur.stake_cents >= prev.stake_cents * RAISE:
                chased += 1
    if after_loss < MIN_AFTER_LOSS:
        return None
    rate = chased / after_loss
    if rate < RATE_FLAG:
        return None
    score = min(80.0, 45 + (rate - RATE_FLAG) * 150)
    return Signal(
        "responsible", "player_harm", score,
        f"Possible problem gambling: raised the stake right after a loss on {chased} of {after_loss} "
        f"post-loss bets ({rate * 100:.0f}%), a classic loss-chasing pattern.",
    )
