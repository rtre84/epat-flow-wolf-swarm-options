"""Learning loop: derive chair-prompt calibration from paper-P&L facts.

Reads data/pnl/summary.json (written by swarm.execute.tracker) and returns a
deterministic calibration directive for the chair prompt — or "" when there is
not enough closed history to judge. No LLM, no network.
"""
from __future__ import annotations

import json
from pathlib import Path

SUMMARY_PATH = Path("data/pnl/summary.json")

WIN_RATE_FLOOR = 0.30
MEAN_R_FLOOR = 0.05
WIN_RATE_HEALTHY = 0.50
MEAN_R_HEALTHY = 0.15
CLOSED_MIN = 10


def _directive(closed: int, win_rate: float, mean_r: float) -> str:
    stats = f"{closed} closed paper trades, win_rate={win_rate:.2f}, mean_R={mean_r:+.2f}"
    if win_rate < WIN_RATE_FLOOR or mean_r < MEAN_R_FLOOR:
        return (f"PAPER-BOOK CALIBRATION: {stats}. The book is underperforming "
                f"(floor: win_rate {WIN_RATE_FLOOR:.2f}, mean_R {MEAN_R_FLOOR:+.2f}). "
                "Raise your minimum confidence to 8/10 for every spec you emit. "
                "Do not loosen exits or quotas; be strictly more selective.")
    if win_rate >= WIN_RATE_HEALTHY and mean_r >= MEAN_R_HEALTHY:
        return (f"PAPER-BOOK CALIBRATION: {stats}. The book is healthy. "
                "Keep the standard 6/10 confidence floor and your normal quotas.")
    return f"PAPER-BOOK CALIBRATION: {stats}. Keep the standard 6/10 confidence floor."


def chair_calibration(summary_path: Path | None = None) -> str:
    """Return a calibration directive for the chair prompt, or "" if the
    summary is missing, malformed, or has too few closed trades."""
    path = Path(summary_path) if summary_path is not None else SUMMARY_PATH
    try:
        summary = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(summary, dict):
        return ""
    closed, win_rate, mean_r = summary.get("closed"), summary.get("win_rate"), summary.get("mean_r")
    if not isinstance(closed, int) or closed < CLOSED_MIN:
        return ""
    if not isinstance(win_rate, (int, float)) or not isinstance(mean_r, (int, float)):
        return ""
    return _directive(closed, float(win_rate), float(mean_r))
