"""Tests for the rejection log (swarm.rejections). Import-light: never import
swarm.crew here (it spawns the UW MCP server at import)."""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

from swarm.backtest.gate import CloseSeries
from swarm.rejections import (
    build_rejection,
    has_pending_outcomes,
    load_rejections,
    parse_dossier,
    parse_skeptic,
    record_rejections,
    save_merged,
    update_outcomes,
)

DOSIER_BLOCK = """DOSSIER QQQ
- dark_pool: no — largest block was below-bid distribution
- insider: neutral
- gex_max_pain: 680 flip, call wall at 680
- iv_rank: 41
- events_next_7d: none
- VERDICT: NO-TRADE
- SCORE: 3
- REASONING: The $21M call sweep was stale, printed at 697 vs 656 spot,
  and dealer call walls sit on spot. No accumulation confirmation anywhere.
"""

SKEPTIC_KILL = """SKEPTIC QQQ
- flows_sane: no — print predates the move by two sessions
- iv_crush_risk: moderate
- dealer_conflict: fighting
- stale_or_chase: stale
- OVERRIDES: kill
- REASONING: Stale tape, hedged flow, and a 680 wall directly overhead.
"""

SKEPTIC_KEEP = SKEPTIC_KILL.replace("OVERRIDES: kill", "OVERRIDES: keep")


class ParseTests(unittest.TestCase):
    def test_parse_dossier_mandated_block(self) -> None:
        score, verdict, reason = parse_dossier(DOSIER_BLOCK)
        self.assertEqual(score, 3.0)
        self.assertEqual(verdict, "NO-TRADE")
        self.assertIn("stale", reason.lower())

    def test_parse_dossier_garbage_is_none(self) -> None:
        self.assertEqual(parse_dossier("model output garbage"),
                         (None, None, ""))

    def test_parse_skeptic_actions(self) -> None:
        self.assertEqual(parse_skeptic(SKEPTIC_KILL)[0], "kill")
        self.assertEqual(parse_skeptic(SKEPTIC_KEEP)[0], "keep")
        self.assertIsNone(parse_skeptic("no block")[0])


class BuildRejectionTests(unittest.TestCase):
    def test_dossier_floor_kills_first(self) -> None:
        # NO-TRADE verdict / score < 6 kills at the dossier even if the
        # skeptic also kills: first fatal stage in pipeline order
        rec = build_rejection(date(2026, 11, 25), 2, "QQQ", DOSIER_BLOCK, SKEPTIC_KILL)
        self.assertEqual(rec["killed_by"], "dossier_floor")
        self.assertEqual(rec["rejection_id"], "2026-11-25_QQQ")
        self.assertIsNone(rec["outcome"])

    def test_skeptic_kill_of_above_floor_dossier(self) -> None:
        dossier = DOSIER_BLOCK.replace("VERDICT: NO-TRADE", "VERDICT: BULLISH") \
                              .replace("SCORE: 3", "SCORE: 7.5")
        rec = build_rejection(date(2026, 11, 25), 1, "MU", dossier, SKEPTIC_KILL)
        self.assertEqual(rec["killed_by"], "skeptic_kill")
        self.assertEqual(rec["dossier_score"], 7.5)

    def test_chair_kill_of_surviving_package(self) -> None:
        dossier = DOSIER_BLOCK.replace("VERDICT: NO-TRADE", "VERDICT: BEARISH") \
                              .replace("SCORE: 3", "SCORE: 6.5")
        rec = build_rejection(date(2026, 11, 25), 3, "SPY", dossier, SKEPTIC_KEEP)
        self.assertEqual(rec["killed_by"], "chair")


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "rejections.json"

    def test_record_and_accumulate(self) -> None:
        day = date(2026, 11, 25)
        record_rejections(day, [("QQQ", DOSIER_BLOCK, SKEPTIC_KILL)],
                          survivor_tickers=set(), path=self.path)
        # second scan: MU rejected, QQQ survived (already a spec, not re-recorded)
        record_rejections(day, [("QQQ", DOSIER_BLOCK, SKEPTIC_KILL),
                                ("MU", DOSIER_BLOCK, SKEPTIC_KILL)],
                          survivor_tickers={"QQQ"}, path=self.path)
        ids = [r["rejection_id"] for r in load_rejections(self.path)]
        self.assertEqual(ids, ["2026-11-25_QQQ", "2026-11-25_MU"])

    def test_upsert_same_id_replaces(self) -> None:
        save_merged([{"rejection_id": "2026-11-25_QQQ", "killed_by": "dossier_floor",
                      "date": "2026-11-25", "ticker": "QQQ", "rank": 1, "outcome": None}],
                    self.path)
        save_merged([{"rejection_id": "2026-11-25_QQQ", "killed_by": "skeptic_kill",
                      "date": "2026-11-25", "ticker": "QQQ", "rank": 1, "outcome": None}],
                    self.path)
        recs = load_rejections(self.path)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["killed_by"], "skeptic_kill")


class OutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "rejections.json"
        self.uw = MagicMock()

    @staticmethod
    def _series(spot: float = 100.0, n: int = 40, start=date(2026, 10, 1)) -> CloseSeries:
        closes, dates = [], []
        p = spot
        d = start
        for i in range(n):
            p *= 1.01  # +1% per bar
            closes.append(round(p, 2))
            dates.append(d)
            d += timedelta(days=1)  # calendar gaps don't matter; bars count
        return CloseSeries(dates, closes)

    def _patch_series(self, series: CloseSeries) -> None:
        patcher = mock.patch.object(CloseSeries, "from_uw", classmethod(
            lambda cls, uw, tk: series))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_outcome_computed_with_enough_forward_bars(self) -> None:
        series = self._series()
        self._patch_series(series)
        rejection_date = series.dates[10].isoformat()
        save_merged([{"rejection_id": f"{rejection_date}_QQQ", "date": rejection_date,
                      "ticker": "QQQ", "rank": 1, "killed_by": "dossier_floor",
                      "outcome": None}], self.path)
        n = update_outcomes(self.uw, self.path)
        self.assertEqual(n, 1)
        out = load_rejections(self.path)[0]["outcome"]
        self.assertAlmostEqual(out["fwd_return_7d"], 0.07, places=2)

    def test_outcome_pending_when_history_too_short(self) -> None:
        series = self._series(n=12)
        self._patch_series(series)
        rejection_date = series.dates[10].isoformat()
        save_merged([{"rejection_id": f"{rejection_date}_QQQ", "date": rejection_date,
                      "ticker": "QQQ", "rank": 1, "killed_by": "dossier_floor",
                      "outcome": None}], self.path)
        self.assertEqual(update_outcomes(self.uw, self.path), 0)
        self.assertTrue(has_pending_outcomes(self.path))
        self.assertIsNone(load_rejections(self.path)[0]["outcome"])

    def test_outcome_skipped_when_date_not_in_series(self) -> None:
        series = self._series(start=date(2026, 11, 1))
        self._patch_series(series)
        save_merged([{"rejection_id": "2026-10-05_QQQ", "date": "2026-10-05",
                      "ticker": "QQQ", "rank": 1, "killed_by": "chair",
                      "outcome": None}], self.path)
        self.assertEqual(update_outcomes(self.uw, self.path), 0)


if __name__ == "__main__":
    unittest.main()
