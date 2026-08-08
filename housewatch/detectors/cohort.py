"""Coordinated-cohort detection (behavioural linkage).

Multi-accounting by device/IP is easy to evade: rotate fingerprints and proxy the
IPs and there's nothing to join on. But a bonus-abuse ring or a farmed exploit is
run by a script, so the accounts *behave* identically even when their fingerprints
don't: the same game, the same exact stake, the same tiny amount of play, in the
same window.

So we link on behaviour instead of hardware. Each "narrow" account (one game, one
stake) gets a signature of (dominant game, modal stake); any signature shared by
enough accounts is a coordinated cohort. Real players are broad (varied games and
stakes), so they don't collect into large identical groups.
"""
from __future__ import annotations

from collections import defaultdict

from ..models import Signal
from ..store import Store

MIN_COHORT = 5   # this many identical narrow accounts is coordination, not coincidence


def detect(store: Store) -> dict[str, Signal]:
    groups: dict[tuple[str, int], list[str]] = defaultdict(list)
    for account, acc in store.accounts.items():
        if acc.is_narrow:
            groups[(acc.dominant_game, acc.modal_stake)].append(account)

    out: dict[str, Signal] = {}
    for (game, stake), members in groups.items():
        if len(members) < MIN_COHORT:
            continue
        score = min(100.0, 45 + len(members) * 6)
        shown = ", ".join(sorted(members)[:6]) + ("…" if len(members) > 6 else "")
        for m in members:
            out[m] = Signal(
                "cohort", "abuse", score,
                f"One of {len(members)} accounts with an identical betting signature "
                f"({game} at {stake / 100:.0f} credits) but different device/IP: coordinated activity, "
                f"a likely ring or farmed exploit. Members: {shown}.",
            )
    return out
