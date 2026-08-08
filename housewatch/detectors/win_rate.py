"""Statistically-impossible win rate.

The signature detector. Because the Monte-Carlo lab measured every game's mean
return (RTP) and the standard deviation of that return, we know exactly how an
honest player's results should be distributed. Over N independent bets the total
return has:

    expected = sum( stake_i * rtp(game_i) )
    variance = sum( (stake_i * return_std(game_i))^2 )     # bets are independent

so we can z-score an account's realised return against that. A player sitting
6 sigma above expected over thousands of bets isn't lucky, they're exploiting a
bug or a broken RNG. We only flag high outliers; unlucky (low) is just unlucky.
"""
from __future__ import annotations

import math

from ..models import Signal
from ..store import AccountState

MIN_BETS = 150   # need a meaningful sample before the z-score means anything
Z_FLAG = 5.0     # ~1 in 3.5 million under honest play


def detect(acc: AccountState) -> Signal | None:
    if acc.n_bets < MIN_BETS or acc.var_return <= 0:
        return None
    z = (acc.returned_total - acc.exp_return) / math.sqrt(acc.var_return)
    if z < Z_FLAG:
        return None
    realised_rtp = acc.returned_total / acc.staked_total if acc.staked_total else 0
    score = min(100.0, 60 + (z - Z_FLAG) * 8)
    return Signal(
        "win_rate", "fraud", score,
        f"Realised RTP {realised_rtp * 100:.0f}% over {acc.n_bets} bets is {z:.1f} sigma above the "
        f"game's expected return. Statistically impossible by luck: likely a bug exploit or tampered RNG.",
    )
