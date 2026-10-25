"""Deterministic paper executor for approved TradeSpecs.

Contract (same as future IBridgePy adapter):
- Input: exactly one pydantic TradeSpec already stamped backtest_gate == approved.
- Strikes are reconstructed with the SAME geometry the backtest gate used
  (swarm.backtest.gate._pick_strikes) so paper results are comparable to it.
- Fill prices are Black-Scholes marks with IV = realized 20d vol * IV_BLOAT,
  identical to the gate simulator. No LLM ever touches this module.
- Output: one order JSON per trade under data/orders/<trade_id>.json.

Entries fill at the most recent UW close (same-bar close, no lookahead beyond
what the backtest contract already documents). The chair's entry trigger is
advisory in the paper book: timing fidelity is a documented limitation.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from swarm.backtest.gate import (
    IV_BLOAT,
    CloseSeries,
    _direction,
    _pick_strikes,
    bs_legs,
    metrics_for_direction,
)
from swarm.models import TradeSpec

ORDERS_DIR = Path("data/orders")
ORDERS_DIR.mkdir(parents=True, exist_ok=True)

MULTIPLIER = 100
MAX_QTY = 10  # per spec; keeps single-name concentration bounded
MIN_CONTRACT_RISK_USD = 25.0


class Leg(BaseModel):
    action: str = Field(description="buy or sell")
    right: str = Field(description="C or P")
    strike: float
    qty: int
    fill_price: float = Field(description="$ per contract at fill")


class OrderRecord(BaseModel):
    trade_id: str
    underlying: str
    strategy: str
    expiry: str
    direction: str
    max_risk_usd: float
    entry_date: str
    entry_spot: float
    entry_iv: float
    dte: int
    net_usd: float = Field(description="credit received (credit) or debit paid (debit/long), per contract")
    risk_usd_one: float = Field(description="max loss per contract")
    qty: int
    committed_risk_usd: float = Field(description="qty * risk_usd_one")
    legs: list[Leg]
    status: str = "open"
    closed_date: str | None = None
    exit_kind: str | None = None
    exit_spot: float | None = None
    unrealized_usd: float | None = None
    pnl_usd: float | None = None
    pnl_r: float | None = None


def execute_paper(spec: TradeSpec, uw, dte: int = 7) -> OrderRecord:
    """Fill the spec on the paper book. Deterministic given UW close history.

    Raises ValueError if the spec is not approved, if reconstructed single-
    contract risk exceeds the cap, or the structure is degenerate.
    """
    if spec.backtest_gate.value != "approved":
        raise ValueError(f"{spec.trade_id}: not approved (gate={spec.backtest_gate.value})")

    series = CloseSeries.from_uw(uw, spec.underlying)
    if len(series.closes) < 30:
        raise ValueError(f"{spec.trade_id}: insufficient close history")
    i = len(series.closes) - 1
    spot = series.closes[i]
    entry_date = series.dates[i]
    iv = series.realized_vol_20(i) * IV_BLOAT

    direction = _direction(spec.strategy.value)
    is_call = direction not in ("put_credit", "put_debit")
    short_k, long_k = _pick_strikes(spot, direction, dte)
    t0 = dte / 252
    net_pts, risk_pts = metrics_for_direction(
        spot, short_k, long_k, t0, iv, is_call, direction,
        min_net=max(1.0, 0.002 * spot),  # identical degenerate filter as the gate
    )
    short_fill, long_fill = bs_legs(spot, short_k, long_k, t0, iv, is_call)
    net_usd, risk_usd_one = net_pts * MULTIPLIER, risk_pts * MULTIPLIER

    if risk_usd_one > spec.max_risk_usd:
        raise ValueError(
            f"{spec.trade_id}: single-contract risk ${risk_usd_one:.2f} exceeds cap ${spec.max_risk_usd}"
        )
    if risk_usd_one < MIN_CONTRACT_RISK_USD:
        raise ValueError(f"{spec.trade_id}: contract risk ${risk_usd_one:.2f} below minimum")
    qty = int(spec.max_risk_usd // risk_usd_one)
    if qty < 1:
        raise ValueError(f"{spec.trade_id}: cap {spec.max_risk_usd} cannot fund any contract")
    qty = min(qty, MAX_QTY)

    legs: list[Leg] = []
    if short_k is not None:
        legs.append(Leg(action="sell", right="C" if is_call else "P",
                        strike=float(short_k), qty=qty,
                        fill_price=round(short_fill * MULTIPLIER, 2)))
    if long_k is not None:
        legs.append(Leg(action="buy", right="C" if is_call else "P",
                        strike=float(long_k), qty=qty,
                        fill_price=round(long_fill * MULTIPLIER, 2)))

    rec = OrderRecord(
        trade_id=spec.trade_id,
        underlying=spec.underlying,
        strategy=spec.strategy.value,
        expiry=spec.expiry,
        direction=direction,
        max_risk_usd=spec.max_risk_usd,
        entry_date=entry_date.isoformat(),
        entry_spot=spot,
        entry_iv=round(iv, 4),
        dte=dte,
        net_usd=round(net_usd, 2),
        risk_usd_one=round(risk_usd_one, 2),
        qty=qty,
        committed_risk_usd=round(risk_usd_one * qty, 2),
        legs=legs,
    )
    (ORDERS_DIR / f"{spec.trade_id}.json").write_text(rec.model_dump_json(indent=2))
    return rec
