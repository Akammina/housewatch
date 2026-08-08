"""Detector + engine tests. Each builds a small scenario and checks the right
accounts get flagged and honest ones don't (no false positives)."""
from housewatch.engine import Engine
from housewatch.events import Bet
from housewatch.store import Store
from housewatch.detectors import (
    account_takeover, bot_behavior, bot_timing, cohort, ip_hopping,
    multi_account, platform, responsible, win_rate,
)


def _acc(store: Store, bets: list[Bet]):
    for b in bets:
        store.add_bet(b)
    return store.accounts[bets[0].account]


def test_win_rate_flags_impossible_returns():
    store = Store()
    # 350 dice bets that always pay 2x -> ~200% RTP, far above the 99% baseline
    acc = _acc(store, [Bet("cheat", "dice", 1000, 2000, ts=i) for i in range(350)])
    sig = win_rate.detect(acc)
    assert sig is not None and sig.category == "fraud"


def test_win_rate_ignores_honest_play():
    store = Store()
    # alternate 1.98x win / 0 loss -> ~99% RTP, exactly expected
    bets = [Bet("honest", "dice", 1000, 1980 if i % 2 else 0, ts=i) for i in range(400)]
    acc = _acc(store, bets)
    assert win_rate.detect(acc) is None


def test_bot_timing_flags_metronome():
    store = Store()
    acc = _acc(store, [Bet("bot", "dice", 1000, 0, ts=i * 0.2) for i in range(60)])  # exact 200ms gaps
    sig = bot_timing.detect(acc)
    assert sig is not None and sig.category == "bot"


def test_bot_timing_ignores_humans():
    store = Store()
    gaps = [0, 3, 9, 2, 15, 4, 22, 1, 8, 30] * 6  # irregular human gaps
    ts, bets = 0.0, []
    for i, g in enumerate(gaps):
        ts += g
        bets.append(Bet("human", "dice", 1000, 0, ts=ts))
    assert bot_timing.detect(_acc(store, bets)) is None


def test_multi_account_flags_ring():
    store = Store()
    for r in range(4):  # 4 accounts, one shared device
        store.add_bet(Bet(f"ring{r}", "dice", 1000, 0, ts=r, device="shared_dev", ip=f"1.1.1.{r}"))
    store.add_bet(Bet("loner", "dice", 1000, 0, ts=9, device="own_dev", ip="9.9.9.9"))
    signals = multi_account.detect(store)
    assert {f"ring{r}" for r in range(4)} <= set(signals)
    assert "loner" not in signals


def test_responsible_flags_chaser_not_random():
    store = Store()
    # chaser: doubles the stake after every loss
    ts, stake, bets = 0.0, 1000, []
    for _ in range(30):
        ts += 5
        bets.append(Bet("chaser", "dice", stake, 0, ts=ts))  # all losses
        stake *= 2
    assert responsible.detect(_acc(store, bets)) is not None

    store2 = Store()
    # random stakes, never a deliberate chase pattern
    stakes = [1000, 2000, 1000, 5000, 1000, 2000, 1000] * 5
    bets2 = [Bet("varied", "dice", s, 0, ts=i * 5) for i, s in enumerate(stakes)]
    assert responsible.detect(_acc(store2, bets2)) is None


def test_platform_monitor_catches_distributed_exploit():
    # a slots exploit spread across 25 accounts: no single account is a big outlier,
    # but the game's overall RTP is wrecked, which the platform monitor sees.
    store = Store()
    for a in range(25):
        for i in range(120):
            store.add_bet(Bet(f"x{a}", "slots", 2000, 6000 if i % 2 else 0, ts=i, device=f"d{a}"))
    # an honest game running alongside, for contrast
    for i in range(2500):
        store.add_bet(Bet(f"h{i % 40}", "dice", 1000, 1980 if i % 2 else 0, ts=i, device="hd"))
    games = {a["game"] for a in platform.detect(store)}
    assert "slots" in games and "dice" not in games


def test_bot_behavior_catches_tireless_and_uniform():
    store = Store()
    # 1500 bets, 2s apart, never a break, one stake -> endurance + uniform
    acc = _acc(store, [Bet("bot", "dice", 1000, 0, ts=i * 2.0) for i in range(1500)])
    assert bot_behavior.detect(acc) is not None


def test_bot_behavior_ignores_human_grinder():
    store = Store()
    ts, bets = 0.0, []
    for i in range(700):
        ts += 300 if i % 50 == 0 else 3       # a real break every 50 bets
        bets.append(Bet("grinder", "dice", (i % 3 + 1) * 1000, 0, ts=ts))  # varied stakes
    assert bot_behavior.detect(_acc(store, bets)) is None


def test_cohort_flags_identical_signature_ring():
    store = Store()
    for r in range(6):                        # 6 accounts, unique device/IP, identical behaviour
        for _ in range(5):
            store.add_bet(Bet(f"c{r}", "dice", 1000, 0, ts=r, device=f"u{r}", ip=f"1.1.1.{r}"))
    flagged = [a for a in cohort.detect(store) if a.startswith("c")]
    assert len(flagged) == 6


def test_cohort_ignores_diverse_players():
    import random as R
    R.seed(1)
    store = Store()
    for u in range(10):
        for _ in range(20):
            store.add_bet(Bet(f"u{u}", R.choice(["dice", "slots", "keno"]), R.choice([1000, 2000, 5000]),
                              0, ts=u, device=f"d{u}", ip=f"2.2.2.{u}"))
    assert cohort.detect(store) == {}


def test_account_takeover_flags_new_device_with_big_stakes():
    store = Store()
    for i in range(60):
        store.add_bet(Bet("v", "dice", 700, 700, ts=1e9 + i * 5, device="A", ip="1.1.1.1"))
    for i in range(6):
        store.add_bet(Bet("v", "dice", 9000, 0, ts=1e9 + 5000 + i * 5, device="B", ip="2.2.2.2"))
    assert account_takeover.detect(store.accounts["v"]) is not None


def test_account_takeover_ignores_second_device_same_stakes():
    store = Store()
    for i in range(60):
        store.add_bet(Bet("v", "dice", 1000, 1000, ts=1e9 + i * 5, device="A", ip="1.1.1.1"))
    for i in range(6):   # second device, but normal stakes -> not a takeover
        store.add_bet(Bet("v", "dice", 1000, 0, ts=1e9 + 5000 + i * 5, device="B", ip="2.2.2.2"))
    assert account_takeover.detect(store.accounts["v"]) is None


def test_ip_hopping_flags_many_ips():
    store = Store()
    for i in range(40):
        store.add_bet(Bet("proxy", "dice", 1000, 0, ts=i, device="d", ip=f"5.5.5.{i}"))
    assert ip_hopping.detect(store.accounts["proxy"]) is not None


def test_ip_hopping_ignores_normal_user():
    store = Store()
    for i in range(60):
        store.add_bet(Bet("u", "dice", 1000, 0, ts=i, device="d", ip="1.1.1.1" if i % 2 else "1.1.1.2"))
    assert ip_hopping.detect(store.accounts["u"]) is None


def test_engine_scores_and_alerts():
    eng = Engine()
    # ring of 3 sharing a device
    for r in range(3):
        for _ in range(3):
            eng.ingest(Bet(f"promo{r}", "dice", 1000, 0, ts=r, device="D", ip="1.1.1.1"))
    ring = eng.profiles["promo0"]
    assert ring.level in ("high", "critical")
    assert any(a["account"].startswith("promo") for a in eng.alerts)
    assert eng.summary()["flagged"] >= 3
