"""Shared types: a Signal is one thing a detector found; a RiskProfile is an
account's combined score; an Alert is a scored event worth surfacing on the feed.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Signal:
    detector: str   # win_rate | bot_timing | multi_account | responsible
    category: str   # fraud | bot | abuse | player_harm
    score: float    # 0-100 contribution
    reason: str     # plain-English explanation


def level_for(score: float) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


@dataclass
class RiskProfile:
    account: str
    score: float
    signals: list[Signal] = field(default_factory=list)

    @property
    def level(self) -> str:
        return level_for(self.score)

    def to_json(self) -> dict:
        return {
            "account": self.account,
            "score": round(self.score, 1),
            "level": self.level,
            "categories": sorted({s.category for s in self.signals}),
            "reasons": [{"detector": s.detector, "category": s.category, "reason": s.reason} for s in self.signals],
        }
