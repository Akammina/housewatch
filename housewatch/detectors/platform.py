"""Platform-level game-integrity monitor (defense in depth).

The per-account win-rate detector can be evaded: keep the edge small, hide it in a
high-variance game, or spread it across many accounts so none looks bad on its own.
But all of those inflate one thing the attacker can't hide, the game's overall RTP
across every player. If a game is paying well above its designed return over a large
sample, something is wrong (a bug, a farmed exploit, or a tampered RNG), no matter
how the winnings are distributed across accounts.

This runs on the per-game aggregate, so it's the same z-score idea applied to the
whole game instead of one account.
"""
from __future__ import annotations

import math

from ..store import Store

MIN_BETS = 2000   # game-level needs a big sample before it means anything
Z_FLAG = 4.0


def detect(store: Store) -> list[dict]:
    out: list[dict] = []
    for game, g in store.games.items():
        if g.bets < MIN_BETS or g.var_return <= 0:
            continue
        z = (g.returned - g.exp_return) / math.sqrt(g.var_return)
        if z < Z_FLAG:
            continue
        rtp = g.returned / g.staked if g.staked else 0
        out.append({
            "game": game,
            "z": z,
            "rtp": rtp,
            "bets": g.bets,
            "score": min(100.0, 65 + (z - Z_FLAG) * 6),
            "reason": (
                f"Game '{game}' is paying {rtp * 100:.1f}% RTP across all players over {g.bets:,} bets, "
                f"{z:.1f} sigma above its designed return. Possible RNG compromise or a widely-farmed exploit."
            ),
        })
    return out
