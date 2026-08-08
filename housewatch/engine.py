"""The engine ties it together: on every ingested bet it updates the account,
runs the detectors, combines their signals into a 0-100 risk score, and decides
whether the account crossed into "alert" territory.

Scoring is deliberately simple and explainable (analysts need to trust it): the
strongest signal dominates, and extra signals add a fraction on top. No black box.
"""
from __future__ import annotations

import time

from .detectors import bot_timing, multi_account, responsible, win_rate
from .events import Bet
from .models import RiskProfile, Signal, level_for
from .store import Store

ALERT_THRESHOLD = 60.0   # "high" and above raises an alert


def combine(signals: list[Signal]) -> float:
    if not signals:
        return 0.0
    scores = sorted((s.score for s in signals), reverse=True)
    return min(100.0, scores[0] + sum(scores[1:]) * 0.4)


class Engine:
    def __init__(self) -> None:
        self.store = Store()
        self.profiles: dict[str, RiskProfile] = {}
        self.alerts: list[dict] = []            # recent alerts (bounded)
        self.multi_signals: dict[str, Signal] = {}
        self._prev_detectors: dict[str, set[str]] = {}

    def ingest(self, bet: Bet) -> list[dict]:
        self.store.add_bet(bet)
        # linkage is global; refresh it, then rescore the bettor and any ring members
        self.multi_signals = multi_account.detect(self.store)
        touched = {bet.account} | set(self.multi_signals)
        alerts = [a for a in (self._rescore(acc) for acc in touched) if a]
        return alerts

    def _rescore(self, account: str) -> dict | None:
        acc = self.store.accounts[account]
        signals: list[Signal] = []
        for detect in (win_rate.detect, bot_timing.detect, responsible.detect):
            s = detect(acc)
            if s:
                signals.append(s)
        if account in self.multi_signals:
            signals.append(self.multi_signals[account])

        score = combine(signals)
        prev = self.profiles.get(account)
        self.profiles[account] = RiskProfile(account, score, signals)

        detectors = {s.detector for s in signals}
        prev_detectors = self._prev_detectors.get(account, set())
        self._prev_detectors[account] = detectors
        # alert when flagged and something is new: first flag, a new detector fired,
        # or the severity level went up
        escalated = prev is None or (detectors - prev_detectors) or level_for(score) != (prev.level if prev else "low")
        if score >= ALERT_THRESHOLD and escalated:
            top = max(signals, key=lambda s: s.score)
            alert = {
                "ts": time.time(),
                "account": account,
                "score": round(score, 1),
                "level": level_for(score),
                "category": top.category,
                "reason": top.reason,
                "detectors": sorted(detectors),
            }
            self.alerts.append(alert)
            del self.alerts[:-200]  # keep the last 200
            return alert
        return None

    def flagged(self, min_score: float = 40.0) -> list[RiskProfile]:
        rows = [p for p in self.profiles.values() if p.score >= min_score]
        rows.sort(key=lambda p: p.score, reverse=True)
        return rows

    def summary(self) -> dict:
        counts = {"critical": 0, "high": 0, "medium": 0}
        for p in self.profiles.values():
            if p.level in counts:
                counts[p.level] += 1
        return {
            "accounts": len(self.store.accounts),
            "flagged": len(self.flagged()),
            **counts,
        }
