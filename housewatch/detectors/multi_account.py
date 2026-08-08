"""Multi-accounting / bonus-abuse rings.

One person running many accounts to farm signup bonuses tends to leave the same
fingerprints: the same device and/or IP across all of them. We treat accounts as
nodes and draw an edge between any two that shared a device or IP, then find the
connected components with union-find. A component above a few accounts is a ring.

This is a global detector: it looks at all accounts at once, not one in isolation.
"""
from __future__ import annotations

from ..models import Signal
from ..store import Store

MIN_RING = 3   # 3+ linked accounts looks like a ring, not a coincidence


def _components(store: Store) -> dict[str, list[str]]:
    parent: dict[str, str] = {a: a for a in store.accounts}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # link accounts that share a device or an IP
    for accounts in list(store.device_accounts.values()) + list(store.ip_accounts.values()):
        accs = list(accounts)
        for other in accs[1:]:
            union(accs[0], other)

    groups: dict[str, list[str]] = {}
    for a in store.accounts:
        groups.setdefault(find(a), []).append(a)
    return groups


def detect(store: Store) -> dict[str, Signal]:
    """Return a signal per account that belongs to a ring."""
    out: dict[str, Signal] = {}
    for members in _components(store).values():
        if len(members) < MIN_RING:
            continue
        # what do they share?
        shared = [d for d, accs in store.device_accounts.items() if len(accs) >= 2 and set(accs) & set(members)]
        shared += [ip for ip, accs in store.ip_accounts.items() if len(accs) >= 2 and set(accs) & set(members)]
        score = min(100.0, 45 + len(members) * 8)
        shown = ", ".join(sorted(members)[:6]) + ("…" if len(members) > 6 else "")
        tag = f" (shared {shared[0]})" if shared else ""
        for m in members:
            out[m] = Signal(
                "multi_account", "abuse", score,
                f"Part of a {len(members)}-account cluster sharing a device/IP{tag}, "
                f"a likely bonus-abuse ring. Linked: {shown}.",
            )
    return out
