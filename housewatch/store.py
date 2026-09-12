"""In-memory store of bets and per-account state.

A streaming detection engine keeps hot state in memory so it can score every event
as it arrives. Per account we keep running aggregates (updated once per bet) so the
detectors are O(1) per event instead of rescanning history:

  * staked / returned totals and the expected-return mean+variance (for the
    win-rate z-score), and
  * inter-bet gap mean/variance via Welford's online algorithm (for bot timing).

The full bet list is kept too, for the responsible-gambling sequence check and for
display. A production build would back this with a database.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from .events import Bet
from .games import stats_for


class AccountState:
    def __init__(self, account: str):
        self.account = account
        self.bets: list[Bet] = []
        self.devices: set[str] = set()
        self.ips: set[str] = set()
        self.first_seen: float = 0.0
        self.last_seen: float = 0.0
        # running aggregates for the win-rate z-score
        self.staked_total: int = 0
        self.returned_total: int = 0
        self.exp_return: float = 0.0   # sum of stake * rtp(game)
        self.var_return: float = 0.0   # sum of (stake * return_std(game))^2
        # running inter-bet gap stats (Welford)
        self._prev_ts: float | None = None
        self.gap_n: int = 0
        self.gap_mean: float = 0.0
        self._gap_m2: float = 0.0
        self.max_gap: float = 0.0            # longest pause (a human takes breaks; a bot doesn't)
        self.stake_counts: Counter[int] = Counter()  # stake spread (bots often bet one size)
        self.game_counts: Counter[str] = Counter()

    def observe(self, bet: Bet) -> None:
        if not self.bets:
            self.first_seen = bet.ts
        self.bets.append(bet)
        rtp, std = stats_for(bet.game)
        self.staked_total += bet.stake_cents
        self.returned_total += bet.payout_cents
        self.exp_return += bet.stake_cents * rtp
        self.var_return += (bet.stake_cents * std) ** 2
        if self._prev_ts is not None and bet.ts > self._prev_ts:
            gap = bet.ts - self._prev_ts
            self.gap_n += 1
            delta = gap - self.gap_mean
            self.gap_mean += delta / self.gap_n
            self._gap_m2 += delta * (gap - self.gap_mean)
            if gap > self.max_gap:
                self.max_gap = gap
        self._prev_ts = bet.ts
        self.last_seen = bet.ts
        self.stake_counts[bet.stake_cents] += 1
        self.game_counts[bet.game] += 1
        if bet.device:
            self.devices.add(bet.device)
        if bet.ip:
            self.ips.add(bet.ip)

    @property
    def n_bets(self) -> int:
        return len(self.bets)

    @property
    def gap_cv(self) -> float | None:
        """Coefficient of variation of inter-bet gaps (std / mean)."""
        if self.gap_n < 2 or self.gap_mean <= 0:
            return None
        return math.sqrt(self._gap_m2 / self.gap_n) / self.gap_mean

    @property
    def span(self) -> float:
        return self.last_seen - self.first_seen

    @property
    def top_stake_share(self) -> float:
        """Fraction of bets placed at the single most-used stake (1.0 = one size only)."""
        if not self.stake_counts:
            return 0.0
        return self.stake_counts.most_common(1)[0][1] / self.n_bets

    @property
    def modal_stake(self) -> int:
        return self.stake_counts.most_common(1)[0][0] if self.stake_counts else 0

    @property
    def dominant_game(self) -> str:
        return self.game_counts.most_common(1)[0][0] if self.game_counts else ""

    @property
    def is_narrow(self) -> bool:
        """Plays essentially one game at one stake, the way a coordinated bot does."""
        return self.n_bets >= 3 and self.top_stake_share >= 0.8 and len(self.game_counts) <= 2


class GameStats:
    """Per-game aggregate across ALL players, for the platform-level RTP monitor.
    A cheat spread thin across accounts still shows up here."""
    def __init__(self) -> None:
        self.bets = 0
        self.staked = 0
        self.returned = 0
        self.exp_return = 0.0
        self.var_return = 0.0


class Store:
    def __init__(self) -> None:
        self.accounts: dict[str, AccountState] = {}
        # reverse indexes for linkage: which accounts used a given device / ip
        self.device_accounts: dict[str, set[str]] = defaultdict(set)
        self.ip_accounts: dict[str, set[str]] = defaultdict(set)
        self.games: dict[str, GameStats] = defaultdict(GameStats)

    def add_bet(self, bet: Bet) -> AccountState:
        acc = self.accounts.get(bet.account)
        if acc is None:
            acc = AccountState(bet.account)
            self.accounts[bet.account] = acc
        acc.observe(bet)
        if bet.device:
            self.device_accounts[bet.device].add(bet.account)
        if bet.ip:
            self.ip_accounts[bet.ip].add(bet.account)
        # platform-level game aggregate
        rtp, std = stats_for(bet.game)
        g = self.games[bet.game]
        g.bets += 1
        g.staked += bet.stake_cents
        g.returned += bet.payout_cents
        g.exp_return += bet.stake_cents * rtp
        g.var_return += (bet.stake_cents * std) ** 2
        return acc
