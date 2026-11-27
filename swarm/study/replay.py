"""Replay engine: the live pipeline's entry rule on real historical quotes.

Per (day, ticker): sell the budget-capped bull put spread at the day's real
EOD contract closes, hold to expiry, settle at the underlying's expiry-day
close. Identical entries run on flow AND ordinary days (bucketed later), so
the comparison isolates the flow signal's edge with hundreds of samples.

Documented simplifications vs the live paper book (both conservative):
- expiry-only exits: the live book also stops credits at 2x premium; skips
  intraday stop checks that would need per-day leg marks.
- strikes land on the real chain grid (the live book uses raw floats).

This module is pure (no network): the orchestrator pulls bars and calls
replay_entry with real quotes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from swarm.study.contracts import (next_expiry, option_ticker, round_strike,
                                   spread_strikes, strike_step)

NET_FLOOR_FRAC = 0.10  # mirrors the gate's width-scaled net floor
NET_FLOOR_ABS = 0.25
DEFAULT_CAP_USD = 300.0
SIGNAL_MIN_DAYS = 3    # nearest weekly expiry for the ATM activity proxy
ENTRY_MIN_DAYS = 7    # entry expiry horizon, matching the live 7-DTE book
SETTLE_RANGE_DAYS = 45  # contract agg range: entry day out past expiry


@dataclass
class ReplayResult:
    ticker: str
    day: str
    expiry: str
    short_k: float
    long_k: float
    credit: float          # points, real EOD closes
    risk: float            # points
    exit_spot: float
    pnl: float             # points per contract
    r: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker, "day": self.day, "expiry": self.expiry,
            "short_k": self.short_k, "long_k": self.long_k,
            "credit": self.credit, "risk": self.risk,
            "exit_spot": self.exit_spot, "pnl": self.pnl, "r": self.r,
        }


def settle_put_spread(credit: float, short_k: float, long_k: float,
                      spot_at_expiry: float) -> tuple[float, float]:
    """(pnl_points, payoff_points) at expiry; cash-settled approximation
    at the expiry-day underlying close."""
    payoff = max(short_k - spot_at_expiry, 0.0) - max(long_k - spot_at_expiry, 0.0)
    return credit - payoff, payoff


def replay_entry(ticker: str, day: date, spot: float,
                 short_close: float | None, long_close: float | None,
                 exit_spot: float, cap_usd: float = DEFAULT_CAP_USD) -> ReplayResult | None:
    """One spread entry at real closes. None (skip) when quotes are missing,
    the structure is degenerate, or the real-grid width cannot fund inside
    the risk budget — the live gate's filters plus the executor's cap."""
    short_k, long_k = spread_strikes(spot, ticker=ticker, cap_usd=cap_usd)
    if short_close is None or long_close is None:
        return None
    if exit_spot is None:
        return None  # expiry not yet in underlying history (entry too recent)
    credit = short_close - long_close
    risk = (short_k - long_k) - credit
    if risk * 100 > cap_usd:
        return None  # one contract exceeds the budget on the real grid
    floor = max(NET_FLOOR_ABS, NET_FLOOR_FRAC * (short_k - long_k))
    if credit <= floor or risk <= 0:
        return None
    expiry = next_expiry(day, ENTRY_MIN_DAYS)
    pnl, _ = settle_put_spread(credit, short_k, long_k, exit_spot)
    return ReplayResult(
        ticker=ticker, day=day.isoformat(), expiry=expiry.isoformat(),
        short_k=short_k, long_k=long_k,
        credit=round(credit, 2), risk=round(risk, 2),
        exit_spot=round(exit_spot, 2), pnl=round(pnl, 3),
        r=round(pnl / risk, 3))


def day_contracts(ticker: str, day: date, spot: float) -> list[tuple[str, str]]:
    """Contracts to pull for one (day, ticker): ATM call+put (flow signal
    activity) plus the spread legs (entry). [(label, opra)]"""
    out: list[tuple[str, str]] = []

    def add(label: str, op: str, k: float, expiry: date) -> None:
        out.append((label, option_ticker(ticker, expiry, op, k)))

    atm = round_strike(spot, strike_step(ticker, spot))
    for label, op in (("atm_call", "C"), ("atm_put", "P")):
        add(label, op, atm, next_expiry(day, SIGNAL_MIN_DAYS))
    short_k, long_k = spread_strikes(spot, ticker=ticker)
    expiry = next_expiry(day, ENTRY_MIN_DAYS)
    add("short_leg", "P", short_k, expiry)
    add("long_leg", "P", long_k, expiry)
    return out


def pull_range(day: date) -> str:
    """Aggregates window for one day's contracts (entry day to expiry+buffer)."""
    return (day + timedelta(days=SETTLE_RANGE_DAYS)).isoformat()
