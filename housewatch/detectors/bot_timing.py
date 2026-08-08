"""Bot detection from bet timing.

Humans are irregular: they pause, think, get distracted, so the gaps between their
bets vary a lot. Bots are metronomes: near-constant intervals and/or inhumanly fast.
We look at the gaps between consecutive bets and flag two things:

  * very low coefficient of variation (gaps are almost all the same length), and
  * a superhuman sustained bet rate (a few hundred ms between bets, on average).
"""
from __future__ import annotations

from ..models import Signal
from ..store import AccountState

MIN_BETS = 30
CV_FLAG = 0.15        # gaps within ~15% of each other -> machine-like
FAST_GAP_S = 0.4      # under 400ms average between bets, sustained -> not a human


def detect(acc: AccountState) -> Signal | None:
    if acc.n_bets < MIN_BETS or acc.gap_n < MIN_BETS - 1:
        return None
    cv = acc.gap_cv
    mean_gap = acc.gap_mean
    if cv is None or mean_gap <= 0:
        return None
    reasons: list[str] = []
    score = 0.0
    if cv < CV_FLAG:
        score = max(score, 85)
        reasons.append(f"inter-bet timing is machine-regular (variation {cv:.2f})")
    if mean_gap < FAST_GAP_S:
        score = max(score, 80)
        reasons.append(f"superhuman bet rate ({mean_gap * 1000:.0f}ms between bets)")
    if not reasons:
        return None
    return Signal(
        "bot_timing", "bot", score,
        f"Automated play across {acc.n_bets} bets: " + "; ".join(reasons) + ".",
    )
