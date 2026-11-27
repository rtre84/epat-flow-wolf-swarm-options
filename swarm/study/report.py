"""Bucket stats + the flow-vs-ordinary report."""
from __future__ import annotations

from datetime import date

from swarm.study.replay import ReplayResult


def bucket_stats(results: list[ReplayResult]) -> dict:
    if not results:
        return {"n": 0, "win_rate": None, "mean_r": None, "median_r": None,
                "mean_credit": None}
    rs = [r.r for r in results]
    rs.sort()
    n = len(rs)
    return {
        "n": n,
        "win_rate": round(sum(1 for r in rs if r > 0) / n, 3),
        "mean_r": round(sum(rs) / n, 3),
        "median_r": round(rs[n // 2], 3),
        "mean_credit": round(sum(r.credit for r in results) / n, 2),
    }


def report(flow: list[ReplayResult], ordinary: list[ReplayResult],
           z_thresh: float, tickers: list[str],
           day_from: date, day_to: date,
           per_ticker: dict[str, list[str]] | None = None) -> dict:
    payload = {
        "z_thresh": z_thresh,
        "tickers": tickers,
        "range": [day_from.isoformat(), day_to.isoformat()],
        "per_ticker_ranges": per_ticker,
        "flow": bucket_stats(flow),
        "ordinary": bucket_stats(ordinary),
        "edge": None,
    }
    f, o = payload["flow"], payload["ordinary"]
    if f["mean_r"] is not None and o["mean_r"] is not None:
        payload["edge"] = round(f["mean_r"] - o["mean_r"], 3)
    return payload


def markdown(payload: dict) -> str:
    f, o = payload["flow"], payload["ordinary"]

    def row(name: str, s: dict) -> str:
        wr = "-" if s["win_rate"] is None else f"{s['win_rate']:.1%}"
        mr = "-" if s["mean_r"] is None else f"{s['mean_r']:+.3f}"
        med = "-" if s["median_r"] is None else f"{s['median_r']:+.3f}"
        cr = "-" if s["mean_credit"] is None else f"{s['mean_credit']:.2f}"
        return (f"| {name} | {s['n']} | {wr} | {mr} | {med} | {cr} |")

    out = [
        "# Baseline: mechanical flow rule vs ordinary days",
        "",
        f"Rule: ATM call+put volume z-score ≥ {payload['z_thresh']} "
        f"(trailing 20 days) = flow day.",
        f"Universe: {', '.join(payload['tickers'])}; "
        f"{payload['range'][0]} → {payload['range'][1]}.",
    ]
    per_ticker = payload.get("per_ticker_ranges")
    if per_ticker:
        out.append("Per-ticker ranges: " + "; ".join(
            f"{t} {r[0]}→{r[1]}" for t, r in sorted(per_ticker.items())) +
            ".")
    out += [
        "Entry: bull put spread, short 0.96×spot (grid), width capped to "
        "the $300 budget, 7+ day expiry, real EOD closes; expiry settle.",
        "",
        "| bucket | n | win rate | mean R | median R | mean credit |",
        "|---|---|---|---|---|---|",
        row("flow days", f),
        row("ordinary days", o),
        "",
    ]
    if payload["edge"] is not None:
        out.append(f"**Flow edge: {payload['edge']:+.3f} R** "
                   f"(flow mean R minus ordinary mean R)")
    return "\n".join(out)
