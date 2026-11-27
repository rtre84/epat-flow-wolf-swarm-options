"""CLI orchestrator: pull → signals → replay → report.

  python -m swarm.study run --tickers SPY,QQQ,TSLA,NVDA,MU \
      --start 2025-11-01 --end 2026-11-25 [--z 2.0] [--stride 1]

Stages are cache-backed and resumable: every Polygon response lands in
data/study/cache/, so a re-run costs nothing until the range grows.

Per (ticker, day) it pulls 4 contracts (ATM call+put for the signal,
spread legs for the entry) plus the underlying's daily bars once per
ticker. Ordinary days replay the identical entry so the buckets differ
only by the flow signal.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from swarm.study.client import PolygonClient, bars
from swarm.study.contracts import next_expiry
from swarm.study.flow_rule import classify_days, DEFAULT_Z
from swarm.study.replay import day_contracts, pull_range, replay_entry, ReplayResult
from swarm.study.report import markdown, report

OUT_DIR = Path("data/study")
OUT_DIR.mkdir(parents=True, exist_ok=True)
PULL_SLEEP = 0.15  # politeness even on unlimited tiers


def _ms_to_day(ms: int) -> str:
    return date.fromtimestamp(ms / 1000).isoformat()


def trading_days(stock_payload: dict, day_from: str, day_to: str) -> list[tuple[date, float]]:
    """[(day, close)] for the underlying — the study calendar and spot."""
    out = []
    for b in bars(stock_payload):
        d = _ms_to_day(b["t"])
        if day_from <= d <= day_to:
            out.append((date.fromisoformat(d), b["c"]))
    return out


def _contract_day_bars(payload: dict) -> dict[str, dict]:
    return {_ms_to_day(b["t"]): b for b in bars(payload)}


def pull_day_contracts(client: PolygonClient, ticker: str, day: date,
                       spot: float) -> dict[str, dict[str, dict]]:
    """{label: {day_iso: bar}} for the day's four contracts."""
    out: dict[str, dict[str, dict]] = {}
    to_day = pull_range(day)
    for label, opra in day_contracts(ticker, day, spot):
        payload = client.contract_aggs(opra, day.isoformat(), to_day)
        out.setdefault(label, {})[opra] = _contract_day_bars(payload)
        time.sleep(PULL_SLEEP)
    return out


def _entry_close(day_bars: dict[str, dict], day: date) -> float | None:
    bar = day_bars.get(day.isoformat())
    return None if bar is None or bar["c"] is None else bar["c"]


def _atm_activity(day_bars: dict[str, dict[str, dict]], day: date) -> float:
    total = 0.0
    for label in ("atm_call", "atm_put"):
        for by_day in day_bars.get(label, {}).values():
            bar = by_day.get(day.isoformat())
            if bar:
                total += bar["v"]
    return total


def run(tickers: list[str], day_from: date, day_to: date,
        z_thresh: float = DEFAULT_Z, stride: int = 1,
        client: PolygonClient | None = None,
        raw_out: str | None = None) -> dict:
    cli = client or PolygonClient()
    all_flow: list[ReplayResult] = []
    all_ordinary: list[ReplayResult] = []
    tagged: list[dict] = []  # bucket-tagged raw entries for merging
    for ticker in tickers:
        stock = cli.stock_aggs(ticker, day_from.isoformat(),
                               (day_to + timedelta(days=45)).isoformat())
        stock_days = {d: b for d, b in
                      ((_ms_to_day(b["t"]), b) for b in bars(stock))}
        days = trading_days(stock, day_from.isoformat(), day_to.isoformat())
        if not days:
            print(f"[skip] {ticker}: no bars in range", file=sys.stderr)
            continue

        activity: dict[date, float] = {}
        pulled: dict[date, dict[str, dict[str, dict]]] = {}
        for i, (day, spot) in enumerate(days):
            print(f"[pull] {ticker} {day} ({i + 1}/{len(days)})",
                  file=sys.stderr)
            day_bars = pull_day_contracts(cli, ticker, day, spot)
            pulled[day] = day_bars
            activity[day] = _atm_activity(day_bars, day)

        buckets = classify_days(activity, z_thresh=z_thresh)
        replayed: dict[date, ReplayResult | None] = {}
        for j, (day, spot) in enumerate(days):
            in_flow = day in set(buckets["flow"])
            if not in_flow and stride > 1 and j % stride != 0:
                continue  # subsample ordinary days
            short_close = long_close = exit_spot = None
            day_bars = pulled[day]
            for by_day in day_bars["short_leg"].values():
                short_close = _entry_close(by_day, day)
            for by_day in day_bars["long_leg"].values():
                long_close = _entry_close(by_day, day)
            expiry = next_expiry(day, 7)
            exit_bar = stock_days.get(expiry.isoformat())
            if exit_bar is not None:
                exit_spot = exit_bar["c"]
            res = replay_entry(ticker, day, spot, short_close, long_close,
                               exit_spot)
            replayed[day] = res

        for day, res in replayed.items():
            if res is None:
                continue
            in_flow = day in set(buckets["flow"])
            (all_flow if in_flow else all_ordinary).append(res)
            tagged.append({**res.to_dict(),
                          "bucket": "flow" if in_flow else "ordinary"})
        print(f"[done] {ticker}: flow={len(buckets['flow'])} "
              f"ordinary={len(buckets['ordinary'])}", file=sys.stderr)

    if raw_out:
        Path(raw_out).write_text(json.dumps(tagged, indent=2))
        print(f"[raw] {len(tagged)} entries -> {raw_out}", file=sys.stderr)
    payload = report(all_flow, all_ordinary, z_thresh, tickers,
                     day_from, day_to)
    (OUT_DIR / "baseline.json").write_text(json.dumps(payload, indent=2))
    (OUT_DIR / "baseline.md").write_text(markdown(payload))
    print(markdown(payload))
    return payload


def merge(paths: list[str], z_thresh: float = DEFAULT_Z,
          out_prefix: str = "data/study/baseline_4y") -> dict:
    """Combine raw entry dumps from several runs into one report. Buckets
    were assigned per-run, so entries merge directly; per-ticker ranges
    come from the entries themselves (split-affected names may start
    later than the global range)."""
    from types import SimpleNamespace

    entries = []
    for p in paths:
        entries.extend(json.loads(Path(p).read_text()))
    if not entries:
        raise RuntimeError("no entries found in raw files")

    flow = [SimpleNamespace(**e) for e in entries if e["bucket"] == "flow"]
    ordinary = [SimpleNamespace(**e) for e in entries
                if e["bucket"] == "ordinary"]
    tickers = sorted({e["ticker"] for e in entries})
    per_ticker = {}
    for t in tickers:
        days = sorted(e["day"] for e in entries if e["ticker"] == t)
        per_ticker[t] = [days[0], days[-1]]
    lo = min(e["day"] for e in entries)
    hi = max(e["day"] for e in entries)

    payload = report(flow, ordinary, z_thresh, tickers,
                     date.fromisoformat(lo), date.fromisoformat(hi),
                     per_ticker=per_ticker)
    out_json = Path(f"{out_prefix}.json")
    out_md = Path(f"{out_prefix}.md")
    out_json.write_text(json.dumps(payload, indent=2))
    out_md.write_text(markdown(payload))
    print(markdown(payload))
    return payload


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="swarm.study")
    p.add_argument("command", choices=["run", "merge"])
    if "--merge" in argv or (argv and argv[0] == "merge"):
        p.add_argument("paths", nargs="+", help="raw entry dumps to merge")
        p.add_argument("--z", type=float, default=DEFAULT_Z)
        p.add_argument("--out", default="data/study/baseline_4y")
        args = p.parse_args(argv)
        merge(args.paths, z_thresh=args.z, out_prefix=args.out)
        return 0
    p.add_argument("--tickers", default="SPY,QQQ,TSLA,NVDA,MU")
    p.add_argument("--start", default="2025-11-01")
    p.add_argument("--end", default=date.today().isoformat())
    p.add_argument("--z", type=float, default=DEFAULT_Z)
    p.add_argument("--stride", type=int, default=1,
                   help="subsample ordinary days (2 = every other day)")
    p.add_argument("--raw-out", default=None,
                   help="dump all entries (bucket-tagged) for later merging")
    args = p.parse_args(argv)
    run([t.strip().upper() for t in args.tickers.split(",")],
        date.fromisoformat(args.start), date.fromisoformat(args.end),
        z_thresh=args.z, stride=args.stride, raw_out=args.raw_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
