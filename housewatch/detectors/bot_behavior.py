"""Bot detection beyond timing.

A smart bot randomises its inter-bet gaps to beat the timing detector, but it still
gives itself away in two ways a human doesn't:

  * endurance: thousands of bets with no real break. People stop to eat, sleep,
    get distracted. A bot just keeps going.
  * a machine-uniform stake: the exact same bet size, thousands of times.

Neither of these fires on a human grinder (who takes breaks and varies the stake),
so they add coverage without adding false positives.
"""
from __future__ import annotations

from ..models import Signal
from ..store import AccountState

ENDURANCE_BETS = 1200   # this many bets...
ENDURANCE_MAX_GAP = 300  # ...with no pause longer than 5 minutes
UNIFORM_BETS = 800
UNIFORM_SHARE = 0.98


def detect(acc: AccountState) -> Signal | None:
    reasons: list[str] = []
    score = 0.0
    if acc.n_bets >= ENDURANCE_BETS and acc.gap_n > 0 and acc.max_gap < ENDURANCE_MAX_GAP:
        score = max(score, 88)
        reasons.append(f"{acc.n_bets} bets with no break longer than {acc.max_gap:.0f}s (people take breaks)")
    if acc.n_bets >= UNIFORM_BETS and acc.top_stake_share >= UNIFORM_SHARE:
        score = max(score, 80)
        reasons.append(f"the exact same stake on {acc.top_stake_share * 100:.0f}% of {acc.n_bets} bets")
    if not reasons:
        return None
    return Signal("bot_behavior", "bot", score, "Automated play: " + "; ".join(reasons) + ".")
