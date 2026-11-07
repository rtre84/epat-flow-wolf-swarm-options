"""Tests for the learning loop (swarm.learn.chair_calibration)."""
import json
import tempfile
import unittest
from pathlib import Path

from swarm.learn import CLOSED_MIN, chair_calibration


class TestChairCalibration(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def summary(self, **overrides: object) -> Path:
        base = {"tracked": 20, "open": 2, "closed": 20, "realized_pnl_usd": 100.0,
                "open_committed_risk_usd": 75.0, "win_rate": 0.42, "mean_r": 0.09,
                "records": []}
        base.update(overrides)
        path = self.dir / "summary.json"
        path.write_text(json.dumps(base))
        return path

    def test_missing_file_is_no_calibration(self) -> None:
        self.assertEqual(chair_calibration(self.dir / "absent.json"), "")

    def test_too_few_closed_trades_is_no_calibration(self) -> None:
        self.assertEqual(chair_calibration(self.summary(closed=CLOSED_MIN - 1)), "")

    def test_null_metrics_are_no_calibration(self) -> None:
        self.assertEqual(chair_calibration(self.summary(closed=3, win_rate=None, mean_r=None)), "")

    def test_malformed_summary_is_no_calibration(self) -> None:
        path = self.dir / "summary.json"
        path.write_text("not json")
        self.assertEqual(chair_calibration(path), "")

    def test_weak_book_raises_confidence_floor(self) -> None:
        cal = chair_calibration(self.summary(win_rate=0.20, mean_r=-0.11))
        self.assertIn("8/10", cal)

    def test_bad_mean_r_alone_raises_floor(self) -> None:
        cal = chair_calibration(self.summary(win_rate=0.60, mean_r=-0.20))
        self.assertIn("8/10", cal)

    def test_healthy_book_keeps_std_floor(self) -> None:
        cal = chair_calibration(self.summary(win_rate=0.60, mean_r=0.18))
        self.assertIn("6/10", cal)
        self.assertNotIn("8/10", cal)

    def test_middle_book_keeps_std_floor(self) -> None:
        cal = chair_calibration(self.summary(win_rate=0.42, mean_r=0.09))
        self.assertIn("6/10", cal)
        self.assertNotIn("8/10", cal)

    def test_floor_boundaries_are_not_enforcement(self) -> None:
        cal = chair_calibration(self.summary(win_rate=0.30, mean_r=0.05))
        self.assertIn("6/10", cal)
        self.assertNotIn("8/10", cal)

    def test_exactly_closed_min_is_calibrated(self) -> None:
        cal = chair_calibration(self.summary(closed=CLOSED_MIN, win_rate=0.20, mean_r=-0.05))
        self.assertIn("8/10", cal)


if __name__ == "__main__":
    unittest.main()
