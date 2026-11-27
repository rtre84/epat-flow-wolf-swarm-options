"""Mechanical flow rule: elevated ATM option activity = a flow day.

The signal uses volume only (open interest is historical-only on tiers
above ours, deliberately avoided). Activity = nearest-expiry ATM call +
put volume; a day is a FLOW day when its activity z-score against the
trailing window clears the threshold. The z-score window excludes the
day being scored (no self-influence).
"""
from __future__ import annotations

from datetime import date

DEFAULT_WINDOW = 20
DEFAULT_Z = 2.0


def zscore(activity: dict[date, float], day: date,
           window: int = DEFAULT_WINDOW) -> float | None:
    """Z-score of `day`'s activity vs the prior `window` trading days.
    None when the trailing window is incomplete or has zero dispersion."""
    prior = sorted(d for d in activity if d < day)[-window:]
    if len(prior) < window:
        return None
    vals = [activity[d] for d in prior]
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
    if var <= 0:
        return None
    return (activity[day] - mean) / (var ** 0.5)


def classify_days(activity: dict[date, float],
                  z_thresh: float = DEFAULT_Z,
                  window: int = DEFAULT_WINDOW) -> dict[str, list[date]]:
    """Split trading days into flow / ordinary buckets by z-score."""
    flow: list[date] = []
    ordinary: list[date] = []
    for day in sorted(activity):
        z = zscore(activity, day, window)
        if z is None:
            continue  # warmup days carry no verdict
        (flow if z >= z_thresh else ordinary).append(day)
    return {"flow": flow, "ordinary": ordinary}
