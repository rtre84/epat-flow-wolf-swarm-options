"""Pure helpers: strike grids, expiry selection, Polygon option tickers.

No network, fully unit-tested. Polygon option ticker format:
O:{UNDERLYING}{YYMMDD}{C|P}{strike*1000 zero-padded to 8}

Strike grids mirror listed-chain conventions: index ETFs quote $1 strikes
at any price; single names step $1 / $2.5 / $5 as price rises. This matters
for the study's honesty: a $300-budget spread can only exist where the
real grid admits it (e.g. 2-pt widths on SPY's $1 grid — not on a $738
stock's $5 grid, whose narrowest spread risks ~$500).
"""
from __future__ import annotations

from datetime import date, timedelta

INDEX_ETFS = {"SPY", "QQQ", "IWM", "DIA"}


def strike_step(ticker: str, price: float) -> float:
    if ticker.upper() in INDEX_ETFS:
        return 1.0
    if price < 200:
        return 1.0
    if price < 500:
        return 2.5
    return 5.0


def round_strike(price: float, step: float) -> float:
    """Nearest strike on the given grid."""
    return round(price / step) * step


def next_expiry(day: date, min_days: int) -> date:
    """Next standard Friday expiry at least `min_days` calendar days out."""
    candidate = day + timedelta(days=min_days)
    days_ahead = (4 - candidate.weekday()) % 7  # Friday == weekday 4
    return candidate + timedelta(days=days_ahead)


def option_ticker(underlying: str, expiry: date, cp: str, strike: float) -> str:
    """O:SYMYYMMDD[C/P]NNNNNNNN — Polygon's contract identifier."""
    if cp not in ("C", "P"):
        raise ValueError(f"right must be C or P, got {cp}")
    return (f"O:{underlying.upper()}{expiry.strftime('%y%m%d')}"
            f"{cp}{int(round(strike * 1000)):08d}")


def spread_strikes(spot: float, ticker: str = "",
                   cap_usd: float = 300.0, buffer: float = 0.8) -> tuple[float, float]:
    """Bull-put-spread strikes under the live pipeline's Phase 7 geometry,
    projected onto the REAL strike grid: short at 0.96x spot, width capped
    to the risk budget — but never narrower than one grid step, because
    narrower spreads are not listed."""
    step = strike_step(ticker, spot)
    short_k = round_strike(spot * 0.96, step)
    budget_width = max(step, float(int(cap_usd * buffer / 100)))
    width = max(step, min(spot * 0.05, budget_width))
    return short_k, short_k - width
