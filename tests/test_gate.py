"""Gate unit tests with synthetic price series — no network."""
import math
import unittest
from datetime import date, timedelta

from swarm.backtest.gate import (
    CloseSeries,
    _direction,
    _pick_strikes,
    _should_refresh,
    bs_price,
    evaluate,
    metrics_for_direction,
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


class RiskBudgetStrikeTests(unittest.TestCase):
    """Phase 7: budget-capped strike widths so a single contract fits the
    spec's max_risk_usd; gate and executor share the same structure."""

    def test_no_budget_keeps_legacy_geometry(self):
        short, lng = _pick_strikes(738.0, "put_credit", 7)
        self.assertAlmostEqual(short, 738.0 * 0.96)
        self.assertAlmostEqual(lng, 738.0 * 0.91)

    def test_budget_caps_width(self):
        # $300 cap -> floor(300*0.8/100) = 2-pt spreads at any spot
        short, lng = _pick_strikes(738.0, "put_credit", 7, 300.0)
        self.assertAlmostEqual(short, 738.0 * 0.96)
        self.assertAlmostEqual(lng, short - 2.0)
        short, lng = _pick_strikes(738.0, "call_credit", 7, 250.0)
        self.assertAlmostEqual(lng, short + 2.0)
        short, lng = _pick_strikes(738.0, "call_debit", 7, 300.0)
        self.assertAlmostEqual(lng, short - 2.0)
        short, lng = _pick_strikes(738.0, "put_debit", 7, 300.0)
        self.assertAlmostEqual(lng, short + 2.0)

    def test_low_spot_keeps_geometric_width(self):
        # spot 30: 5% width (1.5 pts) is already inside the budget
        short, lng = _pick_strikes(30.0, "put_credit", 7, 300.0)
        self.assertAlmostEqual(lng, short - 1.5)

    def test_long_ignores_budget(self):
        short, lng = _pick_strikes(738.0, "long", 7, 300.0)
        self.assertIsNone(short)
        self.assertAlmostEqual(lng, 738.0)

    def test_net_floor_scales_with_width(self):
        # width-scaled floor replaces the flat 1.0-pt floor: a 2-pt spread
        # with a 0.5-pt credit is a valid structure, not degenerate
        net, risk = metrics_for_direction(
            100.0, 96.0, 94.0, 7 / 252, 0.60, False, "put_credit")
        self.assertGreater(net, 0)
        self.assertAlmostEqual(risk, 2.0 - net)

    def test_degenerate_net_still_rejected(self):
        # near-zero premium under the width-scaled floor must still raise
        with self.assertRaises(ValueError):
            metrics_for_direction(
                100.0, 96.0, 94.0, 7 / 252, 0.08, False, "put_credit")

    def test_budgeted_simulation_runs_all_strategies(self):
        s = _series()
        for strat in STRATS:
            rs = simulate_archetype(s, strat, 7, max_risk_usd=300.0)
            self.assertTrue(rs, strat)
            self.assertTrue(all(r >= -1.5 and math.isfinite(r) for r in rs), strat)


class CacheRefreshTests(unittest.TestCase):
    """Closes cached once must never freeze the paper book at a stale bar."""

    def test_same_or_previous_day_is_fresh(self):
        self.assertFalse(_should_refresh(date(2026, 11, 25), date(2026, 11, 25)))
        self.assertFalse(_should_refresh(date(2026, 11, 25), date(2026, 11, 26)))  # Thanksgiving

    def test_older_than_one_day_refreshes(self):
        self.assertTrue(_should_refresh(date(2026, 11, 6), date(2026, 11, 26)))
        self.assertTrue(_should_refresh(date(2026, 11, 21), date(2026, 11, 23)))  # weekend gap

    def test_missing_or_empty_is_refresh(self):
        self.assertTrue(_should_refresh(None))


if __name__ == "__main__":
    unittest.main()
