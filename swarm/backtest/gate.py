"""Custom daily-bar simulator for the 6 defined-risk archetypes.

Fidelity contract (documented limitation):
- Underlying bars: UW daily closes (5Y pull), not intraday.
- Option legs: Black-Scholes marks with entry IV = realized 20d vol * 1.15
  (premium-rich) and no smile; spread structure and time decay are exact.
- Entry: every `step_days` trading days, both 7d (weekly) and 30d (monthly)
  holds simulated independently.
- Exit: stop at defined max loss (2x net premium) or expiry, whichever first.

This validates the *archetype on this ticker* (population stats), not one
hand-picked contract. The chair's prose triggers stay unverifiable math on
purpose: LLM text never gates execution.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from swarm.tools.uw import UWMCPClient

CACHE_DIR = Path("data/backtests/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DAYS_PER_YEAR = 252
IV_BLOAT = 1.15
ENTRY_STEP_DAYS = 5
STRATEGIES = (
    "long_call", "long_put",
    "bull_put_spread", "bear_call_spread",
    "bull_call_spread", "bear_put_spread",
)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, t_years: float, iv: float, is_call: bool) -> float:
    if t_years <= 0 or iv <= 0 or spot <= 0:
        return max(0.0, (spot - strike) if is_call else (strike - spot))
    vol_t = iv * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * t_years) / vol_t
    d2 = d1 - vol_t
    if is_call:
        return spot * _norm_cdf(d1) - strike * _norm_cdf(d2)
    return strike * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


@dataclass
class CloseSeries:
    dates: list[date]
    closes: list[float]

    @classmethod
    def from_uw(cls, uw: UWMCPClient, ticker: str) -> "CloseSeries":
        cache = CACHE_DIR / f"{ticker}_close_5y.json"
        if cache.exists():
            payload = json.loads(cache.read_text())
        else:
            r = uw.call_tool("get_ticker_close_prices", {"ticker": ticker, "timeframe": "5Y"})
            payload = json.loads(r["result"]["content"][0]["text"]).get("data", [])
            cache.write_text(json.dumps(payload))
        rows = sorted(payload, key=lambda x: x["date"])
        return cls([date.fromisoformat(r["date"]) for r in rows], [float(r["c"]) for r in rows])

    def realized_vol_20(self, i: int) -> float:
        if i < 20:
            return 0.35
        rets = [math.log(self.closes[j] / self.closes[j - 1]) for j in range(i - 19, i + 1)]
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        return max(0.08, min(3.0, math.sqrt(var * DAYS_PER_YEAR)))


def _pick_strikes(spot: float, direction: str, dte: int) -> tuple[float | None, float | None]:
    """Archetype (short, long) strikes as % offsets from spot. Longs have short=None."""
    if direction == "long":
        return None, spot * 1.00  # ATM-ish long option
    return {
        "put_credit": (spot * 0.96, spot * 0.91),   # sell lower put, buy lower put
        "call_credit": (spot * 1.04, spot * 1.09),  # sell near call, buy far call
        "call_debit": (spot * 1.04, spot * 1.00),   # buy near call, sell far call
        "put_debit": (spot * 0.96, spot * 1.00),    # buy near put, sell lower put
    }[direction]  # direction "long" returns early above


def _direction(strategy: str) -> str:
    return {
        "long_call": "long",
        "long_put": "long",
        "bull_put_spread": "put_credit",
        "bear_call_spread": "call_credit",
        "bull_call_spread": "call_debit",
        "bear_put_spread": "put_debit",
    }[strategy]


def simulate_archetype(series: CloseSeries, strategy: str, dte: int) -> list[float]:
    """Enter archetype every ENTRY_STEP_DAYS; returns list of R-multiples (pnl/risk)."""
    direction = _direction(strategy)
    results: list[float] = []
    n = len(series.dates)
    for i in range(20, n - 1, ENTRY_STEP_DAYS):
        spot = series.closes[i]
        entry_date = series.dates[i]
        iv0 = series.realized_vol_20(i) * IV_BLOAT
        short_k, long_k = _pick_strikes(spot, direction, dte)
        t0 = dte / DAYS_PER_YEAR
        call_short = direction not in ("put_credit", "put_debit")
        leg_short = 0.0 if short_k is None else bs_price(spot, short_k, t0, iv0, call_short)
        leg_long = 0.0 if long_k is None else bs_price(spot, long_k, t0, iv0, call_short)
        if "credit" in direction:
            net = leg_short - leg_long  # credit received
        else:
            net = leg_long - leg_short  # debit paid
        if net <= max(1.0, 0.002 * spot):  # degenerate spread
            continue
        risk = (abs(short_k - long_k) - net) if "credit" in direction else net
        if risk <= 0:
            continue

        stopped = False
        expiry_i = min(i + dte, n - 1)
        test_i = i
        while test_i < expiry_i:
            test_i += 1
            cur_spot = series.closes[test_i]
            t_left = max(0.0, (dte - (test_i - i)) / DAYS_PER_YEAR)
            short_m = 0.0 if short_k is None else bs_price(cur_spot, short_k, t_left, iv0, call_short)
            long_m = 0.0 if long_k is None else bs_price(cur_spot, long_k, t_left, iv0, call_short)
            if "credit" in direction:
                value = short_m - long_m  # cost to close: sold leg minus bought leg
                if value >= net + risk:
                    stopped = True
                    break
            else:
                value = long_m - short_m  # position worth; we want it big
                if value <= 0.02 * net:
                    stopped = True
                    break
        if stopped:
            pnl = (-risk) if "credit" in direction else (-risk)
        else:
            cur_spot = series.closes[expiry_i]
            short_m = 0.0 if short_k is None else bs_price(cur_spot, short_k, 0.0, iv0, call_short)
            long_m = 0.0 if long_k is None else bs_price(cur_spot, long_k, 0.0, iv0, call_short)
            if "credit" in direction:
                pnl = net - (short_m - long_m)          # credit minus closing cost
            else:
                pnl = (long_m - short_m) - net          # position gain minus debit
        results.append(pnl / risk)
    return results


def evaluate(series: CloseSeries, strategy: str, dte: int) -> dict:
    rs = simulate_archetype(series, strategy, dte)
    if not rs:
        return {"dte": dte, "n": 0, "win_rate": 0.0, "mean_r": 0.0, "median_r": 0.0, "max_r": 0.0, "min_r": 0.0}
    rs.sort()
    n = len(rs)
    return {
        "dte": dte,
        "n": n,
        "win_rate": round(sum(1 for r in rs if r > 0) / n, 3),
        "mean_r": round(sum(rs) / n, 3),
        "median_r": round(rs[n // 2], 3),
        "max_r": round(rs[-1], 3),
        "min_r": round(rs[0], 3),
    }


def run_gate(ticker: str, strategy: str, uws: UWMCPClient | None = None) -> dict:
    """Full archetype gate: both 7d and 30d holds; pass requires one hold profile
    to clear n>=30, win_rate>=0.30, mean_r>=0.05."""
    uw = uws or UWMCPClient()
    uw.initialize()
    series = CloseSeries.from_uw(uw, ticker)
    report = {"ticker": ticker, "strategy": strategy, "profiles": {}}
    best = None
    for dte in (7, 30):
        m = evaluate(series, strategy, dte)
        report["profiles"][f"{dte}d"] = m
        candidate = m["n"] >= 30 and m["win_rate"] >= 0.30 and m["mean_r"] >= 0.05
        report[f"{dte}d_pass"] = candidate
        best = best or candidate
    report["gate_pass"] = bool(best)
    # slice recent-regime sanity: re-run last 6 months only
    months = 128  # ~6 months of bars
    recent = CloseSeries(series.dates[-months:], series.closes[-months:])
    for dte in (7, 30):
        m = evaluate(recent, strategy, dte)
        report["profiles"][f"{dte}d_recent"] = m
        report[f"{dte}d_recent_pass"] = (
            m["n"] >= 8 and m["win_rate"] >= 0.25 and m["mean_r"] >= 0.0
        )
    return report


def gate_spec(spec: dict, uws: UWMCPClient | None = None) -> dict:
    """Backtest-gate one spec dict — writes report under data/backtests/."""
    out_dir = Path("data/backtests")
    out_dir.mkdir(parents=True, exist_ok=True)
    report = run_gate(spec["underlying"], spec["strategy"], uws)
    report["trade_id"] = spec["trade_id"]
    (out_dir / f"{spec['trade_id']}.json").write_text(json.dumps(report, indent=2))
    spec = dict(spec)
    # recent-regime sanity is advisory in v1 (documented limitation)
    spec["backtest_gate"] = "approved" if report["gate_pass"] else "rejected"
    return spec
