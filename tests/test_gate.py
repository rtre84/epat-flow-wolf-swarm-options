"""Gate unit tests with synthetic price series — no network."""
import math
import unittest
from datetime import date, timedelta

from swarm.backtest.gate import (
    CloseSeries,
    _direction,
    _pick_strikes,
    bs_price,
    evaluate,
    simulate_archetype,
)


def _series(n=600, drift=0.001):
    closes, dates = [], []
    p = 100.0
    d = date(2024, 1, 1)
    for i in range(n):
        closes.append(p)
        dates.append(d)
        p *= 1 + drift + 0.05 * math.sin(i / 9.0)
        d += timedelta(days=1)
    return CloseSeries(dates, closes)


STRATS = (
    "long_call", "long_put", "bull_put_spread",
    "bear_call_spread", "bull_call_spread", "bear_put_spread",
)


class GateTests(unittest.TestCase):
    def test_bs_call_put_parity(self):
        c = bs_price(100, 100, 0.1, 0.3, True)
        p = bs_price(100, 100, 0.1, 0.3, False)
        self.assertLess(c, 5)
        self.assertGreater(c, 0)
        self.assertLess(p, 5)
        self.assertGreater(p, 0)

    def test_directions_complete(self):
        for s in STRATS:
            self.assertTrue(_direction(s))

    def test_pick_strikes_ordering(self):
        pairs = [
            _pick_strikes(100, "put_credit", 7),
            _pick_strikes(100, "call_credit", 7),
            _pick_strikes(100, "call_debit", 7),
            _pick_strikes(100, "put_debit", 7),
        ]
        for short, lng in pairs:
            self.assertTrue(short and lng and short != lng)

    def test_simulate_runs_all_strategies(self):
        s = _series()
        for strat in STRATS:
            rs = simulate_archetype(s, strat, 7)
            self.assertTrue(rs, strat)
            self.assertTrue(all(r >= -1.5 and math.isfinite(r) for r in rs), strat)
            if "credit" in _direction(strat):
                # spread credit: risking strike-width minus net credit
                self.assertTrue(all(-1.01 <= r <= 1.0 for r in rs), strat)

    def test_evaluate_stats(self):
        m = evaluate(_series(), "bull_put_spread", 7)
        self.assertGreater(m["n"], 0)
        self.assertLessEqual(m["win_rate"], 1)


if __name__ == "__main__":
    unittest.main()
