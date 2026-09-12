"""Full red-team + false-positive harness.

A professional detector is judged on two numbers at once: how many attacks it
catches (recall) and how few honest players it wrongly flags (false positives).
Chasing one without the other is easy and useless. This harness runs a diverse
normal population against a wide set of attack variants and reports both.

Each attack is tagged: `catchable` (we expect a hit) or `fundamental` (evadable
without signals a server doesn't have, e.g. client biometrics or a payment graph).
We grade recall on the catchable ones and treat fundamentals as known limits.

    python -m simulator.redteam
"""
from __future__ import annotations

import random

from housewatch.engine import Engine
from housewatch.events import Bet
from .attack import multiplier

random.seed(11)
GAMES = ["dice", "coinflip", "limbo", "wheel", "roulette", "keno", "slots"]
FLAG = 60.0


def human_gaps(n, mu=1.5, sigma=0.85, break_prob=0.03):
    """Human timing: irregular, and every so often a real break (minutes away)."""
    for _ in range(n):
        yield random.uniform(120, 900) if random.random() < break_prob else random.lognormvariate(mu, sigma)


def feed(eng, account, game_fn, n, gaps, stake_fn, *, device, ip, cheat=1.0, t0=1_700_000_000.0):
    ts = t0
    for g in gaps:
        ts += g
        game = game_fn()
        stake = stake_fn()
        eng.ingest(Bet(account, game, stake, round(stake * multiplier(game, cheat)), ts, device, ip))


# ---- honest population (stress false positives) ----
def normal_population(eng, count=120):
    for u in range(count):
        acc, dev, ip = f"user_{u:03d}", f"dev_{u:03d}", f"77.{u % 250}.{random.randint(1, 250)}.{random.randint(1, 250)}"
        kind = random.choices(["casual", "grinder", "high_roller", "streaky"], [0.5, 0.25, 0.15, 0.10])[0]
        if kind == "casual":
            n = random.randint(30, 120); stakes = [10, 20, 50, 100]
            feed(eng, acc, lambda: random.choice(GAMES), n, human_gaps(n, 1.8, 0.9),
                 lambda: random.choice(stakes) * 100, device=dev, ip=ip)
        elif kind == "grinder":   # high volume, faster, but human breaks + some stake variation
            n = random.randint(300, 650)
            feed(eng, acc, lambda: random.choice(["dice", "limbo", "wheel"]), n, human_gaps(n, 1.0, 0.7, 0.05),
                 lambda: random.choice([50, 50, 100, 200]) * 100, device=dev, ip=ip)
        elif kind == "high_roller":
            n = random.randint(20, 60)
            feed(eng, acc, lambda: random.choice(GAMES), n, human_gaps(n, 2.2, 1.0),
                 lambda: random.choice([500, 1000, 2000]) * 100, device=dev, ip=ip)
        else:                     # streaky: varies stake with mood (not systematic chasing)
            n = random.randint(60, 200)
            feed(eng, acc, lambda: random.choice(GAMES), n, human_gaps(n, 1.6, 0.9),
                 lambda: random.choice([20, 20, 50, 100, 100, 300]) * 100, device=dev, ip=ip)


# ---- attacks ----
def run_attacks(eng):
    results = []   # (name, catchable, account_or_check)

    def acct(name, catchable, account):
        results.append((name, catchable, ("acct", account)))

    def platform_check(name, catchable, game):
        results.append((name, catchable, ("game", game)))

    fixed = lambda v: (lambda: v)
    dice = fixed("dice")

    # cheating
    feed(eng, "cheat_blatant", dice, 700, human_gaps(700), fixed(2000), device="c1", ip="9.0.0.1", cheat=1.30)
    acct("cheat blatant (dice +30%)", True, "cheat_blatant")
    feed(eng, "cheat_moderate", dice, 2600, human_gaps(2600), fixed(2000), device="c2", ip="9.0.0.2", cheat=1.12)
    acct("cheat moderate (dice +12%, high volume)", True, "cheat_moderate")
    feed(eng, "cheat_stealth", dice, 700, human_gaps(700), fixed(2000), device="c3", ip="9.0.0.3", cheat=1.04)
    acct("cheat stealth (dice +4%)", False, "cheat_stealth")
    feed(eng, "cheat_slots1", fixed("slots"), 700, human_gaps(700), fixed(2500), device="c4", ip="9.0.0.4", cheat=1.4)
    acct("cheat single acct on slots (high var)", False, "cheat_slots1")
    for a in range(30):   # uniform signature -> caught by the cohort detector
        feed(eng, f"exp_slots_{a}", fixed("slots"), 150, human_gaps(150), fixed(2000), device=f"es{a}", ip=f"9.1.{a}.5", cheat=1.5)
    acct("distributed slots exploit (30 accts)", True, "exp_slots_0")
    for a in range(20):
        feed(eng, f"exp_dice_{a}", dice, 130, human_gaps(130), fixed(1000), device=f"ed{a}", ip=f"9.2.{a}.5", cheat=1.25)
    acct("distributed dice exploit (20 accts)", True, "exp_dice_0")
    # smarter: vary the stake and game per account so there's no shared signature
    for a in range(15):
        feed(eng, f"exp_smart_{a}", lambda: random.choice(["dice", "limbo"]), 120,
             human_gaps(120), lambda: random.choice([10, 30, 70, 150]) * 100, device=f"sm{a}", ip=f"9.7.{a}.5", cheat=1.25)
    acct("distributed exploit, varied signatures", False, "exp_smart_0")

    # bots
    feed(eng, "bot_metronome", dice, 400, (0.2 + random.uniform(-0.01, 0.01) for _ in range(400)), fixed(5000), device="b1", ip="9.3.0.1")
    acct("bot metronome (200ms)", True, "bot_metronome")
    feed(eng, "bot_fast", dice, 400, (0.12 for _ in range(400)), fixed(5000), device="b2", ip="9.3.0.2")
    acct("bot superfast (120ms)", True, "bot_fast")
    # tireless bot: human-like jitter, but 3000 bets, never a break, one stake
    feed(eng, "bot_tireless", dice, 3000, (random.lognormvariate(0.7, 0.8) for _ in range(3000)), fixed(3000), device="b3", ip="9.3.0.3")
    acct("bot tireless (jitter, no breaks, uniform stake)", True, "bot_tireless")
    # low-and-slow human-mimicking bot (breaks + varied stake + jitter, modest volume)
    feed(eng, "bot_mimic", dice, 300, human_gaps(300), lambda: random.choice([10, 20, 50]) * 100, device="b4", ip="9.3.0.4")
    acct("bot human-mimic (low volume)", False, "bot_mimic")

    # account takeover: built up on one device, then hijacked from another with big stakes
    feed(eng, "victim_ato", dice, 60, human_gaps(60), fixed(700), device="devA", ip="10.10.0.1")
    feed(eng, "victim_ato", dice, 6, human_gaps(6), fixed(9000), device="devB", ip="66.66.0.9", t0=1_700_005_000.0)
    acct("account takeover (new device + big stakes)", True, "victim_ato")

    # IP hopping: one account cycling through many IPs (proxy rotation)
    ts = 1_700_000_000.0
    for i in range(40):
        ts += random.uniform(3, 10)
        eng.ingest(Bet("proxy_user", "dice", 1500, round(1500 * multiplier("dice")), ts, "pdev", f"200.10.{i}.5"))
    acct("IP hopping (proxy rotation)", True, "proxy_user")

    # multi-accounting
    for r in range(6):
        feed(eng, f"ring_dev_{r}", dice, 6, human_gaps(6), fixed(1000), device="RINGDEV", ip=f"9.4.0.{r}")
    acct("ring: shared device", True, "ring_dev_0")
    for r in range(6):
        feed(eng, f"ring_ip_{r}", dice, 6, human_gaps(6), fixed(1000), device=f"rip{r}", ip="9.4.9.9")
    acct("ring: shared IP only", True, "ring_ip_0")
    # rotated fingerprints but identical behaviour (bonus bots): same stake, same game, minimal play, same window
    for r in range(8):
        feed(eng, f"ring_clone_{r}", dice, 5, (random.uniform(2, 6) for _ in range(5)), fixed(1000), device=f"clone{r}", ip=f"9.5.{r}.7", t0=1_700_000_500.0)
    acct("ring: rotated fp, identical behaviour", True, "ring_clone_0")
    # rotated fingerprints AND diverse behaviour
    for r in range(6):
        feed(eng, f"ring_div_{r}", lambda: random.choice(GAMES), random.randint(20, 80), human_gaps(80), lambda: random.choice([10, 50, 200]) * 100, device=f"dv{r}", ip=f"9.6.{r}.7")
    acct("ring: rotated fp, diverse behaviour", False, "ring_div_0")

    return results


def caught(eng, target) -> tuple[bool, str]:
    kind, key = target
    if kind == "game":
        hit = next((a for a in eng.alerts if a["category"] == "integrity" and a["account"] == f"game:{key}"), None)
        return (hit is not None, hit["reason"][:60] if hit else "")
    p = eng.profiles.get(key)
    if p and p.score >= FLAG:
        top = max(p.signals, key=lambda s: s.score)
        return True, f"[{top.detector}] {top.reason[:52]}"
    return False, f"score {(p.score if p else 0):.0f}"


def main():
    eng = Engine()
    normal_population(eng)
    results = run_attacks(eng)

    print("\n=== ATTACK COVERAGE ===")
    rec_hit = rec_tot = 0
    for name, catchable, target in results:
        ok, info = caught(eng, target)
        tag = "catchable " if catchable else "fundamental"
        mark = "CAUGHT" if ok else "MISS  "
        if catchable:
            rec_tot += 1; rec_hit += ok
        note = "" if catchable else ("  (unexpectedly caught)" if ok else "  (known limit)")
        print(f"  [{tag}] {mark}  {name:<44} {info}{note}")

    # false positives on the honest population
    normals = [p for a, p in eng.profiles.items() if a.startswith("user_")]
    fp = [p for p in normals if p.score >= FLAG]

    print("\n=== SCORECARD ===")
    print(f"  recall on catchable attacks : {rec_hit}/{rec_tot}")
    print(f"  normal players              : {len(normals)}")
    print(f"  false positives (>= {FLAG:.0f})     : {len(fp)}   ({100*len(fp)/max(1,len(normals)):.1f}%)")
    for p in fp:
        top = max(p.signals, key=lambda s: s.score) if p.signals else None
        print(f"      FP {p.account} score {p.score:.0f} - {top.reason[:60] if top else ''}")
    print()


if __name__ == "__main__":
    main()
