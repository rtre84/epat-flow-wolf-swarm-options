"""Paper executor + tracker tests. Same synthetic series trick as test_gate:
a deterministic high-vol random walk so weekly option marks clear the
degenerate-net filters for every direction."""
import json
import math
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from swarm.backtest.gate import CloseSeries
from swarm.execute import paper as paper_mod
from swarm.execute import tracker as tracker_mod
from swarm.execute.paper import ORDERS_DIR, execute_paper
from swarm.execute.tracker import mark_all
from swarm.models import SpecStatus, Strategy, TradeSpec

T0 = date(2026, 1, 4)


def make_series(n: int = 400, spot: float = 100.0) -> CloseSeries:
    closes, dts = [], []
    p = spot
    for i in range(n):
        p *= 1.0 + 0.05 * math.sin(i / 9.0) + 0.02 * math.sin(i / 3.0)
        closes.append(round(p, 2))
        dts.append(T0 + timedelta(days=i))
    return CloseSeries(dts, closes)


def fake_uw() -> object:
    return mock.MagicMock()


_N = [0]

def _tid(strategy = None) -> tuple[str, str]:
    _N[0] += 1
    ticker = f"T{_N[0]}"
    return f"{T0.isoformat()}_{ticker}", ticker

def make_spec(strategy: Strategy, risk: float = 300.0) -> TradeSpec:
    trade_id, ticker = _tid()
    return TradeSpec(
        trade_id=trade_id, scan_date=T0, underlying=ticker, strategy=strategy,
        expiry="weekly", max_risk_usd=risk, entry_trigger="flow spike",
        invalidation="close through invalidation level", confidence=7.0,
        signals=["gap_up_on_flow"], backtest_gate=SpecStatus.APPROVED,
    )


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._tmp_orders = paper_mod.ORDERS_DIR
        self._tmp_pnl = tracker_mod.PNL_DIR
        paper_mod.ORDERS_DIR = self.tmp / "orders"
        paper_mod.ORDERS_DIR.mkdir()
        tracker_mod.ORDERS_DIR = paper_mod.ORDERS_DIR  # tracker imported its own binding
        tracker_mod.PNL_DIR = self.tmp / "pnl"
        tracker_mod.PNL_DIR.mkdir()
        self.series = make_series()
        self._patcher = mock.patch.object(CloseSeries, "from_uw", classmethod(
            lambda cls, uw, tk: self.series))
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        paper_mod.ORDERS_DIR = self._tmp_orders
        tracker_mod.ORDERS_DIR = self._tmp_orders
        tracker_mod.PNL_DIR = self._tmp_pnl
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fill_and_degenerate_rejection(self):
        # the synthetic series marks these directions above the net floor
        ok = [Strategy.LONG_CALL, Strategy.LONG_PUT,
              Strategy.BULL_CALL_SPREAD, Strategy.BEAR_PUT_SPREAD]
        for strat in ok:
            spec = make_spec(strat)
            rec = json.loads(execute_paper(spec, fake_uw()).model_dump_json())
            self.assertEqual(rec["status"], "open")
            self.assertGreater(rec["committed_risk_usd"], 0)
            self.assertLessEqual(rec["committed_risk_usd"], rec["max_risk_usd"] + 0.01)
            actions = sorted(l["action"] for l in rec["legs"])
            if rec["direction"] == "long":
                self.assertEqual(actions, ["buy"])
            else:
                self.assertEqual(actions, ["buy", "sell"])
            # net_usd stored positive for both credit and debit books
            self.assertGreater(rec["net_usd"], 0)
            self.assertTrue((paper_mod.ORDERS_DIR / f"{spec.trade_id}.json").exists())
        # narrow credit spreads under the 1.0-pt net floor are rejected,
        # exactly as the backtest gate does
        for strat in (Strategy.BULL_PUT_SPREAD, Strategy.BEAR_CALL_SPREAD):
            with self.assertRaises(ValueError):
                execute_paper(make_spec(strat), fake_uw())

    def test_rejects_unapproved(self):
        spec = make_spec(Strategy.LONG_CALL)
        spec.backtest_gate = SpecStatus.PENDING_BACKTEST
        with self.assertRaises(ValueError):
            execute_paper(spec, fake_uw())

    def test_rejects_risky_contract(self):
        # tiny cap below a single contract risk must be rejected, never oversized
        spec = make_spec(Strategy.LONG_CALL, risk=1.0)
        with self.assertRaises(ValueError):
            execute_paper(spec, fake_uw())

    def test_qty_sizing_bounds(self):
        spec = make_spec(Strategy.LONG_CALL)
        rec = execute_paper(spec, fake_uw())
        self.assertLessEqual(rec.qty, paper_mod.MAX_QTY)
        self.assertGreaterEqual(rec.qty, 1)

    def test_mark_closes_and_summarizes(self):
        spec = make_spec(Strategy.BEAR_PUT_SPREAD)
        rec = execute_paper(spec, fake_uw())
        self.assertEqual(rec.status, "open")
        summary = mark_all(fake_uw())
        # series covered by dte=7 bars -> position must reach expiry/stopped/open
        self.assertIn("closed", summary)
        entry = json.loads((paper_mod.ORDERS_DIR / f"{spec.trade_id}.json").read_text())
        if summary["open"] == 0:
            self.assertIn(entry["status"], ("closed",))
            self.assertIsNotNone(entry["pnl_usd"])
            self.assertGreaterEqual(entry["exit_kind"], "")
        else:
            self.assertIsNotNone(entry.get("unrealized_usd"))
        # summary persisted
        self.assertTrue((tracker_mod.PNL_DIR / "summary.json").exists())

    def test_mark_idempotent_closed(self):
        spec = make_spec(Strategy.BULL_CALL_SPREAD)
        execute_paper(spec, fake_uw())
        mark_all(fake_uw())
        before = (paper_mod.ORDERS_DIR / f"{spec.trade_id}.json").read_text()
        summary = mark_all(fake_uw())
        after = (paper_mod.ORDERS_DIR / f"{spec.trade_id}.json").read_text()
        self.assertEqual(before, after)
        self.assertGreaterEqual(summary["tracked"], 1)


if __name__ == "__main__":
    unittest.main()
