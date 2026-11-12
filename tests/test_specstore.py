"""Tests for the spec store (swarm.specstore): accumulate, upsert by trade_id.

Import-light by design: never import swarm.crew here (it spawns the UW MCP
server process at import time).
"""
import json
import tempfile
import unittest
from pathlib import Path

from swarm.specstore import load_existing, merge_specs, save_merged


def spec(tid: str, **overrides: object) -> dict:
    base = {"trade_id": tid, "scan_date": tid[:10], "underlying": tid[11:],
            "strategy": "long_call", "expiry": "weekly", "max_risk_usd": 100.0,
            "entry_trigger": "x", "invalidation": "y", "confidence": 7.0,
            "signals": ["s"], "backtest_gate": "pending_backtest"}
    base.update(overrides)
    return base


class TestLoadExisting(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "trade_specs.json"

    def test_missing_file_loads_empty(self) -> None:
        self.assertEqual(load_existing(self.path), [])

    def test_malformed_file_loads_empty(self) -> None:
        self.path.write_text("not json")
        self.assertEqual(load_existing(self.path), [])

    def test_non_list_file_loads_empty(self) -> None:
        self.path.write_text(json.dumps({"specs": []}))
        self.assertEqual(load_existing(self.path), [])

    def test_records_without_trade_id_are_dropped(self) -> None:
        # the chair's empty-day object is not a spec and must not accumulate
        self.path.write_text(json.dumps(
            [{"specs": [], "summary": "empty day"}, spec("2026-11-02_TSLA")]))
        loaded = load_existing(self.path)
        self.assertEqual([s["trade_id"] for s in loaded], ["2026-11-02_TSLA"])


class TestMergeSpecs(unittest.TestCase):
    def test_new_ids_append_and_preserve_existing_order(self) -> None:
        merged = merge_specs([spec("2026-11-02_TSLA"), spec("2026-11-03_SPY")],
                             [spec("2026-11-04_QQQ")])
        self.assertEqual([m["trade_id"] for m in merged],
                         ["2026-11-02_TSLA", "2026-11-03_SPY", "2026-11-04_QQQ"])

    def test_same_id_replaces_with_newer_record(self) -> None:
        merged = merge_specs([spec("2026-11-02_TSLA", backtest_gate="pending_backtest")],
                             [spec("2026-11-02_TSLA", backtest_gate="approved")])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["backtest_gate"], "approved")

    def test_empty_new_keeps_everything(self) -> None:
        existing = [spec("2026-11-02_TSLA")]
        self.assertEqual(merge_specs(existing, []), existing)


class TestSaveMerged(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "nested" / "trade_specs.json"

    def test_accumulates_across_saves(self) -> None:
        save_merged([spec("2026-11-02_TSLA")], self.path)
        save_merged([spec("2026-11-03_SPY")], self.path)
        self.assertEqual([s["trade_id"] for s in load_existing(self.path)],
                         ["2026-11-02_TSLA", "2026-11-03_SPY"])

    def test_upserts_same_id_in_place(self) -> None:
        save_merged([spec("2026-11-02_TSLA", backtest_gate="pending_backtest")], self.path)
        merged = save_merged([spec("2026-11-02_TSLA", backtest_gate="rejected")], self.path)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["backtest_gate"], "rejected")

    def test_empty_scan_never_discards_history(self) -> None:
        save_merged([spec("2026-11-02_TSLA")], self.path)
        merged = save_merged([], self.path)
        self.assertEqual([s["trade_id"] for s in merged], ["2026-11-02_TSLA"])

    def test_repair_drops_stale_empty_day_record(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([{"specs": [], "summary": "empty day"}]))
        merged = save_merged([spec("2026-11-02_TSLA")], self.path)
        self.assertEqual([s["trade_id"] for s in merged], ["2026-11-02_TSLA"])


class TestApprovedImmutability(unittest.TestCase):
    """A gate-approved record is immutable: newer same-trade_id records
    are discarded; pending/rejected records stay replaceable."""

    def test_new_record_cannot_replace_approved(self) -> None:
        merged = merge_specs([spec("2026-11-06_MU", backtest_gate="approved", confidence=6.0)],
                             [spec("2026-11-06_MU", backtest_gate="pending_backtest", confidence=9.0)])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["backtest_gate"], "approved")
        self.assertEqual(merged[0]["confidence"], 6.0)

    def test_approved_challenger_is_also_discarded(self) -> None:
        merged = merge_specs([spec("2026-11-06_MU", backtest_gate="approved", confidence=6.0)],
                             [spec("2026-11-06_MU", backtest_gate="approved", confidence=9.0)])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["confidence"], 6.0)  # first approval wins

    def test_executed_status_is_protected_too(self) -> None:
        merged = merge_specs([spec("2026-11-06_MU", backtest_gate="approved", status="executed")],
                             [spec("2026-11-06_MU", backtest_gate="pending_backtest")])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].get("status"), "executed")

    def test_pending_record_still_replaceable(self) -> None:
        merged = merge_specs([spec("2026-11-02_TSLA", backtest_gate="pending_backtest")],
                             [spec("2026-11-02_TSLA", backtest_gate="rejected")])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["backtest_gate"], "rejected")

    def test_rejected_record_still_replaceable(self) -> None:
        merged = merge_specs([spec("2026-11-02_TSLA", backtest_gate="rejected")],
                             [spec("2026-11-02_TSLA", backtest_gate="approved")])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["backtest_gate"], "approved")

    def test_same_ticker_different_date_appends(self) -> None:
        merged = merge_specs([spec("2026-11-03_MU", backtest_gate="approved")],
                             [spec("2026-11-04_MU")])
        self.assertEqual([m["trade_id"] for m in merged],
                         ["2026-11-03_MU", "2026-11-04_MU"])

    def test_duplicate_ids_within_new_keep_first(self) -> None:
        merged = merge_specs([], [spec("2026-11-06_MU", confidence=6.0),
                                  spec("2026-11-06_MU", confidence=9.0)])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["confidence"], 6.0)


class TestSaveMergedApprovedSticky(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "trade_specs.json"

    def test_save_merged_keeps_approved_over_challenger(self) -> None:
        save_merged([spec("2026-11-06_MU", backtest_gate="approved", confidence=6.0)], self.path)
        merged = save_merged([spec("2026-11-06_MU", backtest_gate="pending_backtest",
                                   confidence=9.0)], self.path)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["backtest_gate"], "approved")
        self.assertEqual(merged[0]["confidence"], 6.0)

    def test_save_merged_appends_new_ids_beside_approved(self) -> None:
        save_merged([spec("2026-11-06_MU", backtest_gate="approved")], self.path)
        merged = save_merged([spec("2026-11-06_MU"), spec("2026-11-07_SPX")], self.path)
        self.assertEqual([s["trade_id"] for s in merged],
                         ["2026-11-06_MU", "2026-11-07_SPX"])


if __name__ == "__main__":
    unittest.main()
