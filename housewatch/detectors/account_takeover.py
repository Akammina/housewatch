"""Account takeover (ATO).

The classic signature of a hijacked account: it builds a normal history from one
device, then a *different* device suddenly logs in and starts betting far larger
than the account ever did. That combination (new device + a big stake jump on an
established account) is what we flag. A person adding a second device rarely also
multiplies their stake several-fold at the same moment.
"""
from __future__ import annotations

import statistics
from collections import Counter

from ..models import Signal
from ..store import AccountState

ESTABLISHED = 40    # this many bets on the original device = "established"
STAKE_JUMP = 4.0    # the new device bets at least this many times bigger
MIN_HIJACK = 3      # a few such bets, not a single fat-finger


def detect(acc: AccountState) -> Signal | None:
    if len(acc.devices) < 2 or acc.n_bets < ESTABLISHED + MIN_HIJACK:
        return None
    bets = sorted(acc.bets, key=lambda b: b.ts)
    primary = Counter(b.device for b in bets if b.device).most_common(1)[0][0]
    primary_bets = [b for b in bets if b.device == primary]
    if len(primary_bets) < ESTABLISHED:
        return None
    base = statistics.median(b.stake_cents for b in primary_bets)
    established_at = primary_bets[ESTABLISHED - 1].ts
    hijack = [b for b in bets
              if b.device and b.device != primary and b.ts >= established_at and b.stake_cents >= base * STAKE_JUMP]
    if len(hijack) < MIN_HIJACK:
        return None
    factor = hijack[0].stake_cents / base if base else 0
    return Signal(
        "account_takeover", "fraud", 82,
        f"Account was established on one device ({len(primary_bets)} bets around {base / 100:.0f} credits), "
        f"then a new device began betting about {factor:.0f}x larger. Possible account takeover.",
    )
