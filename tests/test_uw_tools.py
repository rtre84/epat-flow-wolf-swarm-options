"""Tests for the UW tool wrappers (swarm.tools.uw_tools).

The shared client is lazy (Phase 9), so importing this module spawns no MCP
session; tests patch the module-level client with a MagicMock and assert the
arguments each wrapper forwards to call_tool — point-in-time date params in
particular.
"""
import unittest
from unittest.mock import MagicMock

import swarm.tools.uw_tools as uw_tools


def _resp() -> dict:
    return {"result": {"content": [{"text": "ok"}]}}


class WrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.client.call_tool.return_value = _resp()
        patcher = unittest.mock.patch.object(uw_tools, "_client", self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _called_args(self) -> dict:
        name, args = self.client.call_tool.call_args[0]
        self.assertIsInstance(args, dict)
        return args

    def test_module_import_spawns_no_client(self) -> None:
        # fresh import state must leave the client un-initialized
        import importlib
        saved = uw_tools._client
        try:
            uw_tools._client = None
            importlib.reload(uw_tools)
            self.assertIsNone(uw_tools._client)
        finally:
            uw_tools._client = saved

    def test_flow_alerts_passes_date_window(self) -> None:
        uw_tools.get_flow_alerts.func(
            min_premium="100000", is_sweep=True, limit=50,
            newer_than="2026-11-02", older_than="2026-11-03")
        args = self._called_args()
        self.assertEqual(args["newer_than"], "2026-11-02")
        self.assertEqual(args["older_than"], "2026-11-03")

    def test_flow_alerts_omits_empty_window(self) -> None:
        uw_tools.get_flow_alerts.func()
        args = self._called_args()
        self.assertNotIn("newer_than", args)
        self.assertNotIn("older_than", args)

    def test_dark_pool_passes_date_window(self) -> None:
        uw_tools.get_dark_pool_trades.func(
            ticker_symbol="MU", newer_than="2026-11-02", older_than="2026-11-03")
        args = self._called_args()
        self.assertEqual(args["ticker_symbol"], "MU")
        self.assertEqual(args["newer_than"], "2026-11-02")
        self.assertEqual(args["older_than"], "2026-11-03")

    def test_gex_and_max_pain_pass_as_of_date(self) -> None:
        uw_tools.get_gex_levels.func(ticker="MU", date_param="2026-11-02")
        self.assertEqual(self._called_args()["date"], "2026-11-02")
        uw_tools.get_max_pain.func(ticker="MU", date_param="2026-11-02")
        self.assertEqual(self._called_args()["date"], "2026-11-02")

    def test_gex_and_max_pain_omit_date_when_blank(self) -> None:
        uw_tools.get_gex_levels.func(ticker="MU")
        self.assertNotIn("date", self._called_args())
        uw_tools.get_max_pain.func(ticker="MU")
        self.assertNotIn("date", self._called_args())

    def test_market_tide_passes_date(self) -> None:
        uw_tools.get_market_tide.func(date_param="2026-11-02")
        self.assertEqual(self._called_args()["date"], "2026-11-02")

    def test_congress_passes_as_of_date(self) -> None:
        uw_tools.get_recent_congress_trades.func(
            ticker_symbol="MU", date_param="2026-11-02")
        args = self._called_args()
        self.assertEqual(args["ticker"], "MU")
        self.assertEqual(args["date"], "2026-11-02")

    def test_earnings_windows_from_scan_date(self) -> None:
        uw_tools.get_upcoming_earnings.func(ticker="MU", min_date="2026-11-02")
        args = self._called_args()
        self.assertEqual(args["min_date"], "2026-11-02")
        self.assertEqual(args["max_date"], "2026-11-12")  # +10 days, not today

    def test_earnings_defaults_to_today(self) -> None:
        uw_tools.get_upcoming_earnings.func()
        args = self._called_args()
        self.assertEqual(args["min_date"], uw_tools._today())


if __name__ == "__main__":
    unittest.main()
