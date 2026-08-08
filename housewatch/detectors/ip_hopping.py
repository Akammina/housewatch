"""IP hopping / proxy rotation.

A normal player connects from one or two places (home, phone). An account that
bets from many different IP addresses is usually one of three things: someone
rotating through proxies/VPNs to look like different people, a shared account, or
part of an operation spread across machines. Any of those is worth a look.
"""
from __future__ import annotations

from ..models import Signal
from ..store import AccountState

MANY_IPS = 5   # a handful of IPs is normal; this many is not


def detect(acc: AccountState) -> Signal | None:
    if acc.n_bets < 20 or len(acc.ips) < MANY_IPS:
        return None
    score = min(92.0, 55 + len(acc.ips) * 4)
    return Signal(
        "ip_hopping", "fraud", score,
        f"Account bet from {len(acc.ips)} different IP addresses. Heavy IP switching points to "
        f"proxy/VPN rotation or shared credentials.",
    )
