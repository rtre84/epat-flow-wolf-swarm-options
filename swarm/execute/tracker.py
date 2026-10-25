"""Paper-book mark-to-market and P&L tracker.

For every open order record this walks the UW close series from the entry bar
using the exact close logic of the backtest gate (stop at 2x premium for
credits / near-zero for debits, otherwise hold to DTE expiry). If the series
hasn't reached expiry yet the record stays open with an unrealized $ mark.

Outputs:
- updated data/orders/*.json (status/pnl fields)
- data/pnl/summary.json for the learning loop
"""
from __future__ import annotations

import json
from pathlib import Path

from swarm.backtest.gate import CloseSeries, position_outcome
from swarm.execute.paper import MULTIPLIER, ORDERS_DIR

PNL_DIR = Path("data/pnl")
PNL_DIR.mkdir(parents=True, exist_ok=True)


def _strikes_from_record(rec: dict) -> tuple[float | None, float | None]:
    short = next((l["strike"] for l in rec["legs"] if l["action"] == "sell"), None)
    long_ = next((l["strike"] for l in rec["legs"] if l["action"] == "buy"), None)
    return short, long_


def mark_all(uw) -> dict:
    """Re-mark every open order record; closes any that hit stop or expiry.

    Returns the summary dict also written to data/pnl/summary.json.
    """
    results: list[dict] = []
    for path in sorted(ORDERS_DIR.glob("*.json")):
        rec = json.loads(path.read_text())
        if rec.get("status") != "open":
            results.append({"trade_id": rec["trade_id"], "status": rec["status"], "changed": False})
            continue

        series = CloseSeries.from_uw(uw, rec["underlying"])
        dates = [str(x) for x in series.dates]
        if rec["entry_date"] not in dates:
            results.append({"trade_id": rec["trade_id"], "status": "error", "changed": False,
                            "reason": "entry_date missing from close series"})
            continue
        entry_i = dates.index(rec["entry_date"])

        direction = rec["direction"]
        short_k, long_k = _strikes_from_record(rec)
        net_pts = rec["net_usd"] / MULTIPLIER
        risk_pts = rec["risk_usd_one"] / MULTIPLIER

        out = position_outcome(series, entry_i, direction, short_k, long_k,
                               rec["entry_iv"], net_pts, risk_pts, rec["dte"])
        qty = rec["qty"]
        if out["kind"] in ("stopped", "expiry"):
            rec["status"] = "closed"
            rec["exit_kind"] = out["kind"]
            rec["exit_spot"] = out["exit_spot"]
            rec["closed_date"] = out["exit_date"]
            rec["pnl_usd"] = round(out["pnl"] * MULTIPLIER * qty, 2)
            rec["pnl_r"] = round(out["pnl"] / risk_pts, 3)
        else:
            mark_pts = out["value"]
            cur_pts = (net_pts - mark_pts) if direction.endswith("credit") else (mark_pts - net_pts)
            rec["unrealized_usd"] = round(cur_pts * MULTIPLIER * qty, 2)
        path.write_text(json.dumps(rec, indent=2))
        results.append({"trade_id": rec["trade_id"], "status": rec["status"], "changed": True})
    return summarize(results)


def summarize(results: list[dict]) -> dict:
    closed: list[dict] = []
    open_count = 0
    committed_open = 0.0
    for path in sorted(ORDERS_DIR.glob("*.json")):
        rec = json.loads(path.read_text())
        if rec.get("status") == "closed" and rec.get("pnl_usd") is not None:
            closed.append(rec)
        elif rec.get("status") == "open":
            open_count += 1
            committed_open += rec.get("committed_risk_usd", 0.0)
    pnls = [r["pnl_usd"] for r in closed]
    rs = [r["pnl_r"] for r in closed if r.get("pnl_r") is not None]
    summary = {
        "tracked": len(results),
        "open": open_count,
        "closed": len(closed),
        "realized_pnl_usd": round(sum(pnls), 2),
        "open_committed_risk_usd": round(committed_open, 2),
        "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls), 3) if pnls else None,
        "mean_r": round(sum(rs) / len(rs), 3) if rs else None,
        "records": results,
    }
    (PNL_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary
