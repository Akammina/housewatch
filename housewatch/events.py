"""Event schema. FairHouse (or the attack simulator) posts these to /ingest.

For the MVP we care about bet events. Each one carries who placed it, from what
device/IP, on which game, and the stake/payout, so the detectors can reason about
win rates, timing, and account linkage.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Bet:
    account: str
    game: str
    stake_cents: int
    payout_cents: int
    ts: float          # unix seconds
    device: str = ""   # device fingerprint
    ip: str = ""

    @property
    def won(self) -> bool:
        return self.payout_cents > 0

    @property
    def multiplier(self) -> float:
        return self.payout_cents / self.stake_cents if self.stake_cents else 0.0

    @staticmethod
    def from_json(d: dict) -> "Bet":
        return Bet(
            account=str(d["account"]),
            game=str(d.get("game", "unknown")),
            stake_cents=int(d["stake_cents"]),
            payout_cents=int(d.get("payout_cents", 0)),
            ts=float(d["ts"]),
            device=str(d.get("device", "")),
            ip=str(d.get("ip", "")),
        )
