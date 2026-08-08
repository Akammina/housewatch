"""Per-game payout statistics: the mean return (RTP) and the standard deviation of
the return per unit staked. These come from the FairHouse Monte-Carlo lab, which
measured them over millions of simulated rounds.

The win-rate detector uses these as the "honest player" baseline: given how many
bets an account has placed, how far is their realised return from what the game's
own math says is normal?
"""

# game -> (mean return, std of return) per unit staked
GAME_STATS: dict[str, tuple[float, float]] = {
    "dice": (0.99, 0.99),
    "coinflip": (0.99, 0.99),
    "limbo": (0.99, 1.00),
    "crash": (0.99, 1.00),
    "mines": (0.99, 0.70),
    "tower": (0.99, 1.52),
    "plinko": (0.9734, 0.47),
    "roulette": (0.9730, 1.00),
    "wheel": (0.9750, 1.05),
    "keno": (0.6178, 1.88),
    "slots": (0.9722, 6.52),
}

# fallback for a game we don't have numbers for
DEFAULT_STATS = (0.97, 1.5)


def stats_for(game: str) -> tuple[float, float]:
    return GAME_STATS.get(game, DEFAULT_STATS)
