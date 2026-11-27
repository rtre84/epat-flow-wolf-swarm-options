"""Tests for the baseline study modules (swarm.study). All pure — no
network, no API key."""
import unittest
from datetime import date

from swarm.study.contracts import (
    next_expiry, option_ticker, round_strike, spread_strikes, strike_step)
from swarm.study.flow_rule import classify_days, zscore
from swarm.study.replay import replay_entry, settle_put_spread, day_contracts
from swarm.study.report import bucket_stats, markdown, report


class ContractTests(unittest.TestCase):
    def test_round_strike_grid(self) -> None:
        self.assertEqual(round_strike(99.4, 1.0), 99.0)
        self.assertEqual(round_strike(255.0, 2.5), 255.0)
        self.assertEqual(round_strike(255.0 + 1.2, 2.5), 255.0)
        self.assertEqual(round_strike(738.0, 5.0), 740.0)

    def test_strike_step_conventions(self) -> None:
        self.assertEqual(strike_step("SPY", 624.0), 1.0)   # index ETFs: $1
        self.assertEqual(strike_step("MU", 150.0), 1.0)
        self.assertEqual(strike_step("MU", 300.0), 2.5)
        self.assertEqual(strike_step("MU", 738.0), 5.0)

    def test_next_expiry_is_friday_and_far_enough(self) -> None:
        d = next_expiry(date(2026, 11, 25), 7)  # Wed Nov 25
        self.assertEqual(d.weekday(), 4)
        self.assertGreaterEqual((d - date(2026, 11, 25)).days, 7)
        self.assertEqual(d, date(2026, 12, 4))   # Fri Dec 4

    def test_option_ticker_format(self) -> None:
        self.assertEqual(option_ticker("SPY", date(2026, 12, 4), "C", 600.0),
                         "O:SPY261204C00600000")
        self.assertEqual(option_ticker("MU", date(2026, 12, 4), "P", 577.5),
                         "O:MU261204P00577500")

    def test_bad_right_raises(self) -> None:
        with self.assertRaises(ValueError):
            option_ticker("SPY", date(2026, 12, 4), "X", 600.0)

    def test_spread_strikes_budget_capped_on_etf_grid(self) -> None:
        # SPY $1 grid: $300 cap admits a 2-point spread
        short_k, long_k = spread_strikes(624.0, ticker="SPY")
        self.assertEqual(short_k - long_k, 2.0)

    def test_spread_strikes_min_width_is_one_grid_step(self) -> None:
        # MU at 738: $5 grid -> narrowest listed spread is 5 points, which
        # the $300 budget cannot fund; replay_entry must skip these
        short_k, long_k = spread_strikes(738.0, ticker="MU")
        self.assertEqual(short_k - long_k, 5.0)

    def test_spread_strikes_low_spot_geometric(self) -> None:
        short_k, long_k = spread_strikes(30.0, ticker="MU")
        self.assertLessEqual(short_k - long_k, 2.0)


class FlowRuleTests(unittest.TestCase):
    def test_zscore_excludes_current_day(self) -> None:
        from datetime import timedelta
        base = date(2026, 10, 1)
        activity = {}
        for i in range(21):
            v = 110.0 if i % 2 else 90.0  # varying baseline, mean 100, std ~10.26
            activity[base + timedelta(days=i)] = v
        activity[base + timedelta(days=20)] = 300.0  # spike on the last day
        z = zscore(activity, base + timedelta(days=20))
        self.assertIsNotNone(z)
        self.assertGreater(z, 10.0)

    def test_warmup_returns_none(self) -> None:
        from datetime import timedelta
        base = date(2026, 10, 1)
        activity = {base + timedelta(days=i): 100.0 for i in range(10)}
        self.assertIsNone(zscore(activity, base + timedelta(days=9)))

    def test_classify_buckets(self) -> None:
        from datetime import timedelta
        base = date(2026, 10, 1)
        activity = {}
        for i in range(25):
            activity[base + timedelta(days=i)] = 110.0 if i % 2 else 90.0
        activity[base + timedelta(days=22)] = 400.0  # flow day
        buckets = classify_days(activity, z_thresh=2.0)
        self.assertIn(base + timedelta(days=22), buckets["flow"])
        self.assertNotIn(base + timedelta(days=23), buckets["flow"])


class ReplayTests(unittest.TestCase):
    def test_settle_spread(self) -> None:
        # short 580 / long 578, credit 1.2, expires worthless above 580
        pnl, payoff = settle_put_spread(1.2, 580.0, 578.0, 601.0)
        self.assertEqual(pnl, 1.2)
        self.assertEqual(payoff, 0.0)
        # pinned below both strikes: full loss
        pnl, payoff = settle_put_spread(1.2, 580.0, 578.0, 500.0)
        self.assertAlmostEqual(pnl, 1.2 - 2.0)

    def test_replay_entry_uses_real_closes(self) -> None:
        day = date(2026, 11, 25)
        # SPY's $1 grid admits the 2-pt budget spread: short 599, long 597
        res = replay_entry("SPY", day, spot=624.0,
                           short_close=1.05, long_close=0.35, exit_spot=610.0)
        self.assertIsNotNone(res)
        self.assertEqual(res.day, "2026-11-25")
        self.assertEqual(res.expiry, "2026-12-04")
        self.assertEqual((res.short_k, res.long_k), (599.0, 597.0))
        self.assertAlmostEqual(res.credit, 0.7)
        self.assertGreater(res.r, 0.0)  # expired worthless above the strikes

    def test_high_priced_stock_grid_cannot_fund_cap(self) -> None:
        # MU at 738: $5 grid -> min spread risks (5 - credit)*100 > $300
        res = replay_entry("MU", date(2026, 11, 25), 738.0,
                           short_close=2.0, long_close=0.8, exit_spot=710.0)
        self.assertIsNone(res)  # cannot fund one contract inside the budget

    def test_missing_quotes_skip(self) -> None:
        res = replay_entry("MU", date(2026, 11, 25), 601.25,
                           short_close=None, long_close=0.35, exit_spot=610.0)
        self.assertIsNone(res)

    def test_degenerate_credit_skips(self) -> None:
        res = replay_entry("MU", date(2026, 11, 25), 601.25,
                           short_close=0.01, long_close=0.005, exit_spot=610.0)
        self.assertIsNone(res)  # credit 0.005 below the width-scaled floor

    def test_day_contracts_shape(self) -> None:
        reqs = day_contracts("SPY", date(2026, 11, 25), 624.0)
        labels = [r[0] for r in reqs]
        self.assertEqual(labels, ["atm_call", "atm_put", "short_leg", "long_leg"])
        for _, opra in reqs:
            self.assertTrue(opra.startswith("O:SPY"))


class ReportTests(unittest.TestCase):
    def _res(self, r: float, credit: float = 1.0) -> object:
        from swarm.study.replay import ReplayResult
        return ReplayResult(ticker="T", day="2026-01-01", expiry="2026-01-09",
                            short_k=100.0, long_k=98.0, credit=credit,
                            risk=credit, exit_spot=100.0, pnl=r * credit, r=r)

    def test_bucket_stats(self) -> None:
        s = bucket_stats([self._res(1.0), self._res(-1.0), self._res(0.5)])
        self.assertEqual(s["n"], 3)
        self.assertAlmostEqual(s["win_rate"], 2 / 3, places=3)
        self.assertAlmostEqual(s["mean_r"], 0.167, places=2)

    def test_empty_bucket(self) -> None:
        s = bucket_stats([])
        self.assertEqual(s["n"], 0)
        self.assertIsNone(s["win_rate"])

    def test_report_and_markdown_edge(self) -> None:
        payload = report([self._res(0.5)], [self._res(-0.5)], 2.0,
                         ["SPY"], date(2026, 1, 1), date(2026, 6, 1))
        self.assertEqual(payload["edge"], 1.0)
        self.assertIn("flow days", markdown(payload))
        self.assertIn("ordinary days", markdown(payload))


if __name__ == "__main__":
    unittest.main()
